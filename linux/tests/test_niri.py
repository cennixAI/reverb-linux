import argparse
import contextlib
import io
import json
import os
import subprocess
import unittest
from unittest.mock import patch

from reverb_linux import app, niri
from reverb_linux.desktop import Desktop


class NiriTests(unittest.TestCase):
    def test_frozen_app_restores_system_library_path_for_niri_and_wtype(self):
        with patch.object(niri.sys, "frozen", True, create=True):
            with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/opt/reverb/_internal"}, clear=True):
                self.assertNotIn("LD_LIBRARY_PATH", niri.command_environment())
            with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/opt/reverb/_internal",
                                         "LD_LIBRARY_PATH_ORIG": "/custom/libs"}, clear=True):
                self.assertEqual(niri.command_environment()["LD_LIBRARY_PATH"], "/custom/libs")

    def test_detects_pond_niri_even_with_custom_desktop_name(self):
        for environment in ({"XDG_CURRENT_DESKTOP": "niri"},
                            {"XDG_CURRENT_DESKTOP": "Pond", "NIRI_SOCKET": "/run/user/1/niri.sock"}):
            with patch.dict(os.environ, environment, clear=True):
                self.assertTrue(niri.is_niri())
        with patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "GNOME"}, clear=True):
            self.assertFalse(niri.is_niri())

    def test_shortcut_quotes_paths_and_disables_key_repeat(self):
        config = niri.shortcut_config(['/home/user/My "Apps"/reverb', '--toggle'])
        self.assertIn('spawn "/home/user/My \\"Apps\\"/reverb" "--toggle";', config)
        self.assertIn('Ctrl+Alt+Space repeat=false', config)
        self.assertIn('spawn-at-startup "/home/user/My \\"Apps\\"/reverb" "--background"', config)

    def test_focused_window_ignores_title_and_handles_closed_window(self):
        with patch.object(niri.subprocess, "run", return_value=argparse.Namespace(
                stdout='{"id": 23, "title": "private document"}')):
            self.assertEqual(niri.focused_window(), 23)
        for response in ('null', '{}', 'invalid'):
            with patch.object(niri.subprocess, "run", return_value=argparse.Namespace(stdout=response)):
                self.assertIsNone(niri.focused_window())

    def test_focus_change_or_unknown_destination_does_not_type(self):
        with patch.object(niri, "focused_window", return_value=24), \
                patch.object(niri.subprocess, "run") as run:
            for destination in (None, 23):
                with self.assertRaises(RuntimeError):
                    niri.type_text("private words", destination)
            run.assert_not_called()

    def test_unicode_and_shell_characters_are_passed_only_over_stdin(self):
        text = 'Café — $(touch /tmp/should-not-exist); "quoted"'
        with patch.object(niri, "focused_window", return_value=23), \
                patch.object(niri.shutil, "which", return_value="/usr/bin/wtype"), \
                patch.object(niri.subprocess, "run") as run:
            niri.type_text(text, 23)
            arguments, keywords = run.call_args
            self.assertEqual(arguments[0], ["/usr/bin/wtype", "-d", "2", "-"])
            self.assertEqual(keywords["input"], text)
            self.assertNotIn("shell", keywords)

    def test_missing_wtype_never_attempts_input(self):
        with patch.object(niri, "focused_window", return_value=23), \
                patch.object(niri.shutil, "which", return_value=None), \
                patch.object(niri.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "pacman"):
                niri.type_text("private words", 23)
            run.assert_not_called()

    def test_background_clipboard_uses_stdin_and_reports_failure(self):
        with patch.object(niri.shutil, "which", return_value="/usr/bin/wl-copy"), \
                patch.object(niri.subprocess, "run") as run:
            self.assertTrue(niri.copy_text("private text"))
            self.assertEqual(run.call_args.kwargs["input"], "private text")
            # wl-copy forks to serve the clipboard; inherited pipes would never
            # reach EOF while it owns the selection, so communicate() would hang.
            self.assertEqual(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)
            self.assertNotIn("private text", run.call_args.args[0])
            run.side_effect = subprocess.CalledProcessError(1, ["wl-copy"])
            self.assertFalse(niri.copy_text("private text"))
        with patch.object(niri.shutil, "which", return_value=None):
            self.assertFalse(niri.copy_text("private text"))

    def test_failed_or_partial_typing_is_not_retried_through_portal(self):
        desktop = Desktop.__new__(Desktop)
        desktop.niri = True
        with patch.object(niri, "type_text", side_effect=subprocess.CalledProcessError(1, ["wtype"])) as type_text, \
                patch.object(desktop, "run") as portal:
            with self.assertRaises(subprocess.CalledProcessError):
                desktop.type_wayland("private words", 23)
            type_text.assert_called_once_with("private words", 23)
            portal.assert_not_called()

    def test_niri_shortcut_does_not_request_a_desktop_portal(self):
        desktop = Desktop.__new__(Desktop)
        desktop.niri = True
        messages = []
        with patch.object(desktop, "run") as portal:
            desktop.start_shortcut(lambda: None, messages.append)
            self.assertIn("Niri", messages[0])
            portal.assert_not_called()

    def test_diagnostics_and_config_work_without_qt_or_models(self):
        for option in ("--diagnose", "--niri-config"):
            output = io.StringIO()
            with patch("sys.argv", ["reverb", option]), contextlib.redirect_stdout(output):
                self.assertEqual(app.main(), 0)
            if option == "--diagnose":
                self.assertIn("kernel", json.loads(output.getvalue()))
            else:
                self.assertIn("Ctrl+Alt+Space", output.getvalue())


if __name__ == "__main__":
    unittest.main()
