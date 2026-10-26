# Command braking and action precision diagnosis

This version is a development diagnostic candidate. It does not replace the
frozen `embodied_abc_v1` controller, model, or previous evaluation results.

`BrakingCommandLimiter` constrains commanded joint positions at a 50 ms period,
with the original 0.5 rad/s rate and 1 rad/s² acceleration bounds. For a candidate
next speed `u`, define `d = acceleration * dt`. The commanded travel including
that candidate step and subsequent maximum braking is

```
S(u) = dt * sum(max(u - k*d, 0), k=0..ceil(max_rate/d)-1)
```

Equivalently, `S(u) <= distance` gives each affine upper bound
`u <= distance/(dt*n) + d*(n-1)/2`. Their minimum is the exact discrete speed cap.
The controller intersects the caps for both hard joint boundaries with the
one-step acceleration interval. It also uses this stopping rule toward the
requested target. Targets may change abruptly, so overshoot of a moving target
cannot always be avoided; the hard-bound stopping constraint is independent of
the requested target. Position is never abruptly clamped after integration.

The invariant starts at a valid joint position with zero command velocity.
It concerns **commands**, not physical joint dynamics, contacts, or hardware
safety. Filtering feasible expert setpoints also introduces tracking lag, which
is measured explicitly in the run evidence.

`precision.infer_action` exposes three fixed numerical modes using the official
LeRobot ACT and processor: original bfloat16 processing, bfloat16 inference with
float32 action unnormalization, and full float32. In the second mode, the
normalized action is converted **before** unnormalization, outside autocast.
Converting the already unnormalized output to float32 cannot restore lost bits.

The registered diagnosis uses one previously trained initialization, frozen
weights, and four 25-second runs. It is not a full-task or generalization test.
See the independent run directory `embodied_control_diag_20260920_v1` for the
protocol, source hashes, numerical checks, all outcomes, and independent replay.
