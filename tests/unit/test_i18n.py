import ast
import importlib
import os
import re
import unittest
from pathlib import Path
from unittest import mock

import i18n

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ("converters.py", "convert_wheel.py")


def marked_strings():
    """Every literal passed to tr()/tr_noop() in the app sources."""
    found = {}
    for name in SOURCES:
        for node in ast.walk(ast.parse((ROOT / name).read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("tr", "tr_noop")
                    and node.args and isinstance(node.args[0], ast.Constant)):
                found.setdefault(node.args[0].value, name)
    return found


def fields(text):
    return sorted(re.findall(r"\{(\w*)\}", text))


class DetectLanguage(unittest.TestCase):
    VARS = ("CONVERT_WHEEL_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")

    def lang_with(self, **env):
        clean = {k: v for k, v in os.environ.items() if k not in self.VARS}
        with mock.patch.dict(os.environ, {**clean, **env}, clear=True):
            return importlib.reload(i18n).LANG

    @classmethod
    def tearDownClass(cls):
        importlib.reload(i18n)  # back to the language of the real environment

    def test_portuguese_locale(self):
        self.assertEqual(self.lang_with(LANG="pt_BR.UTF-8"), "pt")

    def test_portugal_also_gets_portuguese(self):
        self.assertEqual(self.lang_with(LANG="pt_PT.UTF-8"), "pt")

    def test_other_locale_is_english(self):
        self.assertEqual(self.lang_with(LANG="de_DE.UTF-8"), "en")

    def test_c_locale_is_english(self):
        self.assertEqual(self.lang_with(LANG="C.UTF-8"), "en")

    def test_nothing_set_is_english(self):
        self.assertEqual(self.lang_with(), "en")

    def test_language_list_wins_over_lang(self):
        self.assertEqual(self.lang_with(LANGUAGE="en_US:pt_BR", LANG="pt_BR.UTF-8"), "en")

    def test_override_wins_over_everything(self):
        self.assertEqual(self.lang_with(CONVERT_WHEEL_LANG="pt_BR", LANGUAGE="en", LANG="en_US.UTF-8"), "pt")


class Translate(unittest.TestCase):
    def test_english_returns_source(self):
        with mock.patch.object(i18n, "LANG", "en"):
            self.assertEqual(i18n.tr("Convert"), "Convert")
            self.assertEqual(i18n.decimal("1.5 MB"), "1.5 MB")

    def test_portuguese_uses_catalog(self):
        with mock.patch.object(i18n, "LANG", "pt"):
            self.assertEqual(i18n.tr("Convert"), "Converter")
            self.assertEqual(i18n.decimal("1.5 MB"), "1,5 MB")

    def test_unknown_text_falls_back_to_source(self):
        with mock.patch.object(i18n, "LANG", "pt"):
            self.assertEqual(i18n.tr("PNG"), "PNG")

    def test_noop_never_translates(self):
        with mock.patch.object(i18n, "LANG", "pt"):
            self.assertEqual(i18n.tr_noop("compress"), "compress")


class Catalog(unittest.TestCase):
    def test_every_marked_string_has_portuguese(self):
        missing = [f"{where}: {text!r}" for text, where in marked_strings().items() if text not in i18n.PT_BR]
        self.assertEqual(missing, [])

    def test_placeholders_match(self):
        bad = [text for text in marked_strings() if text in i18n.PT_BR and fields(text) != fields(i18n.PT_BR[text])]
        self.assertEqual(bad, [])

    def test_no_unused_entries(self):
        self.assertEqual(sorted(set(i18n.PT_BR) - set(marked_strings())), [])


if __name__ == "__main__":
    unittest.main()
