"""Reverb's window and floating recording control. Dictation only."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import sys
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QIcon
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QMenu, QPlainTextEdit,
                               QPushButton, QStyle, QSystemTrayIcon, QVBoxLayout, QWidget)

from .desktop import SHORTCUT, Desktop, toggle_command
from .speech import Recorder, Speech
from .text import cleanup, load_state, save_state
from . import niri

LISTENING = "<span style=\"color: #ff453a;\">●</span> Listening"
AUTOSTART = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / "ai.cennix.Reverb.desktop"


def desktop_exec(arguments):
    """Quote a command for a .desktop file's Exec line."""
    def quote(argument):
        argument = argument.replace("%", "%%")
        if not re.search(r"[\s\"'\\><~|&;$*?#()`]", argument):
            return argument
        return '"' + re.sub(r'(["`$\\])', r"\\\\\1", argument) + '"'
    return " ".join(map(quote, arguments))


def set_autostart(enabled):
    if enabled:
        AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART.write_text("[Desktop Entry]\nType=Application\nName=Reverb\nComment=Offline dictation\n"
                             "Exec=" + desktop_exec(toggle_command()[:-1] + ["--background"]) + "\n"
                             "Icon=audio-input-microphone\nTerminal=false\nX-GNOME-Autostart-enabled=true\n")
    else:
        AUTOSTART.unlink(missing_ok=True)


class Events(QObject):
    toggle = Signal()
    shortcut = Signal(str)
    ready = Signal(object)
    failed = Signal(str, bool)  # message, show the window
    paste = Signal(str)
    done = Signal(str, bool)  # text, typed into the app
    permission = Signal(bool)


class Pill(QWidget):
    """Small always-on-top control shown while listening. It never takes keyboard focus."""

    def __init__(self, finish, cancel):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("Reverb dictation")
        self.setStyleSheet("QWidget { background: #1c1c1e; color: white; font-size: 14px; }"
                           "QPushButton { background: #3a3a3c; border: none; border-radius: 6px; padding: 6px 14px; }"
                           "QPushButton:hover { background: #4a4a4c; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 8, 8)
        self.label = QLabel()
        layout.addWidget(self.label)
        self.finish = QPushButton("Done")
        self.finish.clicked.connect(finish)
        layout.addWidget(self.finish)
        self.cancel = QPushButton("Cancel")
        self.cancel.clicked.connect(cancel)
        layout.addWidget(self.cancel)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def present(self, text, buttons=False, seconds=0):
        self.timer.stop()
        self.label.setText(text)
        self.finish.setVisible(buttons)
        self.cancel.setVisible(buttons)
        self.adjustSize()
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.bottom() - self.height() - 32)
        self.show()
        if seconds:
            self.timer.start(seconds * 1000)


