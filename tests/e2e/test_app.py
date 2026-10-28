"""Starts the real app in an isolated X server and session bus, with a throwaway HOME.

Only runs through tools/smoke.sh (xvfb-run + dbus-run-session): against the real desktop the
new process would hand its command line to the running instance and grab the real mouse.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ISOLATED = os.environ.get("CONVERT_WHEEL_SMOKE") == "1"


def wait_for(check, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.1)
    return False


@unittest.skipUnless(ISOLATED, "run it with tools/smoke.sh (isolated X server and session bus)")
class App(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory(prefix="convert-wheel-home-")
        self.addCleanup(self.home.cleanup)
        self.env = dict(os.environ, HOME=self.home.name)
        self.log = Path(self.home.name, ".cache/devkit-convert-wheel/convert-wheel.log")
        self.config = Path(self.home.name, ".config/devkit-convert-wheel/config.json")

    def start(self, *args):
        p = subprocess.Popen([sys.executable, str(ROOT / "convert_wheel.py"), *args], env=self.env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: p.poll() is None and (p.terminate(), p.wait(5)))
        return p

    def test_starts_off_with_tray_icons(self):
        p = self.start("--off")
        self.assertTrue(wait_for(lambda: self.log.exists() and "started" in self.log.read_text()),
                        "no 'started' line in the log")
        self.assertTrue(wait_for(self.config.exists))
        self.assertTrue(json.loads(self.config.read_text())["paused"])
        icons = Path(self.home.name, ".cache/devkit-convert-wheel/icons")
        self.assertEqual(sorted(os.listdir(icons)), ["convert-wheel-off.svg", "convert-wheel-on.svg"])
        time.sleep(1)
        self.assertIsNone(p.poll(), "the app exited by itself")

    def test_second_launch_hands_over_to_the_first(self):
        first = self.start("--off")
        self.assertTrue(wait_for(lambda: self.log.exists() and "started" in self.log.read_text()))
        second = self.start("--config")
        self.assertEqual(second.wait(10), 0)
        self.assertIsNone(first.poll())
        self.assertEqual(self.log.read_text().count("started"), 1)

    def test_version(self):
        out = subprocess.run([sys.executable, str(ROOT / "convert_wheel.py"), "--version"], env=self.env,
                             capture_output=True, text=True, timeout=10)
        self.assertEqual(out.stdout.strip(), "devkit-convert-wheel " + (ROOT / "VERSION").read_text().strip())


if __name__ == "__main__":
    unittest.main()
