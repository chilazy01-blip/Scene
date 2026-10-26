"""Reuse the validated acquisition loop at the actual task's close transition."""
def install(pipeline,active):
 pipeline.HOLD_CAP=None  # The physical contact governor owns the retained0.03rad bound.
 def squeeze(runner,target,seconds,offset=None,**kwargs):
  active['enabled']=True;runner.grip_cap=None
  initial_t=runner.grip_alpha;initial_f=runner.grip_alpha_f
  dt=runner.model.opt.timestep;maximum=int(round(6./dt));ramp=int(round(4./dt))
  rows=[];stable=0;frac=0.;captured=False
  for i in range(maximum):
   frac=min(1.,i/ramp)
   runner.grip_alpha=initial_t+(target-initial_t)*frac
   runner.grip_alpha_f=initial_f+(target-initial_f)*frac
   runner.step_once()
   g=active['governor'];opposed='thumb' in g.latched and bool(g.latched&{'index','middle'})
   stable=stable+1 if opposed and runner.finger_contacts()>=2 and runner.cyl_tilt_deg()<10. else 0
   if i%80==0:
    geom=pipeline.pinch_geometry(runner,offset)
    rows.append({'t':float(runner.data.time),'grip':float(runner.grip_alpha_f),'depth_m':geom['depth_m'],'contacts':runner.finger_contacts(),'tilt_deg':float(runner.cyl_tilt_deg())})
   if stable*dt>=.2:captured=True;break
  if not captured:raise pipeline.EpisodeAborted('measured_opposed_grasp_not_acquired')
  return rows,{'frac':frac,'why':'measured_opposed_contact_stable','measured_capture':True,'plant_unchanged':True}
 pipeline.squeeze=squeeze
