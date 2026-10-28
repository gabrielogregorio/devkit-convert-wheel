import math
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import convert_wheel as w
import converters as c
import i18n


def wheel(n=6):
    f = w.Wheel.__new__(w.Wheel)   # no window: geometry and drawing only
    f.k, f.cx, f.cy = 1.0, 500, 500
    f.targets = c.targets_for("/x/photo.webp")[:n]
    f.files, f.msg, f.anim, f.sel = [], "", None, (None, None)
    f.S = 2 * (w.Wheel.R2 + w.Wheel.PAD)
    return f


class Zone(unittest.TestCase):
    def at(self, f, radius, degrees):
        a = math.radians(degrees)   # 0 = up, clockwise
        return f.zone(500 + radius * math.sin(a), 500 - radius * math.cos(a))

    def test_center_and_far_cancel(self):
        f = wheel()
        self.assertEqual(f.zone(500, 500), (None, None))
        self.assertEqual(self.at(f, w.Wheel.R2 + w.Wheel.OUTSIDE + 1, 0), (None, None))

    def test_inner_ring_converts_outer_ring_adjusts(self):
        f = wheel()
        self.assertEqual(self.at(f, (w.Wheel.R0 + w.Wheel.R1) / 2, 0), (0, "conv"))
        self.assertEqual(self.at(f, (w.Wheel.R1 + w.Wheel.R2) / 2, 0), (0, "cfg"))
        self.assertEqual(self.at(f, w.Wheel.R2 + w.Wheel.OUTSIDE - 1, 0), (0, "cfg"))

    def test_petals_go_clockwise_from_the_top(self):
        f = wheel(6)
        r = (w.Wheel.R0 + w.Wheel.R1) / 2
        self.assertEqual([self.at(f, r, d)[0] for d in (0, 60, 120, 180, 240, 300, 359)], [0, 1, 2, 3, 4, 5, 0])

    def test_scale_follows_the_size_setting(self):
        f = wheel()
        f.k = 2.0
        self.assertEqual(self.at(f, w.Wheel.R1 * 1.5, 0), (0, "conv"))

    def test_no_targets_means_nothing(self):
        f = wheel(0)
        self.assertEqual(self.at(f, 100, 0), (None, None))


class Drawing(unittest.TestCase):
    def test_svg_is_valid_xml_in_every_state(self):
        f = wheel()
        for sel in ((None, None), (2, "conv"), (3, "cfg")):
            for anim in (None, {"kind": "open", "t0": 0, "delay": 0.01}, {"kind": "pick", "t0": 0, "i": 2},
                         {"kind": "close", "t0": 0}):
                with self.subTest(sel=sel, anim=anim):
                    f.sel, f.anim = sel, anim
                    ET.fromstring(f.svg())

    def test_file_names_are_escaped(self):
        f = wheel()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'a<&>".png')
            Path(path).write_text("x")
            f.files = [path]
            ET.fromstring(f.svg())

    def test_tray_icons_are_valid_svg(self):
        ET.fromstring(w.tray_icon_svg("#16a085", "#f1c40f"))


class Helpers(unittest.TestCase):
    def test_human_size(self):
        with mock.patch.object(i18n, "LANG", "en"):
            self.assertEqual([w.human_size(n) for n in (500, 1536, 5 * 1024 ** 3)], ["500 B", "1.5 KB", "5.0 GB"])
        with mock.patch.object(i18n, "LANG", "pt"):
            self.assertEqual(w.human_size(1536), "1,5 KB")

    def test_is_file_manager(self):
        self.assertTrue(w.is_file_manager(("org.gnome.Nautilus", "Home")))
        self.assertTrue(w.is_file_manager(("Gjs", "Desktop Icons 1")))
        self.assertFalse(w.is_file_manager(("Gjs", "Something else")))
        self.assertFalse(w.is_file_manager(("Gnome-terminal", "bash")))
        self.assertFalse(w.is_file_manager(None))

    def test_clipboard_path(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "my file.png")
            Path(path).touch()
            self.assertEqual(w.Capture._path("file://" + path.replace(" ", "%20")), path)
            self.assertEqual(w.Capture._path(path), path)
        self.assertIsNone(w.Capture._path("relative/file.png"))
        self.assertIsNone(w.Capture._path("/nonexistent/file.png"))

    def test_version_is_semver(self):
        self.assertRegex(w.VERSION, r"^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$")


if __name__ == "__main__":
    unittest.main()
