"""Renders the wheel through GdkPixbuf like the app does, saves PNGs and measures one frame."""
import os
import time
import unittest

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

import convert_wheel as w  # noqa: E402
import converters as c  # noqa: E402

from .samples import CHECK_DIR  # noqa: E402

# 16 ms is the budget for ~60 fps; shared CI machines get a looser limit
FRAME_LIMIT_MS = float(os.environ.get("CONVERT_WHEEL_FRAME_LIMIT_MS", "16"))


def pixbuf(f):
    ld = GdkPixbuf.PixbufLoader.new_with_type("svg")
    ld.write(f.svg().encode())
    ld.close()
    return ld.get_pixbuf()


class Render(unittest.TestCase):
    def setUp(self):
        CHECK_DIR.mkdir(parents=True, exist_ok=True)
        f = w.Wheel.__new__(w.Wheel)
        f.targets = c.targets_for("/x/photo.webp")
        f.k, f.files, f.msg, f.anim = 1.0, [__file__], "", None
        f.S = 2 * (w.Wheel.R2 + w.Wheel.PAD)
        self.f = f

    def test_static_states(self):
        for name, sel in (("wheel", (2, "conv")), ("wheel-cfg", (5, "cfg"))):
            self.f.sel = sel
            pb = pixbuf(self.f)
            self.assertEqual((pb.get_width(), pb.get_height()), (self.f.S, self.f.S))
            pb.savev(str(CHECK_DIR / f"{name}.png"), "png", [], [])

    def test_animation_sheet(self):
        from PIL import Image
        frames = []
        for kind, ts, extra in (("open", (0.02, 0.07, 0.13, 0.2, 0.42), {"delay": 0.14 / len(self.f.targets)}),
                                ("pick", (0.06, 0.13, 0.2, 0.27), {"i": 2})):
            for t in ts:
                self.f.sel = (2, "conv") if kind == "pick" else (None, None)
                self.f.anim = dict(kind=kind, t0=time.monotonic() - t, **extra)
                path = CHECK_DIR / "frame.png"
                pixbuf(self.f).savev(str(path), "png", [], [])
                frames.append(Image.open(path).resize((262, 262)))
        sheet = Image.new("RGBA", (262 * len(frames), 262), (40, 44, 52, 255))
        for j, frame in enumerate(frames):
            sheet.alpha_composite(frame.convert("RGBA"), (262 * j, 0))
        sheet.save(CHECK_DIR / "animation.png")

    def test_frame_time(self):
        self.f.sel = (2, "conv")
        start = time.perf_counter()
        for _ in range(20):
            pixbuf(self.f)
        ms = (time.perf_counter() - start) / 20 * 1000
        print(f"  wheel frame: {ms:.1f} ms (limit {FRAME_LIMIT_MS:g})")
        self.assertLess(ms, FRAME_LIMIT_MS)


if __name__ == "__main__":
    unittest.main()
