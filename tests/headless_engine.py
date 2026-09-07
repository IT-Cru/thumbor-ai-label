"""A stand-in for Thumbor's gifsicle engine: an engine that holds no PIL image.

``thumbor.engines.gif.Engine.load`` sets ``self.image = ""`` and delegates every
operation to the ``gifsicle`` binary. Nothing can be composited onto that, and the
plugin has to say so honestly on both the image path and ``/meta/``.

Shaped like the real thing rather than mocked, so the tests exercise the same
attribute the gif engine actually leaves behind - and without needing the binary,
which no test of this plugin's own logic should have to depend on.
"""

from __future__ import annotations

from thumbor.engines.pil import Engine as PilEngine


class Engine(PilEngine):
    #: None until ``load`` has run, so ``BaseEngine.load`` can still read the real
    #: image's size while it sets ``source_width``/``source_height``.
    image_size = None

    @property
    def size(self):
        if self.image_size is None:
            return self.image.size
        return self.image_size

    def load(self, buffer, extension):
        super().load(buffer, extension)
        self.buffer = buffer
        self.image_size = self.image.size
        self.image = ""
        self.operations = []

    def resize(self, width, height):
        self.operations.append(f"--resize {width}x{height}")
        self.image_size = (width, height)

    def crop(self, left, top, right, bottom):
        self.operations.append(f"--crop {left},{top}-{right},{bottom}")
        self.image_size = (right - left, bottom - top)

    def flip_vertically(self):
        self.operations.append("--flip-vertical")

    def flip_horizontally(self):
        self.operations.append("--flip-horizontal")

    def has_transparency(self):
        return False

    def read(self, extension=None, quality=None):
        return self.buffer
