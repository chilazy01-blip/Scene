"""Material-aware rigid mass properties from undilated component voxels.

Values are explicit modeling priors, never measurements of generated assets.
The collision SDF builder is reused at zero dilation. Open surfaces remain
surfaces; their artificial voxel thickness is never multiplied by solid density.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation

from .collision_mesh_cleanup import CollisionMeshCleanupConfig, cleanup_collision_mesh
from .multilevel_proxy import build_component_aware_sdf, mesh_content_hash

SCHEMA = 'scene-v2-material-voxel-mass/v1'
# Representative design values with uncertainty ranges, not a calibrated dataset.
# Paper: UPM Book bulk 1.3--1.65 cm3/g implies approximately 606--769 kg/m3.
DENSITIES = {
    'paper': (700., 450., 1000.), 'wood': (650., 350., 900.),
    'oak': (700., 550., 850.), 'walnut': (650., 500., 800.),
    'steel': (7850., 7700., 8050.), 'aluminum': (2700., 2600., 2850.),
    'brass': (8500., 8000., 8900.), 'plastic': (1050., 850., 1450.),
    'metal': (5000., 2700., 8900.),
    'glass': (2500., 2200., 2800.), 'rubber': (1100., 900., 1400.),
}
FAMILY_ALIASES = {'timber':'wood', 'aluminium':'aluminum', 'polymer':'plastic'}
# These are category-conditioned ENVELOPE densities used only when material
# volume cannot be established; they must not be applied to surface voxels.
ENVELOPE_PRIORS = {
    'single_book': (650., 450., 950.), 'book': (650., 450., 950.),
    'bookcase': (100., 45., 220.), 'cabinet': (130., 60., 260.),
    'chair': (160., 60., 350.), 'sofa': (75., 35., 150.),
    'storage_box': (100., 25., 250.), 'general_object': (150., 30., 500.),
}
SOLID_STRUCTURES = {'solid', 'solid_panels', 'bound_paper_block', 'solid_part'}


def profile_from_material_slots(category: str, slots: list[dict], *, structure: str = 'unknown',
                                explicit: dict | None = None) -> dict:
    """Reuse material-library families and roles, preserving surface/bulk scope.

    Texture pixels and metallic/roughness values alone do not establish bulk
    composition. A declared structural slot can provide a density prior; mixed
    structures need part-level data or the category fallback.
    """
    if explicit is not None:
        return {'category':category, **explicit}
    families=set();structural=set();evidence=[]
    for slot in slots:
        family=str(slot.get('material_family','')).strip().lower()
        family=FAMILY_ALIASES.get(family,family)
        if family not in DENSITIES:continue
        families.add(family)
        scope=slot.get('material_scope','appearance')
        role=slot.get('slot_role','')
        if scope=='bulk' and role in {'furniture_body','load_bearing_frame','shelves','page_block','solid_part'}:
            structural.add(family)
        evidence.append({'family':family,'scope':scope,'slot_role':role,'package_id':slot.get('package_id')})
    bulk=len(structural)==1
    candidates=structural if bulk else families
    return {'category':category,'structure':structure,
            'material':next(iter(candidates)) if len(candidates)==1 else 'unknown',
            'material_scope':'bulk' if bulk else 'appearance',
            'origin':'existing_render_material_slots','material_slot_evidence':evidence,
            'classification_confidence':'declared_structural_material' if bulk else 'appearance_only_or_ambiguous'}


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n')


def density_prior(profile: dict[str, Any]) -> dict:
    material = str(profile.get('material', '')).strip().lower()
    material = FAMILY_ALIASES.get(material, material)
    scope = profile.get('material_scope', 'appearance')
    category = str(profile.get('category', 'general_object')).lower()
    if scope == 'bulk' and material in DENSITIES:
        value, lower, upper = DENSITIES[material]
        return {'material': material, 'density_kg_m3': value,
                'density_range_kg_m3': [lower,upper], 'kind':'material_density_prior',
                'origin':profile.get('origin','declared_design_prior'), 'measured':False}
    # Appearance-only labels, including metallic shaders, do not identify bulk.
    value, lower, upper = ENVELOPE_PRIORS.get(category, ENVELOPE_PRIORS['general_object'])
    return {'material': material or 'unknown', 'density_kg_m3':value,
            'density_range_kg_m3':[lower,upper], 'kind':'category_envelope_density_prior',
            'category':category, 'origin':'uncalibrated_category_design_default', 'measured':False,
            'reason':'bulk_material_not_identified' if scope == 'bulk' else 'appearance_is_not_bulk_material'}


def point_mass_properties(points: np.ndarray, weights: np.ndarray, *, cell_size_m: float = 0.) -> dict:
    """Aggregate disjoint equal-sized material cells into one rigid body."""
    points = np.asarray(points,dtype=np.float64)
    weights = np.asarray(weights,dtype=np.float64)
    if (points.ndim != 2 or points.shape[1] != 3 or weights.shape != (len(points),)
            or not len(points) or not np.isfinite(points).all() or not np.isfinite(weights).all()
            or np.any(weights <= 0) or not np.isfinite(cell_size_m) or cell_size_m < 0):
        raise ValueError('Finite positions and positive mass weights are required')
    mass = float(weights.sum())
    center = (points*weights[:,None]).sum(axis=0)/mass
    local = points-center
    covariance = (local*weights[:,None]).T@local
    inertia = np.eye(3)*np.trace(covariance)-covariance
    inertia += np.eye(3)*(mass*cell_size_m**2/6.)
    values, axes = np.linalg.eigh(inertia)
    if values.min() <= 0:
        raise ValueError('Mass distribution has degenerate inertia')
    if np.linalg.det(axes) < 0: axes[:,0] *= -1
    return {'mass_kg':mass, 'center_of_mass_m':center.tolist(),
            'inertia_tensor_kg_m2':inertia.tolist(), 'principal_inertia_kg_m2':values.tolist(),
            'inertial_quaternion_wxyz':Rotation.from_matrix(axes).as_quat()[[3,0,1,2]].tolist()}


def combine_mass_properties(components: list[dict]) -> dict:
    """Exact parallel-axis aggregation of already estimated material parts."""
    if not components: raise ValueError('No mass components')
    masses=np.array([c['mass_kg'] for c in components],dtype=float)
    centers=np.array([c['center_of_mass_m'] for c in components],dtype=float)
    if not np.isfinite(masses).all() or np.any(masses <= 0) or not np.isfinite(centers).all():
        raise ValueError('Invalid component masses or centers')
    total=float(masses.sum());center=(masses[:,None]*centers).sum(axis=0)/total
    inertia=np.zeros((3,3))
    for c,m,p in zip(components,masses,centers):
        tensor=np.asarray(c['inertia_tensor_kg_m2'],dtype=float)
        if tensor.shape!=(3,3) or not np.allclose(tensor,tensor.T) or np.linalg.eigvalsh(tensor).min()<=0:
            raise ValueError('Invalid component inertia')
        r=p-center;inertia += tensor+m*(np.eye(3)*np.dot(r,r)-np.outer(r,r))
    values,axes=np.linalg.eigh(inertia)
    if np.linalg.det(axes)<0:axes[:,0]*=-1
    return {'mass_kg':total,'center_of_mass_m':center.tolist(),'inertia_tensor_kg_m2':inertia.tolist(),
            'principal_inertia_kg_m2':values.tolist(),
            'inertial_quaternion_wxyz':Rotation.from_matrix(axes).as_quat()[[3,0,1,2]].tolist()}


def surface_mass_properties(mesh: trimesh.Trimesh, mass_kg: float) -> dict:
    """Exact uniform triangular-lamina prior, independent of tessellation.

    When some components are open, mixing filled-volume weights for closed
    parts with artificial surface-voxel thickness for open parts biases COM.
    A consistent surface-area prior avoids that mixture. It is not a measured
    internal mass distribution or a claim that the furniture is a thin shell.
    """
    if not np.isfinite(mass_kg) or mass_kg<=0:raise ValueError('Positive mass required')
    triangles=np.asarray(mesh.triangles,dtype=float)
    area=np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1)/2
    valid=area>0;triangles=triangles[valid];area=area[valid]
    if not len(area) or not np.isfinite(triangles).all():raise ValueError('Finite nonzero surface required')
    weights=area*(mass_kg/area.sum());sums=triangles.sum(axis=1)
    center=(sums*(weights/3)[:,None]).sum(axis=0)/mass_kg
    second=(sums*weights[:,None]).T@sums
    for i in range(3):second+=(triangles[:,i]*weights[:,None]).T@triangles[:,i]
    covariance=second/12-mass_kg*np.outer(center,center)
    inertia=np.eye(3)*np.trace(covariance)-covariance
    values,axes=np.linalg.eigh(inertia)
    if values.min()<=0:raise ValueError('Degenerate surface inertia')
    if np.linalg.det(axes)<0:axes[:,0]*=-1
    return {'mass_kg':float(mass_kg),'center_of_mass_m':center.tolist(),'inertia_tensor_kg_m2':inertia.tolist(),
            'principal_inertia_kg_m2':values.tolist(),
            'inertial_quaternion_wxyz':Rotation.from_matrix(axes).as_quat()[[3,0,1,2]].tolist()}


def estimate_mass_properties(mesh: trimesh.Trimesh, profile: dict, output: Path,
                             *, pitch_m: float=.01, max_grid_cells: int=8_000_000) -> dict:
    """Cache two undilated grids and their mass/COM/inertia sensitivity.

    ``mesh`` must already be in the final metric asset frame, with instance
    scale baked once. Its hash, profile, resolution, and estimator version are
    part of the cache identity. A cache is accepted only with unchanged files.
    """
    if not np.isfinite(pitch_m) or pitch_m < 1e-5 or max_grid_cells < 1000:
        raise ValueError('Invalid voxel budget')
    if not isinstance(profile,dict): raise ValueError('Physical profile must be an object')
    if not isinstance(mesh,trimesh.Trimesh) or not len(mesh.faces): raise ValueError('Mesh required')
    if not np.isfinite(mesh.vertices).all(): raise ValueError('Nonfinite mesh')
    extents=np.asarray(mesh.extents,dtype=float)
    if np.any(extents<=0): raise ValueError('Nonvolumetric object envelope')
    identity={'schema':SCHEMA,'mesh_sha256':mesh_content_hash(mesh),'profile':profile,
              'requested_pitch_m':pitch_m,'max_grid_cells':max_grid_cells,
              'estimator_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'dependency_code_sha256':{name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                  for name in ('multilevel_proxy.py','collision_mesh_cleanup.py','collision_proxy.py')}}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    output=Path(output)/key;output.mkdir(parents=True,exist_ok=True)
    result_path=output/'mass_properties.json'
    if result_path.exists():
        report=json.loads(result_path.read_text())
        if report.get('identity')!=identity: raise ValueError('Mass cache identity mismatch')
        for record in report['voxel_files']:
            if hashlib.sha256(Path(record['path']).read_bytes()).hexdigest()!=record['sha256']:
                raise ValueError('Mass voxel cache changed')
        return {**report,'artifact':str(result_path),'cache_hit':True}
    clean,cleanup=cleanup_collision_mesh(mesh,CollisionMeshCleanupConfig())
    if not cleanup['accepted']: clean=mesh.copy()
    solid_reconstruction = None
    if profile.get('structure') == 'bound_paper_block' and profile.get('material_scope') == 'bulk':
        # A declared CLOSED book is a nearly convex filled page block. Its cover
        # lips are not evidence of large internal air spaces. This explicit
        # structural prior never applies to shelves, chairs, tubes or cabinets.
        clean=clean.convex_hull
        solid_reconstruction='convex_closed_book_envelope_from_declared_bound_page_block'
    finest=pitch_m
    while float(np.prod(np.ceil(extents/finest)+9))>max_grid_cells:
        finest*=1.25
    prior=density_prior(profile)
    envelope=float(np.prod(extents))
    measured_mass=profile.get('mass_kg')
    if measured_mass is not None:
        if (isinstance(measured_mass,bool) or not np.isfinite(measured_mass) or measured_mass<=0
                or not profile.get('mass_source')):
            raise ValueError('Explicit mass requires a positive value and a source')
        interval=np.asarray(profile.get('mass_range_kg',[measured_mass,measured_mass]),dtype=float)
        if interval.shape!=(2,) or not np.isfinite(interval).all() or not (0<interval[0]<=measured_mass<=interval[1]):
            raise ValueError('Explicit mass range must be positive, ordered and contain the mass')
    rows=[];files=[]
    for level,pitch in [('coarse',finest*2),('fine',finest)]:
        proxy=build_component_aware_sdf(clean,pitch=pitch,padding_voxels=3,
              surface_dilation_voxels=0,fill_watertight_components=True,maximum_split_components=512,
              metadata={'purpose':'mass_estimation','physical_mass_schema':SCHEMA})
        occupied=np.argwhere(proxy.occupancy)
        points=proxy.origin+occupied*pitch
        if not len(points): raise ValueError('Empty undilated voxel proxy')
        volume=float(len(points)*pitch**3)
        components=proxy.metadata['components']
        closed=all(c['interior_filled'] for c in components)
        geometry_solid=closed and profile.get('structure') in SOLID_STRUCTURES
        solid=(geometry_solid
               and profile.get('material_scope')=='bulk' and prior['kind']=='material_density_prior')
        if measured_mass is not None:
            total=float(measured_mass);mass_range=profile.get('mass_range_kg',[total,total])
            origin='explicit_total_mass';reason=None
            applied_prior=None
        elif solid:
            total=volume*prior['density_kg_m3']
            mass_range=[volume*x for x in prior['density_range_kg_m3']]
            origin='undilated_material_voxel_volume';reason=None
            applied_prior=prior
        else:
            fallback=density_prior({'category':profile.get('category','general_object')})
            total=envelope*fallback['density_kg_m3']
            mass_range=[envelope*x for x in fallback['density_range_kg_m3']]
            origin='category_envelope_fallback'
            reason=('open_surface_voxels_do_not_define_material_thickness' if not closed
                    else 'solid_interior_or_bulk_material_not_established')
            applied_prior=fallback
        if geometry_solid:
            properties=point_mass_properties(points,np.full(len(points),total/len(points)),cell_size_m=pitch)
            distribution='uniform_undilated_solid_voxel_mass'
        else:
            properties=surface_mass_properties(clean,total)
            distribution='uniform_visible_surface_area_prior'
        grid_path=output/(level+'.npz');proxy.save(grid_path)
        files.append({'path':str(grid_path.resolve()),'sha256':hashlib.sha256(grid_path.read_bytes()).hexdigest()})
        rows.append({**properties,'level':level,'pitch_m':pitch,'occupied_volume_m3':volume,
                     'occupied_cell_count':len(points),'mass_origin':origin,'mass_range_kg':mass_range,
                     'volume_interpretation':'assumed_material_solid' if solid else 'geometry_distribution_proxy',
                     'fallback_reason':reason,'closed_component_fill_only':closed,
                     'applied_density_prior':applied_prior,
                     'mass_distribution_model':distribution,
                     'geometry_report':proxy.metadata})
    fine,coarse=rows[1],rows[0]
    inertia_f=np.asarray(fine['inertia_tensor_kg_m2']);inertia_c=np.asarray(coarse['inertia_tensor_kg_m2'])
    report={'schema':SCHEMA,'identity':identity,'cache_key':key,'profile':profile,'density_prior':prior,
            **{k:v for k,v in fine.items() if k not in ('geometry_report','level')},
            'true_mass_kg':None,'true_inertia_kg_m2':None,'material_measured':False,
            'mass_source':profile.get('mass_source'),'envelope_volume_m3':envelope,
            'cleanup':cleanup,'solid_reconstruction':solid_reconstruction,
            'surface_dilation_voxels':0,'levels':rows,'voxel_files':files,
            'resolution_sensitivity':{
                'mass_relative_difference':abs(fine['mass_kg']-coarse['mass_kg'])/fine['mass_kg'],
                'volume_relative_difference':abs(fine['occupied_volume_m3']-coarse['occupied_volume_m3'])/fine['occupied_volume_m3'],
                'center_difference_m':float(np.linalg.norm(np.asarray(fine['center_of_mass_m'])-coarse['center_of_mass_m'])),
                'inertia_relative_frobenius_difference':float(np.linalg.norm(inertia_f-inertia_c)/np.linalg.norm(inertia_f))},
            'limitations':['Density ranges are design priors, not statistical confidence intervals.',
                          'Closed visual geometry does not independently prove hidden solid structure.',
                          'Unknown interiors use an explicit fallback; voxel resolution is not material thickness.',
                          'Volume or surface weighting is an explicit prior for unobserved internal mass distribution.',
                          'Surface-prior COM/inertia do not depend on voxel pitch; zero pitch sensitivity is not material calibration.']}
    _write(result_path,report)
    return {**report,'artifact':str(result_path),'cache_hit':False}
