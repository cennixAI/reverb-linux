# Reverb for Linux

Offline dictation for Linux x86_64, with support for Ubuntu/Mint and Pond/Arch. Dictation only:
press a key, speak, press it again, and your words are typed where your cursor is.
Speech is recognized on your computer by the bundled Parakeet model. There is no
account and no cloud, and nothing is downloaded after installation.

The Mac app in `Sources/` is separate and has more features. This folder is a
small Python/Qt app that only does dictation.

## Install

**Pond / Arch (Niri):** use `reverb-…-x86_64.pkg.tar.zst`:

```sh
sha256sum --ignore-missing -c SHA256SUMS.txt
sudo pacman -U ./reverb-0.3.1.linux1-1-x86_64.pkg.tar.zst
```

The package installs `wtype` and `wl-clipboard` through pacman. Python, speech
recognition and the model are bundled; the app needs no Python installation or
model download. Open **Reverb**, then follow the Niri setup below.

**Ubuntu / Mint:** build a Debian package from source first; no public Debian installer accompanies this preview. Then open the `Reverb-…-linux-x86_64.deb` file with your software installer and choose
Install, or run `sudo apt install ./Reverb-…-linux-x86_64.deb`. Then open **Reverb**
from your app menu.

## Use

1. Click where you want the text to go, in any app.
2. Press **Ctrl+Alt+Space** and speak. A small **Listening** control appears at
   the bottom of the screen.
3. Press **Ctrl+Alt+Space** again, or click **Done**. Your words are typed at the
   cursor.

You can also click **Start dictation** in Reverb's window. Reverb steps aside so
your words go back into the app you were using. **Cancel** throws a recording
away. Recordings stop automatically after two minutes.

Closing the window keeps Reverb running so the shortcut still works. **Quit**
stops it. On Ubuntu/Mint, **Start when I log in** is on by default.

### First-time setup on Pond / Niri

Click **Copy Niri shortcut**, or run `reverb --niri-config`. Add the printed
configuration to your Niri config (usually `~/.config/niri/config.kdl`). With the
installed package it looks like this:

```kdl
spawn-at-startup "/opt/reverb/reverb" "--background"

binds {
    Ctrl+Alt+Space repeat=false { spawn "/opt/reverb/reverb" "--toggle"; }
}

window-rule {
    match title="^Reverb dictation$"
    open-floating true
    open-focused false
    default-floating-position x=32 y=32 relative-to="bottom-right"
}
```

If you already have a `binds` block, add just the `Ctrl+Alt+Space` line to it.
Use your existing Pond configuration location if it differs. Run `niri validate`
after saving; Niri reloads configuration automatically. Open Reverb now for the
current session; `spawn-at-startup` starts it in future sessions. Remove that line
to disable automatic startup. Key repeat is disabled so holding the shortcut
doesn't repeatedly start and stop recording.
The window rule keeps the recording control at the bottom right without taking
focus from the field you're dictating into; include it with the shortcut.

Niri uses `wtype` with its virtual keyboard protocol. It does not ask for the
GNOME/KDE remote-desktop approval or require root/input-group access. Reverb
checks that the original Niri window is still focused immediately before typing;
if it changed, the words are copied for manual paste. This check identifies a
window, not individual tabs or text fields inside it. Keep the intended field
focused until typing finishes. Typing failures are never automatically retried,
because some words may already have been entered.

The target is Pond with Niri and kernel `7.3.0-4-pond`. Kernel-specific
modules are unnecessary. Real microphone/device and physical shortcut behavior
still require a trial on that machine.

### First-time setup on GNOME / KDE Wayland

Ubuntu uses Wayland, which needs two one-time approvals:

* **Shortcut:** click **Turn on Ctrl+Alt+Space** in Reverb's window. It adds a
  shortcut under Settings → Keyboard → Custom Shortcuts. On KDE, approve the
  desktop's shortcut dialog instead. On other desktops, add a shortcut yourself
  that runs `reverb --toggle`.
* **Typing:** when your desktop asks whether Reverb may control your keyboard,
  choose **Allow**. Reverb asks for the keyboard only, never your screen. If
  your desktop remembers the approval, it won't ask again. Otherwise it asks
  once each time Reverb starts.

Linux Mint (Cinnamon) and other X11 desktops don't need either step.

If typing isn't possible, Reverb copies your words to the clipboard and tells you
to press Ctrl+V. The last dictation also stays in Reverb's window, with a
**Copy** button, until you quit.

## Privacy

* The app has no network code. Speech recognition runs on your CPU.
* Audio stays in memory and is discarded after recognition. Transcripts are not
  saved. Only the most recent dictation is shown, until you quit.
* Reverb saves one small file, `~/.config/reverb/state.json` (owner-only), with
  setup flags and, on Wayland, the desktop's remembered typing approval.

## Build

On Ubuntu x86_64 with Python 3.11, install `requirements.txt`, `libarchive-tools`,
`zstd` and the libraries listed in `package.sh`, then:

```sh
python download_models.py   # pinned, checksum-verified, about 480 MB
python main.py              # run from source
bash package.sh             # build both installers in dist/packages/
```

Only `download_models.py` downloads anything, and only when you run it at build time.

```sh
reverb --toggle                       # start or finish dictation in the running app
reverb --transcribe-file speech.wav   # print the text of a 16-bit WAV file
reverb --check-model                  # load the bundled model and exit
reverb --diagnose                     # local kernel, architecture, desktop and wtype availability
reverb --niri-config                  # print shortcut and startup configuration; writes nothing
```

The original Linux installer verification workflow ran on Ubuntu 22.04 and performed the following checks:

* Runs the unit tests.
* Runs an end-to-end X11 test: press the shortcut in another app, recognize a
  sample recording, and check the words are pasted into that app's text field.
* Builds the `.deb`, installs it, and transcribes with networking disabled.
* Installs the package on Ubuntu 24.04 too.
* Installs the Arch package in a clean Arch container and, without networking,
  checks recognition, native Wayland UI, Niri configuration, Unicode typing,
  changed-window protection and shortcut dispatch under nested Niri.

GNOME/KDE portal typing and real microphones still need an actual desktop trial.

See [THIRD_PARTY.md](THIRD_PARTY.md) for model and dependency notices.
