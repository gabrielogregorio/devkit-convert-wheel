"""Real conversions on tiny samples, through the same convert() the wheel uses."""
import os
import time
import unittest

import converters as c

from .samples import OUTPUTS, SAMPLES, build

CASES = [("photo.webp", "png", ""), ("photo.webp", "jpg", ""), ("photo.webp", "pdf", ""),
         ("photo.webp", "ico", "icon"), ("photo.webp", "avif", ""), ("photo.png", "png", "compress"),
         ("anim.gif", "mp4", "animation"), ("anim.gif", "webp", ""), ("sound.wav", "mp3", ""),
         ("sound.wav", "opus", ""), ("video.mp4", "webm", ""), ("video.mp4", "gif", "animated"),
         ("video.mp4", "mp3", "audio"), ("video.mp4", "jpg", "1 frame"), ("video.mp4", "mkv", ""),
         ("note.txt", "md", ""), ("note.txt", "pdf", ""), ("doc.md", "html", ""), ("doc.md", "pdf", ""),
         ("doc.md", "txt", ""), ("page.html", "md", ""), ("page.html", "txt", ""), ("data.json", "yaml", ""),
         ("data.json", "csv", ""), ("table.csv", "json", ""), ("sub.srt", "vtt", ""), ("logo.svg", "png", ""),
         ("doc.pdf", "png", "pages"), ("doc.pdf", "png", "1 image"), ("doc.pdf", "jpg", "1 image"),
         ("doc.pdf", "webp", "pages"), ("doc.pdf", "webp", "1 image"), ("doc.pdf", "svg", "vector"),
         ("doc.pdf", "tiff", "multipage"), ("doc.pdf", "txt", ""), ("doc.pdf", "md", "approximate"),
         ("doc.pdf", "pdf", "compress"), ("folder", "zip", "pack"), ("font.ttf", "woff2", "web")]
OFFICE_CASES = [("doc.md", "docx", "Word"), ("data.json", "xlsx", "spreadsheet")]


def size_of(path):
    if os.path.isdir(path):
        return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(path) for f in fs)
    return os.path.getsize(path)


class Conversions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()

    def convert(self, name, ext, sub):
        src = str(SAMPLES / name)
        if not os.path.exists(src):
            self.skipTest(f"sample {name} missing")
        target = next((t for t in c.targets_for(src) if t.ext == ext and t.sub == sub), None)
        self.assertIsNotNone(target, f"{name} -> {ext} ({sub}) not offered")
        start = time.time()
        out = c.convert([src], target, target.defaults(), c.default_destination(src, target, str(OUTPUTS)),
                        c.Progress())
        self.assertGreater(size_of(out), 0)
        print(f"  ✓  {name} -> {os.path.basename(out)} ({size_of(out)} B, {time.time() - start:.1f}s)")

    def test_samples(self):
        cases = CASES + (OFFICE_CASES if os.environ.get("CONVERT_WHEEL_OFFICE") == "1" else [])
        for name, ext, sub in cases:
            with self.subTest(source=name, ext=ext, sub=sub):
                self.convert(name, ext, sub)

    def test_repeated_name_gets_a_number(self):
        src = str(SAMPLES / "photo.webp")
        target = next(t for t in c.targets_for(src) if t.ext == "png")
        first = c.convert([src], target, target.defaults(), c.default_destination(src, target, str(OUTPUTS)),
                          c.Progress())
        second = c.default_destination(src, target, str(OUTPUTS))
        self.assertTrue(os.path.exists(first))
        self.assertNotEqual(first, second)
        self.assertRegex(second, r" \(\d+\)\.png$")

    def test_fake_media_gives_a_friendly_error(self):
        src = str(SAMPLES / "fake.mp3")
        target = next(t for t in c.targets_for(src) if t.ext == "wav")
        dest = str(OUTPUTS / "fake.wav")
        with self.assertRaises(c.ConversionError) as ctx:
            c.convert([src], target, target.defaults(), dest, c.Progress())
        self.assertTrue(ctx.exception.hint)
        self.assertFalse(os.path.exists(dest))


if __name__ == "__main__":
    unittest.main()
