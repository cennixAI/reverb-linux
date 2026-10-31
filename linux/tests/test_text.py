import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reverb_linux.desktop import gvariant_string, keysym, parse_gvariant
from reverb_linux.text import cleanup, load_state, save_state


class CleanupTests(unittest.TestCase):
    def test_fillers_and_stutters_are_removed(self):
        self.assertEqual(cleanup("um send the the report uh tomorrow"), "Send the report tomorrow")
        self.assertEqual(cleanup("I think so, um."), "I think so.")
        self.assertEqual(cleanup("version 2 2 is out"), "Version 2 2 is out")

    def test_words_and_symbols_are_kept(self):
        self.assertEqual(cleanup("a c plus plus file"), "A c plus plus file")
        self.assertEqual(cleanup("C++ and C# are languages."), "C++ and C# are languages.")
        self.assertEqual(cleanup(""), "")
        self.assertEqual(cleanup("  um  "), "")


class StateTests(unittest.TestCase):
    def test_state_is_private_to_the_user(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"XDG_CONFIG_HOME": root}):
            save_state({"restore_token": "secret"})
            file = Path(root) / "reverb/state.json"
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(load_state()["restore_token"], "secret")

    def test_missing_or_corrupt_state_is_empty(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"XDG_CONFIG_HOME": root}):
            self.assertEqual(load_state(), {})
            (Path(root) / "reverb").mkdir()
            (Path(root) / "reverb/state.json").write_text("[not json")
            self.assertEqual(load_state(), {})


class DesktopTextTests(unittest.TestCase):
    def test_keysyms_cover_ascii_latin1_and_unicode(self):
        self.assertEqual(keysym("a"), ord("a"))
        self.assertEqual(keysym("A"), ord("A"))
        self.assertEqual(keysym(" "), 0x20)
        self.assertEqual(keysym("é"), 0xE9)
        self.assertEqual(keysym("—"), 0x01002014)
        self.assertEqual(keysym("\n"), 0xFF0D)

    def test_gsettings_values_round_trip(self):
        self.assertEqual(parse_gvariant("@as []\n"), [])
        self.assertEqual(parse_gvariant("['/a/', '/b/']"), ["/a/", "/b/"])
        command = "/opt/reverb/reverb --toggle"
        self.assertEqual(parse_gvariant(gvariant_string(command)), command)
        self.assertEqual(parse_gvariant(gvariant_string("it's")), "it's")


if __name__ == "__main__":
    unittest.main()
