"""Streaming inspection of actual decoded RGB frames and source row timestamps."""
import numpy as np


def iter_source_camera(path, timestamps, *, expected_shape, tolerance_seconds=1e-5):
    import av
    times = np.asarray(timestamps, dtype=np.float64)
    if times.ndim != 1 or not len(times) or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError('invalid_camera_timestamps')
    shape = tuple(expected_shape)
    if len(shape) != 3 or shape[-1] != 3 or min(shape) < 1:
        raise ValueError('invalid_rgb_shape')
    if not np.isfinite(tolerance_seconds) or not 0 <= tolerance_seconds <= 1e-3:
        raise ValueError('invalid_timestamp_tolerance')
    count = 0
    with av.open(str(path)) as container:
        if len(container.streams.video) != 1:
            raise ValueError('single_video_stream_required')
        stream = container.streams.video[0]
        stream.codec_context.thread_count = 1
        for frame in container.decode(stream):
            if count >= len(times):
                raise ValueError('extra_video_frames')
            if frame.pts is None or frame.time_base is None:
                raise ValueError('missing_video_timestamp')
            pts = float(frame.pts * frame.time_base)
            if abs(pts-times[count]) > tolerance_seconds:
                raise ValueError('video_row_timestamp_mismatch')
            rgb = frame.to_ndarray(format='rgb24')
            if rgb.dtype != np.uint8 or rgb.shape != shape:
                raise ValueError('video_frame_shape_or_dtype')
            yield count, pts, rgb
            count += 1
    if count != len(times):
        raise ValueError('missing_video_frames')
