import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import converters as c
import i18n


class English(unittest.TestCase):
    """Messages compared in English, whatever the machine language."""

    def setUp(self):
        patcher = mock.patch.object(i18n, "LANG", "en")
        patcher.start()
        self.addCleanup(patcher.stop)


class FreePath(unittest.TestCase):
    def test_numbers_until_free(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(c.free_path(d, "a", "png"), os.path.join(d, "a.png"))
            Path(os.path.join(d, "a.png")).touch()
            Path(d, "a (1).png").touch()
            self.assertEqual(c.free_path(d, "a", "png"), os.path.join(d, "a (2).png"))

    def test_without_extension(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "doc"))
            self.assertEqual(c.free_path(d, "doc", ""), os.path.join(d, "doc (1)"))

    def test_default_destination_uses_source_folder(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "photo.webp")
            target = c.Target("png", "image", None)
            self.assertEqual(c.default_destination(src, target), os.path.join(d, "photo.png"))
            self.assertEqual(c.default_destination(src, target, "/out"), "/out/photo.png")


class Names(unittest.TestCase):
    def test_split_ext(self):
        cases = {"a.tar.gz": ("a", "tar.gz"), "b.TGZ": ("b", "tar.gz"), "c.txz": ("c", "tar.xz"),
                 "Photo.JPG": ("Photo", "jpg"), "/x/folder/": ("folder", ""), "no-ext": ("no-ext", ""),
                 "v1.2.mp4": ("v1.2", "mp4")}
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(c.split_ext(name), expected)

    def test_shorten_middle_keeps_the_end(self):
        self.assertEqual(c.shorten_middle("short.png", 20), "short.png")
        out = c.shorten_middle("a-very-long-file-name-here.webp", 16)
        self.assertEqual(len(out), 16)
        self.assertTrue(out.endswith(".webp"))
        self.assertIn("…", out)


class Times(English):
    def test_seconds(self):
        for txt, expected in (("90", 90), ("1:30", 90), ("00:01:30.5", 90.5), ("1,5", 1.5), ("", None), (None, None)):
            with self.subTest(txt=txt):
                self.assertEqual(c.seconds(txt), expected)

    def test_invalid_time(self):
        with self.assertRaises(c.ConversionError) as ctx:
            c.seconds("abc")
        self.assertIn("abc", ctx.exception.reason)

    def test_ffmpeg_trim(self):
        self.assertEqual(c.ffmpeg_trim({}, 10), ([], 10))
        self.assertEqual(c.ffmpeg_trim({"start": "2", "end": "0:08"}, 10), (["-ss", "2.0", "-to", "8.0"], 6.0))
        self.assertEqual(c.ffmpeg_trim({"start": "20"}, 10)[1], None)  # start past the end: no progress


class Pages(English):
    def test_all(self):
        for spec in ("", None, "all", "*", "todas"):
            with self.subTest(spec=spec):
                self.assertEqual(c.pages(spec, 3), [0, 1, 2])

    def test_ranges(self):
        self.assertEqual(c.pages("1-3,5", 10), [0, 1, 2, 4])
        self.assertEqual(c.pages("8-", 10), [7, 8, 9])
        self.assertEqual(c.pages("2, 50", 3), [1])

    def test_invalid(self):
        for spec in ("x", "20"):
            with self.subTest(spec=spec), self.assertRaises(c.ConversionError):
                c.pages(spec, 3)


class ProcessErrors(English):
    def test_known_rules(self):
        cases = {"write error: No space left on device": "Disk full.",
                 "moov atom not found": "Incomplete video (interrupted download or recording).",
                 "Invalid data found when processing input": "corrupted or wrong extension"}
        for stderr, reason in cases.items():
            with self.subTest(stderr=stderr):
                err = c.process_error("ffmpeg", stderr, 1)
                self.assertIn(reason, err.reason)
                self.assertTrue(err.hint)

    def test_unknown_error_keeps_the_tail(self):
        err = c.process_error("gs", "\n".join(f"line {i}" for i in range(40)), 3)
        self.assertIn("'gs'", err.reason)
        self.assertIn("3", err.reason)
        self.assertTrue(err.details.endswith("line 39"))
        self.assertNotIn("line 10\n", err.details)

    def test_missing_tool(self):
        with mock.patch.object(c.shutil, "which", return_value=None), self.assertRaises(c.ConversionError) as ctx:
            c.Progress().run(["soffice", "--version"])
        self.assertIn("sudo apt install libreoffice", ctx.exception.hint)


