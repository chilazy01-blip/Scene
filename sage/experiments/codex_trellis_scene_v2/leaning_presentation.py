"""A local comparison page and exportable plots from saved simulation data."""
from pathlib import Path
import html
import json
import os
import numpy as np

def write_presentation(output: Path):
    os.environ.setdefault('MPLCONFIGDIR',str(output/'matplotlib_config'))
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    report=json.loads((output/'comparison.json').read_text())
    data={};images={};mass={};rows=[]
    for label in ('normal','low'):
        path=Path(report['runs'][label][-1]['path']).parent
        result=json.loads((path/'result.json').read_text());data[label]=result
        manifest=json.loads((output/'renders'/label/'render_manifest.json').read_text())
        images[label]=[{'time_s':f['time_s'],'path':str(Path(f['image']['path']).relative_to(output))}
                       for f in manifest['frames'] if f['camera']=='books']
    binding=json.loads((output/'physics_binding/geometry_binding.json').read_text())
    for identifier,obj in binding['objects'].items():
        props=json.loads(Path(obj['mass_properties']['path']).read_text())
        mass[identifier]={'mass_kg':props['mass_kg'],'mass_range_kg':props['mass_range_kg'],
            'mass_origin':props['mass_origin'],'volume_m3':props['occupied_volume_m3'],
            'volume_interpretation':props['volume_interpretation'],'center_of_mass_body_m':props['center_of_mass_m'],
            'resolution_sensitivity':props['resolution_sensitivity']}
    (output/'mass_summary.json').write_text(json.dumps(mass,indent=2))
    fig,axes=plt.subplots(2,2,figsize=(11,7),sharex=True)
    for col,label in enumerate(('normal','low')):
        path=Path(report['runs'][label][-1]['path']).parent
        with np.load(path/'dense_state.npz') as dense:
            ids=dense['object_ids'].tolist();poses=dense['matrix_world_z_up'];times=dense['time_s']
            for identifier in data[label]['metrics']:
                i=ids.index(identifier)
                up=poses[:,i,:3,:3]@np.asarray(binding['objects'][identifier].get('semantic_up_axis_body',[0,0,1]))
                angle=np.degrees(np.arctan2(up[:,0],up[:,2]))
                displacement=np.linalg.norm(poses[:,i,:3,3]-poses[0,i,:3,3],axis=1)
                axes[0,col].plot(times,angle,label=identifier.rsplit('_',1)[-1])
                axes[1,col].plot(times,displacement*1000)
        axes[0,col].set_title(f"{label} friction, mu={data[label]['mu']}")
        axes[0,col].set_ylabel('Lean in row plane (degrees)');axes[1,col].set_ylabel('Body displacement (mm)')
        axes[1,col].set_xlabel('Time (s)');axes[0,col].legend(title='Book',ncol=5,fontsize=8)
    for ax in axes.ravel():ax.grid(alpha=.25)
    fig.tight_layout();fig.savefig(output/'trajectory_comparison.png',dpi=160);fig.savefig(output/'trajectory_comparison.pdf');plt.close(fig)
    for identifier,normal in data['normal']['metrics'].items():
        low=data['low']['metrics'][identifier]
        rows.append('<tr><td>'+html.escape(identifier)+'</td>'+''.join(f'<td>{v:.4g}</td>' for v in [
            mass[identifier]['mass_kg'],normal['final_total_tilt_from_vertical_deg'],low['final_total_tilt_from_vertical_deg'],
            normal['tail_linear_rms_m_s'],normal['tail_fraction_with_shelf_support'],
            normal['tail_mean_force_imbalance_over_weight']])+'</tr>')
    page='''<!doctype html><meta charset="utf-8"><title>独立斜靠书籍：实际仿真对照</title>
<style>body{font:16px system-ui;max-width:1200px;margin:30px auto;padding:0 18px;color:#253145;background:#f6f7fa}h1{font-size:25px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}img{width:100%;background:white}section{background:white;padding:18px;margin:18px 0;border-radius:10px}input{width:80%}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px;border-bottom:1px solid #ddd}a{color:#2362a1}</style>
<h1>五本独立书籍的真实动力学对照</h1>
<p>书籍分别生成、各有 6 个自由度；10° 是初始姿态。书架为静止环境。图片来自保存的仿真轨迹，未手工固定书本。</p>
<section><label>实际仿真时间 <b id="time"></b><br><input id="slider" type="range" min="0" value="0" step="1"></label>
<div class="grid"><div><p>正常摩擦 μ=0.5</p><img id="normal"></div><div><p>低摩擦 μ=0.005</p><img id="low"></div></div></section>
<section><img src="trajectory_comparison.png"><a href="trajectory_comparison.pdf">导出轨迹图 PDF</a></section>
<section><table><tr><th>书本</th><th>估计质量 kg</th><th>正常最终倾角 °</th><th>低摩擦最终倾角 °</th><th>正常末段速度 RMS m/s</th><th>层板支撑比例</th><th>平均合力/重力</th></tr>ROWS</table></section>
<p>上述质量是材料/结构先验估计，未实物校准。参考容差与步长敏感性单独记录，不以一张静态图认定物理正确。</p>
<p><a href="comparison.json">完整对照结果</a> · <a href="mass_summary.json">质量、重心及体积分辨率</a> · <a href="source_audit.json">逐本生成来源</a> · <a href="asset_inspection/inspection_manifest.json">每本四视图清单</a></p>
<script>const frames=FRAMES;const slider=document.getElementById('slider');slider.max=frames.normal.length-1;function show(){const i=+slider.value;document.getElementById('time').textContent=frames.normal[i].time_s.toFixed(2)+' s';for(const name of ['normal','low'])document.getElementById(name).src=frames[name][i].path;}slider.oninput=show;show();</script>'''
    (output/'index.html').write_text(page.replace('ROWS',''.join(rows)).replace('FRAMES',json.dumps(images)))
