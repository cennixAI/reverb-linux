"""End to end on a real X11 server: focus another app's text field, press Ctrl+Alt+Space,
"speak" a recording, press Ctrl+Alt+Space again, and check the words were pasted there.

The microphone is replaced by a WAV file; everything else is the shipping code path:
the global shortcut, the floating control, offline recognition, the clipboard, and XTest paste.
Run under xvfb-run with a window manager, e.g. openbox.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WAV = ROOT / "models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/test_wavs/0.wav"
EXPECTED = ["don't wish to see it any more", "very like the old portrait"]
STALE = "stale clipboard from another app"


def target(output):
    """A separate app with a focused text field that saves its contents to `output`.
    When `output`.copy appears, it copies text of its own, as a user might just before dictating."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLineEdit
    app = QApplication([])
    field = QLineEdit()
    field.setWindowTitle("Reverb paste target")
    field.resize(900, 60)
    field.show()
    field.activateWindow()
    field.setFocus()
    output = Path(output)
    request, copied = output.with_suffix(".copy"), output.with_suffix(".copied")

    def poll():
        output.write_text(field.text())
        if request.exists() and not copied.exists():
            app.clipboard().setText(STALE)
            copied.write_text("1")
    save = QTimer()
    save.timeout.connect(poll)
    save.start(100)
    app.exec()


def xdotool(*args):
    return subprocess.run(["xdotool", *args], check=True, capture_output=True, text=True).stdout.strip()


def main():
    from reverb_linux import speech
    from reverb_linux.speech import read_wav

    class WavRecorder(speech.Recorder):
        def start(self):
            self.started = True

        def stop(self):
            return read_wav(WAV)
    speech.Recorder = WavRecorder
    from reverb_linux import window as reverb_window
    reverb_window.Recorder = WavRecorder

    with tempfile.TemporaryDirectory() as home:
        os.environ["XDG_CONFIG_HOME"] = home
        os.environ["XDG_RUNTIME_DIR"] = home
        output = Path(home) / "field.txt"
        field = subprocess.Popen([sys.executable, __file__, "--target", str(output)])
        reverb_window.AUTOSTART = Path(home) / "autostart/ai.cennix.Reverb.desktop"
        result = {}

        def drive(window):
            finished = result["finished"]
            try:
                deadline = time.monotonic() + 60
                while window.phase != "ready" or "Press Ctrl+Alt+Space" not in window.shortcut.text():
                    assert time.monotonic() < deadline, "Reverb did not become ready: " + window.shortcut.text()
                    time.sleep(0.2)
                # Another app owns the clipboard now, newer than anything Reverb has seen.
                output.with_suffix(".copy").write_text("1")
                while not output.with_suffix(".copied").exists():
                    assert time.monotonic() < deadline, "Target app did not copy"
                    time.sleep(0.1)
                time.sleep(0.5)
                target_window = xdotool("search", "--sync", "--name", "Reverb paste target").split()[0]
                xdotool("windowactivate", "--sync", target_window)
                time.sleep(0.5)
                xdotool("key", "--clearmodifiers", "ctrl+alt+space")
                time.sleep(1)
                assert window.phase == "recording", "Shortcut did not start dictation: " + window.phase
                # The floating control must not have taken focus from the target app.
                assert xdotool("getwindowfocus") == target_window, "The recording control stole focus"
                xdotool("key", "--clearmodifiers", "ctrl+alt+space")
                deadline = time.monotonic() + 60
                while not output.exists() or not output.read_text():
                    assert time.monotonic() < deadline, "Nothing reached the target field. Status: " + window.status.text()
                    time.sleep(0.2)
                time.sleep(0.5)
                text = output.read_text()
                print("Target field received: " + text, flush=True)
                assert STALE not in text, "Pasted the old clipboard instead of the dictation"
                assert all(phrase in text.lower() for phrase in EXPECTED), text
                assert window.result.toPlainText() == text, window.result.toPlainText()
                result["ok"] = True
            except BaseException as error:
                result["error"] = repr(error)
            finally:
                finished.emit()

        from PySide6.QtCore import QObject, QTimer, Signal

        class Finished(QObject):
            signal = Signal()
        original_init = reverb_window.Window.__init__

        def patched(self, app, args):
            original_init(self, app, args)
            # Quit on the GUI thread once the driving thread is done.
            holder = Finished(self)
            holder.signal.connect(self.quit)
            result["finished"] = holder.signal
            QTimer.singleShot(0, lambda: threading.Thread(target=drive, args=(self,), daemon=True).start())
        reverb_window.Window.__init__ = patched
        try:
            reverb_window.run(argparse.Namespace(toggle=False, background=True, smoke_ui=False),
                              os.path.join(home, "reverb.sock"))
        finally:
            field.terminate()
            field.wait(5)
        if not result.get("ok"):
            print("Desktop integration failed: " + result.get("error", "no result"), flush=True)
            return 1
        print("X11: shortcut, offline recognition, and paste into another app all worked.", flush=True)
        return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--target":
        target(sys.argv[2])
    else:
        raise SystemExit(main())