class Window(QWidget):
    def __init__(self, app, args):
        super().__init__()
        self.app = app
        self.state = load_state()
        self.desktop = Desktop(self.state)
        self.recorder = Recorder()
        self.events = Events()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.speech = None
        self.phase = "loading"  # loading, ready, starting, recording, working, broken
        self.start_when_ready = args.toggle
        self.finished_at = 0.0
        self.quitting = False
        self.destination = None

        self.setWindowTitle("Reverb")
        self.setMinimumWidth(440)
        icon = QIcon.fromTheme("audio-input-microphone", self.style().standardIcon(QStyle.SP_MediaVolume))
        self.setWindowIcon(icon)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        title = QLabel("Reverb")
        title.setStyleSheet("font-size: 26px; font-weight: 600;")
        layout.addWidget(title)
        self.status = QLabel("Loading the speech model…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.button = QPushButton("Start dictation")
        self.button.setMinimumHeight(52)
        self.button.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.button.setEnabled(False)
        self.button.clicked.connect(self.from_button)
        layout.addWidget(self.button)
        self.shortcut = QLabel("Setting up " + SHORTCUT + "…")
        self.shortcut.setWordWrap(True)
        self.shortcut.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.shortcut)
        self.setup = QPushButton("Turn on " + SHORTCUT)
        self.setup.clicked.connect(self.install_shortcut)
        self.setup.setVisible(False)
        layout.addWidget(self.setup)
        self.allow = QPushButton("Allow Reverb to type into apps…")
        self.allow.clicked.connect(self.allow_typing)
        layout.addWidget(self.allow)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("Your last dictation appears here until you quit.")
        self.result.setMaximumHeight(110)
        layout.addWidget(self.result)
        row = QHBoxLayout()
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: self.app.clipboard().setText(self.result.toPlainText()))
        row.addWidget(copy)
        row.addStretch()
        self.login = QCheckBox("Start when I log in")
        self.login.setVisible(not self.desktop.niri)
        row.addWidget(self.login)
        quit_button = QPushButton("Quit")
        quit_button.clicked.connect(self.quit)
        row.addWidget(quit_button)
        layout.addLayout(row)
        note = QLabel("Speech is recognized on this computer. Nothing is sent anywhere. "
                      "Closing this window keeps Reverb ready in the background.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)
        self.permission_changed()

        self.pill = Pill(self.finish, self.cancel)
        self.limit = QTimer(self)
        self.limit.setSingleShot(True)
        self.limit.timeout.connect(self.finish)
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icon, self)
            menu = QMenu(self)
            menu.addAction("Start or finish dictation", self.toggle)
            menu.addAction("Show Reverb", self.present)
            menu.addSeparator()
            menu.addAction("Quit Reverb", self.quit)
            self.tray.setContextMenu(menu)
            self.tray.setToolTip("Reverb · offline dictation")
            self.tray.activated.connect(lambda reason: self.present() if reason == QSystemTrayIcon.Trigger else None)
            self.tray.show()

        self.events.toggle.connect(self.toggle)
        self.events.shortcut.connect(self.shortcut_changed)
        self.events.ready.connect(self.loaded)
        self.events.failed.connect(self.fail)
        self.events.paste.connect(self.paste)
        self.events.done.connect(self.done)
        self.events.permission.connect(self.permission_result)

        if args.smoke_ui:
            self.pill.present(LISTENING, True)
            self.status.setText("Linux UI smoke test passed")
            QTimer.singleShot(300, self.quit)
            return
        if "autostart" not in self.state and not self.desktop.niri:
            # Start at login by default so the shortcut keeps working after a restart.
            self.state["autostart"] = True
            try:
                set_autostart(True)
                save_state(self.state)
            except OSError:
                pass
        self.login.setChecked(AUTOSTART.exists())
        self.login.toggled.connect(self.login_changed)
        if args.toggle:
            self.pill.present("Starting Reverb…")
        self.pool.submit(self.load)
        self.desktop.start_shortcut(self.events.toggle.emit, self.events.shortcut.emit)
        if (self.desktop.wayland and not self.desktop.niri and not self.state.get("restore_token")
                and not args.background and not args.toggle):
            QTimer.singleShot(800, self.allow_typing)

    # Model

    def load(self):
        try:
            self.events.ready.emit(Speech())
        except Exception as error:
            self.events.failed.emit("Could not load the speech model: " + str(error), True)

    def loaded(self, engine):
        self.speech = engine
        self.reset("Ready.")
        if self.start_when_ready:
            self.start_when_ready = False
            self.start()

    # Dictation

    def toggle(self):
        if self.phase == "loading":
            self.start_when_ready = True
            self.pill.present("Starting Reverb…")
        elif self.phase == "ready":
            self.start()
        elif self.phase == "recording":
            self.finish()
        elif self.phase == "broken":
            self.present()

    def from_button(self):
        if self.phase == "recording":
            self.finish()
        elif self.phase == "ready":
            # Hide first so the app you were in gets focus back and receives the words.
            self.phase = "starting"
            self.hide()
            QTimer.singleShot(400, self.start)

    def start(self):
        if self.phase not in ("ready", "starting"):
            return
        self.destination = niri.focused_window() if self.desktop.niri else None
        try:
            self.recorder.start()
        except Exception as error:
            self.fail("Could not open the microphone: " + str(error), True)
            return
        self.phase = "recording"
        self.button.setText("Finish dictation")
        self.status.setText("Listening…")
        self.limit.start(Recorder.MAX_SECONDS * 1000)
        self.pill.present(LISTENING, True)

    def finish(self):
        if self.phase != "recording":
            return
        self.limit.stop()
        self.phase = "working"
        self.finished_at = time.monotonic()
        self.button.setEnabled(False)
        self.button.setText("Transcribing…")
        self.status.setText("Transcribing…")
        self.pill.present("Transcribing…")
        try:
            samples, rate = self.recorder.stop()
        except Exception as error:
            self.fail(str(error), False)
            return
        self.pool.submit(self.process, samples, rate)

    def cancel(self):
        if self.phase != "recording":
            return
        self.limit.stop()
        try:
            self.recorder.stop()
        except Exception:
            pass
        self.pill.hide()
        self.reset("Dictation cancelled.")

    def process(self, samples, rate):
        try:
            text = cleanup(self.speech.transcribe(samples, rate))
        except Exception as error:
            self.events.failed.emit("Could not recognize speech: " + str(error), False)
            return
        if not text:
            self.events.failed.emit("No speech was heard. Check your microphone and try again.", False)
            return
        if not self.desktop.wayland:
            try:
                self.desktop.wait_for_modifiers()
            except Exception:
                pass
            self.events.paste.emit(text)
            return
        # Ctrl+Alt from the shortcut may still be held, and typed letters would combine with it.
        time.sleep(max(0.0, 0.6 - (time.monotonic() - self.finished_at)))
        try:
            self.desktop.type_wayland(text, self.destination)
            self.events.done.emit(text, True)
        except Exception:
            self.events.done.emit(text, False)

    def paste(self, text):
        # X11 clipboard ownership lives on the GUI thread, which must keep running to serve the paste.
        self.app.clipboard().setText(text)
        try:
            self.desktop.paste_x11()
            self.done(text, True)
        except Exception:
            self.done(text, False)

    def done(self, text, typed):
        self.result.setPlainText(text)
        if typed:
            self.pill.hide()
            self.reset("Done. Press " + SHORTCUT + " to dictate again.")
        else:
            if self.desktop.niri and not niri.copy_text(text):
                self.pill.present("Text saved. Open Reverb to copy it.", seconds=4)
                self.reset("Your words are saved below. Use Copy, then paste into your app.")
                return
            if not self.desktop.niri:
                self.app.clipboard().setText(text)
            self.pill.present("Copied. Press Ctrl+V to paste.", seconds=4)
            self.reset("Copied to the clipboard. Click where it goes and press Ctrl+V.")
        self.permission_changed()

    def reset(self, message):
        self.phase = "ready"
        self.button.setEnabled(True)
        self.button.setText("Start dictation")
        self.status.setText(message)

    def fail(self, message, show):
        self.limit.stop()
        if self.speech is None:
            self.phase = "broken"
            self.status.setText(message)
        else:
            self.reset(message)
        if show:
            self.pill.hide()
            self.present()
        else:
            self.pill.present(message, seconds=4)

    # Setup

    def shortcut_changed(self, message):
        self.shortcut.setText(message)
        self.setup.setText("Copy Niri shortcut" if self.desktop.niri else "Turn on " + SHORTCUT)
        self.setup.setVisible(self.desktop.niri or (self.desktop.wayland and self.desktop.gnome
                              and not self.desktop.gnome_shortcut_installed()))

    def install_shortcut(self):
        if self.desktop.niri:
            self.app.clipboard().setText(niri.shortcut_config(toggle_command()))
            self.shortcut.setText("Copied. Add this block to your Niri config (usually "
                                  "~/.config/niri/config.kdl), then run niri validate. "
                                  "If it already has a binds block, add only the Ctrl+Alt+Space line there.")
            return
        try:
            self.desktop.install_gnome_shortcut()
            self.shortcut_changed("Press " + SHORTCUT + " in any app to start. Press it again to finish.")
        except Exception as error:
            self.shortcut.setText("Could not add the shortcut: " + str(error))

    def allow_typing(self):
        self.allow.setEnabled(False)
        self.status.setText("Choose Allow in your desktop's dialog so Reverb can type your words. "
                            "Reverb asks for the keyboard only, never your screen.")

        def ask():
            try:
                self.desktop.allow_typing()
                self.events.permission.emit(True)
            except Exception:
                self.events.permission.emit(False)
        threading.Thread(target=ask, daemon=True).start()

    def permission_result(self, granted):
        self.allow.setEnabled(True)
        self.permission_changed()
        if granted:
            self.status.setText("Reverb can type into your apps." if self.speech else "Loading the speech model…")
        else:
            self.status.setText("Typing wasn't allowed, so dictation will be copied for you to paste with Ctrl+V. "
                                "Use the Allow button to try again.")

    def permission_changed(self):
        self.allow.setVisible(self.desktop.wayland
                              and not self.desktop.niri
                              and not (self.state.get("restore_token") or self.desktop.session))

    def login_changed(self, enabled):
        try:
            set_autostart(enabled)
        except OSError as error:
            self.status.setText("Could not change login startup: " + str(error))

    # Window

    def present(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def quit(self):
        # Qt asks every window to close before quitting, so let this one close now.
        self.quitting = True
        self.app.quit()

    def closeEvent(self, event):
        if self.quitting:
            event.accept()
            return
        # Keep running so the shortcut still works; Quit stops Reverb.
        self.hide()
        event.ignore()

    def shutdown(self):
        if self.phase == "recording":
            try:
                self.recorder.stop()
            except Exception:
                pass
        self.pool.shutdown(wait=False, cancel_futures=True)


def run(args, socket_path):
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Reverb")
    app.setDesktopFileName("ai.cennix.Reverb")
    app.setQuitOnLastWindowClosed(False)
    server = QLocalServer()
    QLocalServer.removeServer(socket_path)
    if not server.listen(socket_path):
        raise RuntimeError("Reverb could not open its control socket: " + server.errorString())
    window = Window(app, args)

    def accept():
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()

            def read(connection=connection):
                command = bytes(connection.readAll()).strip()
                if command == b"toggle":
                    window.toggle()
                elif command == b"show":
                    window.present()
            connection.readyRead.connect(read)
            connection.disconnected.connect(connection.deleteLater)
            if connection.bytesAvailable():
                read()
    server.newConnection.connect(accept)
    if not (args.background or args.toggle):
        window.present()
    app.aboutToQuit.connect(window.shutdown)
    app.aboutToQuit.connect(server.close)
    return app.exec()
