"""Amortize durable quota I/O without executing unreserved actions."""
class Batch:
    def __init__(self, journal, kind, planned_units, maximum_units, batch_units=100):
        if not (0 < planned_units <= maximum_units and batch_units > 0):
            raise ValueError('invalid_batch_scope')
        self.journal, self.kind = journal, kind
        self.planned_units, self.maximum_units = planned_units, maximum_units
        self.batch_units = batch_units
        self.completed = self.charged = self.current_used = self.current_units = 0
        self.token = None

    def call(self, action, units=1):
        if type(units) is not int or units <= 0 or self.completed + units > self.planned_units:
            raise RuntimeError('bounded_batch_action_exceeded')
        if self.token is None:
            reserve = min(self.batch_units, self.planned_units-self.completed)
            if units > reserve or self.charged + reserve > self.maximum_units:
                raise RuntimeError('bounded_batch_reservation_exceeded')
            # A failed durable reservation never permits the action to start.
            token = self.journal.reserve(self.kind, reserve)
            self.token, self.current_units, self.current_used = token, reserve, 0
            self.charged += reserve
        if self.current_used + units > self.current_units:
            raise RuntimeError('action_crosses_reservation_boundary')
        value = action()
        self.current_used += units
        self.completed += units
        if self.current_used == self.current_units:
            self.journal.complete(self.token)
            self.token = None
        return value
