"""Development-only training view over audited existing episodes; no data copies."""
from bisect import bisect_right
from pathlib import Path
import json
import numpy as np
from .dataset import sha
from .multimodal import MultimodalSequence


class DevelopmentRGBD:
    """One cached episode; public wrist RGB-D and aligned native actions only.

    The catalog selects successful declared development episodes. Storage variants
    are identified by the original trajectory hash, never counted as new data.
    Episode/frame indices are bookkeeping, not model observations.
    """
    def __init__(self, catalog, purpose='conditional_multimodal_research'):
        if purpose != 'conditional_multimodal_research':
            raise ValueError('unqualified_purpose')
        c = json.loads(Path(catalog).read_text()) if isinstance(catalog, (str, Path)) else catalog
        if c['schema'] != 'conditional-unified-training/v1' or c['scope'] != 'simulation_only':
            raise ValueError('unsupported_catalog')
        if c['hardware_qualified'] or c['production_qualified']:
            raise ValueError('invalid_scope_upgrade')
        self.bindings = []; self.ends = []; identities = set(); source_hashes = set()
        self.camera = c['camera']; self.total = 0
        for row in c['rgbd_episodes']:
            if sha(row['binding']) != row['binding_sha256']:
                raise ValueError('binding_hash_mismatch')
            b = json.loads(Path(row['binding']).read_text()); m = b['metadata']
            if m['scope'] != 'simulation_only' or not m['complete_episode']:
                raise ValueError('not_complete_conditional_data')
            if m['source_kind'] not in ('complete_task_development', 'complete_task_household'):
                raise ValueError('evaluation_not_training')
            pb = row['proprio_binding']; pm = pb['metadata']
            if not pm['task_success'] or pm['kind'] != m['source_kind']:
                raise ValueError('failed_or_mismatched_source')
            if pm['trial'] != m['source_trial'] or pb['sha256'] != m['source_h5_sha256']:
                raise ValueError('source_lineage_mismatch')
            if pm['trial'] in identities or pb['sha256'] in source_hashes:
                raise ValueError('duplicate_source_episode')
            if row['frames'] != m['frames'] or row['frames'] <= 0:
                raise ValueError('frame_count_mismatch')
            identities.add(pm['trial']); source_hashes.add(pb['sha256'])
            self.bindings.append(b); self.total += row['frames']; self.ends.append(self.total)
        if not self.bindings:
            raise ValueError('empty_training_catalog')
        self._episode = None; self._sequence = None

    def __len__(self):
        return self.total

    def __getitem__(self, index):
        if not isinstance(index, (int, np.integer)) or not 0 <= index < self.total:
            raise IndexError(index)
        episode = bisect_right(self.ends, index)
        frame = index - (self.ends[episode - 1] if episode else 0)
        if self._episode != episode:
            self._sequence = MultimodalSequence(self.bindings[episode], purpose='conditional_multimodal_training')
            if self.camera not in self._sequence.cameras:
                raise ValueError('required_camera_missing')
            self._episode = episode
        s = self._sequence
        return dict(episode_index=np.int64(episode), frame_index=np.int64(frame),
                    trajectory={k: v[frame].copy() for k, v in s.rows.items()},
                    cameras={self.camera: {k: v[frame].copy() for k, v in s.cameras[self.camera].items()}})
