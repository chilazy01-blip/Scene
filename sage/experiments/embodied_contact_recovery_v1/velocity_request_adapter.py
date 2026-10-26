"""Keep navigation requests separate from transient issued policy commands."""
ATTRIBUTES = ('lin_vel_x', 'lin_vel_y', 'ang_vel_z')


def call_with_issued_velocity(controller, issued, callback):
    requested = [getattr(controller, name) for name in ATTRIBUTES]
    try:
        for name, value in zip(ATTRIBUTES, issued):
            setattr(controller, name, float(value))
        return callback(controller)
    finally:
        for name, value in zip(ATTRIBUTES, requested):
            setattr(controller, name, value)
