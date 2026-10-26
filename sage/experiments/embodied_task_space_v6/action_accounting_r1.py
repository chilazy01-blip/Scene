"""Read-only reconciliation of prospectively reserved task-range actions.

Completed actions are a lower bound, and all durable reservations are charged.
A saved prefix prevents a valid but rolled-back journal from clearing charges.
This module creates neither a journal nor an experimental authorization.
"""
from pathlib import Path
import fcntl
import hashlib
import json

ACTION_LIMITS = dict(static_policy_forwards=82000, dynamic_policy_forwards=23450,
                     physics_steps=234500, component_attempts=8,
                     full_task_attempts=1, render_passes=8940)
COUNTERS = ('dynamic_trials', 'physics_steps', 'static_policy_forwards',
            'dynamic_policy_forwards', 'render_frames',
            'qualified_full_body_task_episodes')


class AccountingRejected(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise AccountingRejected(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def snapshot(path, scope, limits=ACTION_LIMITS, previous=None):
    """Take an immutable consistent view; reject active writers or lost history."""
    path = Path(path)
    require(isinstance(scope, str) and bool(scope), 'scope_required')
    require(limits and all(isinstance(k, str) and type(v) is int and v >= 0
                           for k, v in limits.items()), 'invalid_limits')
    charged = dict.fromkeys(limits, 0)
    completed = dict(charged)
    pending, claims, seen = {}, {}, set()
    seq, head, prefix_seen = 0, '0' * 64, previous is None
    if previous is not None:
        require(previous.get('path') == str(path.resolve()) and previous.get('scope') == scope
                and previous.get('limits') == limits, 'accounting_scope_changed')
        require(type(previous.get('sequence')) is int and previous['sequence'] >= 0,
                'invalid_previous_sequence')
        if previous['sequence'] == 0:
            require(previous.get('head_sha256') == head, 'invalid_empty_prefix')
            prefix_seen = True
    exists = path.exists()
    if not exists:
        require(previous is None or previous['sequence'] == 0, 'journal_disappeared')
    else:
        lock_path = path.with_suffix(path.suffix + '.lock')
        require(lock_path.exists(), 'existing_journal_lock_missing')
        with lock_path.open('rb') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AccountingRejected('journal_writer_active') from exc
            with path.open('rb') as source:
                for raw in source:
                    require(raw.endswith(b'\n'), 'truncated_journal')
                    try:
                        row = json.loads(raw)
                        body = {k: v for k, v in row.items() if k != 'sha256'}
                        digest = hashlib.sha256(canonical(body)).hexdigest()
                    except (ValueError, TypeError, AttributeError) as exc:
                        raise AccountingRejected('invalid_journal_record') from exc
                    require(type(row.get('sequence')) is int and row['sequence'] == seq
                            and row.get('previous') == head and row.get('sha256') == digest,
                            'journal_chain_changed')
                    event = row.get('event')
                    if seq == 0:
                        require(event == 'open' and row.get('scope') == scope
                                and row.get('limits') == limits, 'journal_authority_changed')
                    elif event == 'reserve':
                        kind, units, token = row.get('kind'), row.get('units'), row.get('token')
                        require(kind in charged and kind not in ('component_attempts', 'full_task_attempts')
                                and type(units) is int and units > 0
                                and token == scope + ':' + str(seq) and token not in seen,
                                'invalid_reservation')
                        require(charged[kind] + units <= limits[kind], 'quota_exceeded:' + kind)
                        charged[kind] += units
                        pending[token] = (kind, units)
                        seen.add(token)
                    elif event == 'complete':
                        token = row.get('token')
                        require(token in pending, 'unknown_or_repeated_completion')
                        kind, units = pending.pop(token)
                        completed[kind] += units
                    elif event == 'claim':
                        name, kind, binding = row.get('name'), row.get('kind'), row.get('binding_sha256')
                        require(isinstance(name, str) and bool(name) and name not in claims
                                and kind in ('component_attempts', 'full_task_attempts')
                                and isinstance(binding, str) and len(binding) == 64
                                and all(c in '0123456789abcdef' for c in binding), 'invalid_attempt_claim')
                        require(charged[kind] + 1 <= limits[kind], 'attempt_quota_exceeded')
                        charged[kind] += 1
                        claims[name] = dict(kind=kind, binding_sha256=binding)
                    else:
                        raise AccountingRejected('unexpected_event')
                    seq += 1
                    head = digest
                    if previous is not None and seq == previous['sequence']:
                        require(head == previous['head_sha256'], 'saved_prefix_changed')
                        prefix_seen = True
                require(seq > 0, 'empty_existing_journal')
    require(prefix_seen, 'journal_rolled_back')
    unknown = {k: charged[k] - completed[k] for k in limits}
    # Attempt claims consume permission before starting. They are not evidence
    # of a physical step or a successful episode.
    return dict(path=str(path.resolve()), scope=scope, limits=dict(limits), exists=exists,
                sequence=seq, head_sha256=head, charged=charged, completed=completed,
                unconfirmed=unknown, pending_reservations=len(pending), claims=claims,
                success_inferred=False)


def compose(historical, snap):
    """Rebuild totals from an immutable baseline, never add to previous totals."""
    require(all(type(historical.get(k)) is int and historical[k] >= 0 for k in COUNTERS),
            'historical_counters_required')
    used, done = snap['charged'], snap['completed']
    delta = dict(physics_steps=used['physics_steps'],
                 static_policy_forwards=used['static_policy_forwards'],
                 dynamic_policy_forwards=used['dynamic_policy_forwards'],
                 render_frames=used['render_passes'],
                 dynamic_trials=used['component_attempts'] + used['full_task_attempts'],
                 qualified_full_body_task_episodes=0)
    total = {k: historical[k] + delta[k] for k in COUNTERS}
    intervals = {k: [historical[k] + done[k], total[k]]
                 for k in ('physics_steps', 'static_policy_forwards', 'dynamic_policy_forwards')}
    intervals['render_frames'] = [historical['render_frames'] + done['render_passes'], total['render_frames']]
    intervals['dynamic_trials'] = [historical['dynamic_trials'], total['dynamic_trials']]
    return dict(charged_totals=total, charged_delta=delta, completed_to_reserved_intervals=intervals,
                render_frames_semantics='historical render counter plus charged renderer passes; not dataset timestamps',
                qualified_episode_delta=0,
                qualification_requires_separate_physics_and_data_audits=True)