class Targets(unittest.TestCase):
    SAMPLES = ("a.png", "a.jpg", "a.webp", "a.gif", "a.svg", "a.mp3", "a.mp4", "a.mkv", "a.pdf", "a.txt", "a.md",
               "a.html", "a.docx", "a.xlsx", "a.pptx", "a.json", "a.csv", "a.srt", "a.ttf", "a.zip", "a.tar.gz")

    def test_key_and_defaults(self):
        t = c.Target("png", "image", None, [c.Option("q", "Q", "number", 90)], sub="compress")
        self.assertEqual(t.key, "image:PNG:compress")
        self.assertEqual(t.defaults(), {"q": 90})
        self.assertEqual(t.defaults({"q": 50, "gone": 1}), {"q": 50})

    def test_every_file_type_has_targets_with_unique_keys(self):
        for name in self.SAMPLES:
            with self.subTest(name=name):
                targets = c.targets_for("/nonexistent/" + name)
                self.assertTrue(targets)
                keys = [t.key for t in targets]
                self.assertEqual(len(keys), len(set(keys)))

    def test_same_format_only_as_compress(self):
        exts = {(t.ext, t.sub) for t in c.targets_for("/x/a.jpg")}
        self.assertIn(("jpg", "compress"), exts)
        self.assertNotIn(("jpg", ""), exts)
        self.assertNotIn("mp3", {t.ext for t in c.targets_for("/x/a.mp3")})

    def test_video_offers_audio_and_compress(self):
        subs = {(t.ext, t.sub) for t in c.targets_for("/x/a.mp4")}
        self.assertTrue({("mp3", "audio"), ("mp4", "compress"), ("jpg", "1 frame")} <= subs)

    def test_pdf_has_extras(self):
        extras = [t for t in c.targets_for("/x/a.pdf") if t.extra]
        self.assertTrue(extras)
        self.assertTrue(all(not t.extra for t in c.targets_for("/x/a.mp3")))

    def test_folder_packs(self):
        with tempfile.TemporaryDirectory() as d:
            targets = c.targets_for(d)
        self.assertEqual({t.family for t in targets}, {"archive"})
        self.assertEqual({t.sub for t in targets}, {"pack"})

    def test_unknown_file_has_nothing(self):
        with tempfile.NamedTemporaryFile(suffix=".xyz") as f:
            f.write(b"\x00\x01\x02binary")
            f.flush()
            self.assertEqual(c.targets_for(f.name), [])

    def test_choice_defaults_are_valid_choices(self):
        for name in self.SAMPLES:
            for t in c.targets_for("/x/" + name):
                for o in t.options:
                    if o.kind == "choice":
                        with self.subTest(target=t.key, option=o.key):
                            self.assertIn(o.default, [v for v, _ in o.choices])


class TextAndData(English):
    def test_html_to_markdown(self):
        md = c.html_to("<h2>Title</h2><p>A <b>bold</b> <a href='http://x'>link</a></p><ul><li>one</li></ul>", md=True)
        self.assertIn("## Title", md)
        self.assertIn("**bold**", md)
        self.assertIn("[link](http://x)", md)
        self.assertIn("- one", md)

    def test_html_to_text_drops_scripts(self):
        txt = c.html_to("<script>alert(1)</script><p>hi</p>", md=False)
        self.assertEqual(txt, "hi\n")

    def test_read_text_falls_back_to_cp1252(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as f:
            f.write("ação\r\n".encode("cp1252"))
        self.addCleanup(os.remove, f.name)
        self.assertEqual(c.read_text(f.name), "ação\n")

    def test_write_csv_joins_columns(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "t.csv")
            c.write_csv({"rows": [{"a": 1}, {"b": [1, 2]}]}, out, ",")
            self.assertEqual(Path(out).read_text().splitlines(), ["a,b", "1,", ',"[1, 2]"'])

    def test_write_csv_rejects_non_tables(self):
        with self.assertRaises(c.ConversionError):
            c.write_csv([1, 2, 3], "/nonexistent/x.csv", ",")


class Convert(English):
    def test_missing_source(self):
        with self.assertRaises(c.ConversionError) as ctx:
            c.convert(["/nonexistent/a.png"], c.Target("jpg", "image", None), {}, "/tmp/a.jpg", c.Progress())
        self.assertIn("/nonexistent/a.png", ctx.exception.reason)

    def test_failure_removes_the_partial_output(self):
        def broken(sources, destination, op, prog):
            Path(destination).write_text("partial")
            raise ValueError("boom")

        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "a.txt")
            Path(src).write_text("x")
            dest = os.path.join(d, "a.out")
            with self.assertRaises(c.ConversionError) as ctx:
                c.convert([src], c.Target("out", "text", broken), {}, dest, c.Progress())
            self.assertFalse(os.path.exists(dest))
            self.assertIn("boom", ctx.exception.reason)

    def test_empty_output_is_an_error(self):
        def empty(sources, destination, op, prog):
            Path(destination).touch()
            return destination

        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "a.txt")
            Path(src).write_text("x")
            with self.assertRaises(c.ConversionError):
                c.convert([src], c.Target("out", "text", empty), {}, os.path.join(d, "a.out"), c.Progress())

    def test_cancel_stops_before_running(self):
        p = c.Progress()
        p.cancel()
        with self.assertRaises(c.Cancelled):
            p.run(["true"])


if __name__ == "__main__":
    unittest.main()
