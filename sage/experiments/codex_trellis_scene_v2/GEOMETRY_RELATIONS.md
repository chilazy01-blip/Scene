# Relation-aware geometry contract

Status: experimental, opt-in.  This contract does not change the V2 default
pipeline until the regression matrix at the end of this document passes.

## Why this exists

The first SDF pilot encoded one successful example: an office chair entering a
box called `under_desk`.  That is useful evidence, but it makes the category
name carry geometry semantics.  A new pair such as a book and an open shelf
then needs new solver code even though the geometric question is the same.

This contract moves the reusable knowledge onto assets:

- `solid`: geometry that other solids must not penetrate;
- `support_surface`: a bounded plane that can carry another object;
- `containment_volume`: a volume in which selected source geometry must fit;
- `free_space`: a volume that an object or anchor may enter partially;
- `entry_portal`: the opening and direction through which entry is feasible;
- `contact_surface`: a bounded plane intended for non-penetrating contact;
- `semantic_anchor`: a point or region on the source used by a relation.

Categories may filter asset selection and authoring suggestions.  They must not
select an evaluator implementation.

## Relation compilation

| Scene relation | Required target slot | Geometry predicate |
| --- | --- | --- |
| `supported_by` | `support_surfaces` | bottom/contact samples lie on the bounded plane, with sufficient footprint support |
| `contained_in` | `containment_volumes` | all selected source samples lie inside the volume with clearance |
| `tucked_under` | `free_space_volumes` | the selected source region enters the free space by a minimum fraction/depth |
| `partially_inserted` | `free_space_volumes` | same primitive as `tucked_under`; the asset metadata defines portal and threshold |
| `against` | `contact_surfaces` | the selected contact samples overlap and approach the bounded plane without deep penetration |
| `contact` | `contact_surfaces` | same geometric primitive as `against`, with relation-specific tolerances |

Every compiled relation also adds a solid non-penetration predicate.  Collision
is evaluated in both directions (source samples against target proxy and target
samples against source proxy).  A missing direction is recorded as incomplete
verification and is rejected by the conservative policy.

## Verification ladder

1. World AABBs cheaply discard distant pairs.
2. A component-aware coarse proxy searches candidate poses.
3. A finer proxy checks both directions and applies its declared error bound.
4. Critical or ambiguous pairs go through triangle-level verification.
5. The accepted pose receives a certificate containing input, transform,
   capability and proxy hashes.  A changed input makes the certificate stale.

The Python triangle verifier is an adaptive floating-point verifier, not an
exact-predicate replacement for OpenMeshCraft.  The interface deliberately
records that distinction so a small native exact backend can be added later.

## Borrowed ideas, not copied implementations

From RobustCage we use component-wise, watertight, multi-resolution outer
proxies, explicit approximation error, and the rule that a failed refinement
does not replace the last valid proxy.  Processing components independently is
important: wrapping a whole desk or shelf in one closed cage would seal its
usable opening.

From OpenMeshCraft we use broad-phase triangle candidate generation followed by
a more careful narrow-phase classification, duplicate/degenerate filtering,
and a final verifier separate from the fast search proxy.  The implementation
is clean-room Python and does not incorporate GPL source.

## Acceptance matrix

The experimental bridge may be proposed for V2 opt-in integration only after:

- cup on desk: accepted support and rejected hovering/deep penetration;
- chair partly under desk: accepted useful overlap and rejected collision;
- book or box in an open shelf: accepted containment without sealing the front;
- contact against a wall or panel: accepted contact and rejected deep overlap;
- an unseen synthetic asset assembled from the same primitives passes without
  adding category-specific solver branches;
- stale certificates and incomplete conservative verification are rejected;
- all pre-existing V2 and repository tests remain green.

Soft bodies, articulation and time-dependent rigid-body dynamics are outside
this phase.
