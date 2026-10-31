"""Real Niri/wtype integration, separate from the speech model and microphone.

Runs inside the nested Niri compositor in the offline Arch container.
"""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLineEdit

sys.path.insert(0, "/checks/source")
from reverb_linux.niri import copy_text, focused_window, type_text
from reverb_linux import window as reverb_window


class FixtureRecorder:
    MAX_SECONDS = 120

    def start(self):
        pass

    def stop(self):
        return [], 16000


class FixtureSpeech:
    def transcribe(self, samples, rate):
        return "Reverb types café and Unicode — offline."


reverb_window.Speech = FixtureSpeech
reverb_window.Recorder = FixtureRecorder

app = QApplication([])
first, second = QLineEdit(), QLineEdit()
first.setWindowTitle("Reverb Niri typing target")
first.resize(800, 80)
first.show()
text = "Reverb types café and Unicode — offline."
result = {"ok": False}
controller = reverb_window.Window(app, argparse.Namespace(toggle=False, background=True, smoke_ui=False))


def stage_one():
    try:
        result["destination"] = focused_window()
        assert result["destination"] is not None, "Niri did not expose the focused target"
        diagnostics = json.loads(subprocess.run(["reverb", "--diagnose"], check=True,
                                               capture_output=True, text=True, timeout=10).stdout)
        assert diagnostics["niri_focused_window"] == result["destination"], diagnostics
        assert controller.phase == "ready", controller.phase
        controller.toggle()
        QTimer.singleShot(400, finish_recording)
    except BaseException as error:
        result["error"] = repr(error)
        app.quit()


def finish_recording():
    try:
        assert controller.phase == "recording", controller.phase
        assert focused_window() == result["destination"], "Recording control stole focus"
        controller.toggle()
        result["delivery_deadline"] = time.monotonic() + 10
        QTimer.singleShot(200, stage_two)
    except BaseException as error:
        result["error"] = repr(error)
        app.quit()


def stage_two():
    try:
        if ((controller.phase != "ready" or first.text() != text)
                and time.monotonic() < result["delivery_deadline"]):
            QTimer.singleShot(100, stage_two)
            return
        assert first.text() == text, (first.text(), controller.phase, controller.status.text())
        assert controller.result.toPlainText() == text
        second.setWindowTitle("Reverb changed destination")
        second.show()
        QTimer.singleShot(400, stage_three)
    except BaseException as error:
        result["error"] = repr(error)
        app.quit()


def stage_three():
    try:
        assert focused_window() != result["destination"], "Second window did not get focus"
        try:
            type_text("This must not be typed", result["destination"])
        except RuntimeError:
            pass
        else:
            raise AssertionError("Changed destination received text")
        assert not second.text()
        assert copy_text(text), "Background clipboard copy failed"
        copied = subprocess.run(["wl-paste", "--no-newline"], check=True, capture_output=True,
                                text=True, timeout=5).stdout
        assert copied == text, repr(copied)
        # Enter through the nested compositor's physical-keyboard backend.
        # Niri 26.04's virtual keyboard path forwards text to clients without
        # exercising the normal compositor shortcut processing.
        host_environment = dict(os.environ, DISPLAY=":99")
        parent = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "^niri$"],
                                env=host_environment, check=True, capture_output=True,
                                text=True, timeout=5).stdout.splitlines()[0]
        subprocess.run(["xdotool", "windowfocus", "--sync", parent],
                       env=host_environment, check=True, timeout=5)
        subprocess.run(["xdotool", "key", "--clearmodifiers", "--delay", "40", "ctrl+alt+space"],
                       env=host_environment, check=True, timeout=5)
        result["shortcut_deadline"] = time.monotonic() + 3
        QTimer.singleShot(400, finish)
    except BaseException as error:
        result["error"] = repr(error)
        app.quit()


def finish():
    if not Path("/tmp/reverb-shortcut").exists() and time.monotonic() < result["shortcut_deadline"]:
        QTimer.singleShot(100, finish)
        return
    result["ok"] = Path("/tmp/reverb-shortcut").exists() and first.text() == text and not second.text()
    if not result["ok"]:
        result["error"] = repr(("shortcut", Path("/tmp/reverb-shortcut").exists(), first.text(), second.text()))
    app.quit()


QTimer.singleShot(800, stage_one)
QTimer.singleShot(15000, app.quit)
app.exec()
controller.shutdown()
if not result["ok"]:
    raise SystemExit("Niri integration failed: " + result.get("error", "shortcut did not fire or timed out"))
print("Niri: Unicode input, changed-window protection and Ctrl+Alt+Space worked.")
