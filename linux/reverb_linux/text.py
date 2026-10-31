"""Dictation clean-up and Reverb's one small state file. No desktop toolkit required."""
import json
import os
from pathlib import Path
import sys
import threading

FILLERS = {"um", "uh", "erm", "er", "uhm", "umm", "hmm", "mm"}
# Repeats that are real English, not stutters.
DOUBLES = {"plus", "minus", "had", "that"}
# Punctuation only, matching the Mac's punctuationCharacters: symbols such as + and $ are part of words.
PUNCTUATION = "!\"#%&'()*,-./:;?@[\\]_{}"
STATE_LOCK = threading.Lock()


def resource_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def cleanup(text):
    """The Mac app's built-in clean-up: drop fillers and stutters, capitalize the first word."""
    words = []
    for raw in text.split():
        bare = raw.lower().strip(PUNCTUATION)
        if bare in FILLERS:
            # Keep sentence punctuation that was attached to the filler.
            if raw[-1] in ".?!" and words:
                words.append(words.pop().rstrip(",") + raw[-1])
            continue
        if (words and bare and not bare.isdigit() and bare not in DOUBLES
                and words[-1].lower().strip(PUNCTUATION) == bare):
            continue  # "the the"
        words.append(raw)
    result = " ".join(words).replace(" ,", ",").replace(",,", ",")
    if result[:1].islower():
        result = result[0].upper() + result[1:]
    return result.strip(", \t\n")


def state_path():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "reverb" / "state.json"


def load_state():
    try:
        saved = json.loads(state_path().read_text())
        return saved if isinstance(saved, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state):
    """Owner-only, written atomically. Holds no audio or text, only setup flags."""
    path = state_path()
    with STATE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(state, output, indent=2)
        os.chmod(temporary, 0o600)
        temporary.replace(path)
