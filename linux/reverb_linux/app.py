import argparse
import os
from pathlib import Path
import socket
import tempfile

from . import __version__


def socket_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return os.path.join(runtime, "ai.cennix.Reverb." + str(os.getuid()) + ".sock")


def send(command):
    """Message the running Reverb. Kept free of Qt so the shortcut starts recording instantly."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(socket_path())
            client.sendall(command)
        return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(prog="reverb", description="Reverb for Linux: offline dictation")
    parser.add_argument("--toggle", action="store_true", help="start or finish dictation")
    parser.add_argument("--background", action="store_true", help="start without showing the window")
    parser.add_argument("--transcribe-file", type=Path, metavar="WAV", help="print the text of a 16-bit WAV file")
    parser.add_argument("--check-model", action="store_true", help="load the bundled speech model and exit")
    parser.add_argument("--niri-config", action="store_true", help="print a Niri dictation shortcut block")
    parser.add_argument("--diagnose", action="store_true", help="print local Linux compatibility information")
    parser.add_argument("--smoke-ui", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version="Reverb " + __version__)
    args = parser.parse_args()
    if args.niri_config:
        from .desktop import toggle_command
        from .niri import shortcut_config
        print(shortcut_config(toggle_command()), end="")
        return 0
    if args.diagnose:
        import json
        import platform
        import shutil
        from .niri import focused_window, is_niri
        try:
            distro = platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
        except (OSError, AttributeError):
            distro = "Unknown"
        print(json.dumps({"version": __version__, "kernel": platform.release(),
                          "architecture": platform.machine(), "distribution": distro,
                          "session": os.environ.get("XDG_SESSION_TYPE", "unknown"),
                          "niri": is_niri(), "wtype": bool(shutil.which("wtype")),
                          "niri_focused_window": focused_window() if is_niri() else None}, indent=2))
        return 0
    if args.check_model or args.transcribe_file:
        from .speech import Speech, read_wav
        from .text import cleanup
        engine = Speech()
        if args.transcribe_file:
            print(cleanup(engine.transcribe(*read_wav(args.transcribe_file))))
        else:
            print("Speech model loaded.")
        return 0
    if not args.smoke_ui:
        command = b"toggle" if args.toggle else b"" if args.background else b"show"
        if send(command):
            return 0
    if os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY") and "QT_QPA_PLATFORM" not in os.environ:
        # Through XWayland the recording control can float on top without taking focus from your app.
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    from .window import run
    return run(args, socket_path())
