"""Niri integration. No root access, input-device access, or network calls."""
import json
import os
import shutil
import subprocess
import sys


def command_environment():
    """System tools must use system libraries, rather than PyInstaller's Qt libraries."""
    environment = os.environ.copy()
    if getattr(sys, "frozen", False):
        if "LD_LIBRARY_PATH_ORIG" in environment:
            environment["LD_LIBRARY_PATH"] = environment["LD_LIBRARY_PATH_ORIG"]
        else:
            environment.pop("LD_LIBRARY_PATH", None)
    return environment


def is_niri():
    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    return "niri" in desktops or bool(os.environ.get("NIRI_SOCKET"))


def window_rules():
    return ('window-rule {\n'
            '    match title="^Reverb dictation$"\n'
            '    open-floating true\n'
            '    open-focused false\n'
            '    default-floating-position x=32 y=32 relative-to="bottom-right"\n'
            '}\n')


def shortcut_config(command):
    # JSON string escaping is also valid for these KDL quoted strings.
    arguments = " ".join(json.dumps(part, ensure_ascii=False) for part in command)
    startup = " ".join(json.dumps(part, ensure_ascii=False) for part in command[:-1] + ["--background"])
    return ("spawn-at-startup " + startup + "\n\n"
            "binds {\n"
            "    Ctrl+Alt+Space repeat=false { spawn " + arguments + "; }\n"
            "}\n\n" + window_rules())


def focused_window():
    """Remember only the window ID; do not retain app titles or document text."""
    try:
        result = subprocess.run(["niri", "msg", "--json", "focused-window"],
                                capture_output=True, text=True, check=True, timeout=2,
                                env=command_environment())
        window = json.loads(result.stdout)
        return window["id"] if isinstance(window, dict) else None
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return None


def type_text(text, destination):
    if destination is None or focused_window() != destination:
        raise RuntimeError("The starting window is no longer focused. Copy the saved dictation.")
    executable = shutil.which("wtype")
    if not executable:
        raise RuntimeError("Install wtype with: sudo pacman -S wtype")
    # Send words over stdin, never the process list or a shell. Do not retry:
    # a failure may follow partial input, and repeating could duplicate text.
    subprocess.run([executable, "-d", "2", "-"], input=text,
                   capture_output=True, text=True, check=True, timeout=10 + len(text) * 0.02,
                   env=command_environment())


def copy_text(text):
    """Data-control clipboard access also works when Reverb is in the background."""
    executable = shutil.which("wl-copy")
    if not executable:
        return False
    try:
        subprocess.run([executable, "--type", "text/plain;charset=utf-8"], input=text,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       text=True, check=True, timeout=5,
                       env=command_environment())
        return True
    except (OSError, subprocess.SubprocessError):
        return False
