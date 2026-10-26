"""Existing PyAV H.264 encoder; one thread, browser-compatible yuv420p."""

from fractions import Fraction
import av


class H264Writer:
    def __init__(self, path, width, height, fps):
        self.container = av.open(str(path), "w", options={"movflags": "+faststart"})
        self.stream = self.container.add_stream("libx264", rate=fps)
        self.stream.width = width
        self.stream.height = height
        self.stream.pix_fmt = "yuv420p"
        self.stream.codec_context.thread_count = 1
        self.stream.options = {"crf": "21", "preset": "fast"}
        self.index = 0
        self.fps = fps

    def isOpened(self):
        return True

    def write(self, bgr):
        frame = av.VideoFrame.from_ndarray(bgr, format="bgr24")
        frame.pts = self.index
        frame.time_base = Fraction(1, self.fps)
        for packet in self.stream.encode(frame):
            self.container.mux(packet)
        self.index += 1

    def release(self):
        for packet in self.stream.encode():
            self.container.mux(packet)
        self.container.close()
