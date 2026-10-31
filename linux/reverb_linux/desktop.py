"""Getting words into other apps: the global shortcut, X11 paste, and Wayland portals."""
import ast
import asyncio
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time
import uuid

from .text import save_state
from . import niri

SHORTCUT = "Ctrl+Alt+Space"
GNOME_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/reverb/"
GNOME_BINDING = "<Control><Alt>space"
PORTAL = ("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
# Terminals paste with Ctrl+Shift+V; plain Ctrl+V would send a control character.
TERMINALS = {"gnome-terminal", "gnome-terminal-server", "org.gnome.terminal", "org.gnome.console", "kgx",
             "ptyxis", "org.gnome.ptyxis", "konsole", "org.kde.konsole", "tilix", "com.gexperts.tilix",
             "terminator", "xfce4-terminal", "mate-terminal", "lxterminal", "qterminal", "kitty", "alacritty",
             "wezterm", "org.wezfurlong.wezterm", "guake", "tilda", "terminology", "deepin-terminal",
             "io.elementary.terminal", "cool-retro-term", "blackbox", "com.raggesilver.blackbox", "foot"}
MODIFIERS = ("Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R", "Super_L", "Super_R",
             "ISO_Level3_Shift")


class TypingStopped(Exception):
    """Some characters were already typed when the session ended, so they must never be retyped."""


def toggle_command():
    """The command a desktop shortcut runs to start or finish dictation."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--toggle"]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py"), "--toggle"]


def keysym(character):
    """X keysym for one character, as Wayland's RemoteDesktop portal expects."""
    if character == "\n":
        return 0xFF0D
    if character == "\t":
        return 0xFF09
    code = ord(character)
    if 0x20 <= code <= 0x7E or 0xA0 <= code <= 0xFF:
        return code
    return 0x01000000 + code


def gvariant_string(value):
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def parse_gvariant(text):
    """The simple GVariant values gsettings prints: strings and string arrays."""
    text = text.strip()
    if text.startswith("@as "):
        text = text[4:]
    return ast.literal_eval(text)


def gsettings(*args):
    return subprocess.run(["gsettings", *args], capture_output=True, text=True, check=True, timeout=5).stdout


class Desktop:
    def __init__(self, state):
        self.state = state
        self.wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))
        self.niri = self.wayland and niri.is_niri()
        desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
        self.gnome = "GNOME" in desktops
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.bus = None
        self.session = None
        self.typing_refused = False

    def run(self, coroutine, timeout=6):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout)
        except BaseException:
            future.cancel()
            raise

    # D-Bus and portal plumbing

    async def session_bus(self):
        from dbus_next.aio import MessageBus
        if self.bus is None:
            self.bus = await MessageBus().connect()
        return self.bus

    async def call(self, destination, path, interface, member, signature="", body=None):
        from dbus_next import Message, MessageType
        bus = await self.session_bus()
        reply = await asyncio.wait_for(bus.call(Message(destination=destination, path=path,
            interface=interface, member=member, signature=signature, body=body or [])), 1.5)
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(reply.error_name or "Desktop request failed")
        return reply.body

    async def portal_version(self, interface):
        try:
            return (await self.call(*PORTAL, "org.freedesktop.DBus.Properties", "Get", "ss",
                                    [interface, "version"]))[0].value
        except (RuntimeError, asyncio.TimeoutError):
            return 0

    async def portal_request(self, interface, member, signature, body):
        from dbus_next import MessageType, Variant
        bus = await self.session_bus()
        token = "reverb_" + uuid.uuid4().hex
        options = body[-1].copy()
        options["handle_token"] = Variant("s", token)
        body[-1] = options
        path = "/org/freedesktop/portal/desktop/request/" + bus.unique_name[1:].replace(".", "_") + "/" + token
        ready = self.loop.create_future()

        def response(message):
            if (message.message_type == MessageType.SIGNAL and message.path == path
                    and message.interface == "org.freedesktop.portal.Request" and message.member == "Response"):
                if not ready.done():
                    ready.set_result(message.body)
        bus.add_message_handler(response)
        rule = "type='signal',interface='org.freedesktop.portal.Request',path='" + path + "'"
        await self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "AddMatch", "s", [rule])
        try:
            returned = (await self.call(*PORTAL, interface, member, signature, body))[0]
            if returned != path:
                raise RuntimeError("Desktop portal returned an unexpected request path")
            code, result = await asyncio.wait_for(ready, 120)
            if code:
                raise RuntimeError("Desktop permission was cancelled or unavailable")
            return {key: value.value for key, value in result.items()}
        finally:
            bus.remove_message_handler(response)
            await self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RemoveMatch", "s", [rule])

    # Global shortcut

    def start_shortcut(self, callback, report):
        """Listen for Ctrl+Alt+Space. `report` receives a sentence for the window."""
        ready = "Press " + SHORTCUT + " in any app to start. Press it again to finish."
        if self.niri:
            report("Copy the Niri shortcut below into your Niri configuration, then press " + SHORTCUT + ".")
            return
        if self.wayland and self.gnome:
            # GNOME runs `reverb --toggle` from its own keyboard settings; see install_gnome_shortcut.
            if self.gnome_shortcut_installed():
                report(ready)
            else:
                report("Click Turn on " + SHORTCUT + " so the shortcut works in every app.")
            return

        def listen():
            try:
                if self.wayland:
                    self.run(self.portal_shortcut(callback), timeout=125)
                    report(ready)
                else:
                    self.grab_x11(callback, lambda: report(ready))
            except Exception:
                if self.gnome and self.gnome_shortcut_installed():
                    report(ready)
                else:
                    report(SHORTCUT + " is unavailable. In your keyboard settings, add a shortcut that runs: "
                           + shlex.join(toggle_command()))
        threading.Thread(target=listen, daemon=True).start()

    def grab_x11(self, callback, registered):
        from Xlib import X, XK, display
        connection = display.Display()
        root = connection.screen().root
        code = connection.keysym_to_keycode(XK.string_to_keysym("space"))
        mask = X.ControlMask | X.Mod1Mask
        errors = []
        # Also grab with Caps Lock and Num Lock on, which X reports as extra modifiers.
        for extra in (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask):
            root.grab_key(code, mask | extra, False, X.GrabModeAsync, X.GrabModeAsync,
                          onerror=lambda *args: errors.append(True))
        connection.sync()
        if errors:
            connection.close()
            raise RuntimeError(SHORTCUT + " is already in use")
        registered()
        pressed = False
        while True:
            event = connection.next_event()
            if event.type == X.KeyPress and not pressed:
                pressed = True
                callback()
            elif event.type == X.KeyRelease:
                # X11 autorepeat emits a matching release/press pair.
                if connection.pending_events():
                    following = connection.next_event()
                    if following.type == X.KeyPress and following.detail == event.detail and following.time == event.time:
                        continue
                pressed = False

    async def portal_shortcut(self, callback):
        from dbus_next import MessageType, Variant
        interface = "org.freedesktop.portal.GlobalShortcuts"
        created = await self.portal_request(interface, "CreateSession", "a{sv}",
                                            [{"session_handle_token": Variant("s", "reverb_" + uuid.uuid4().hex)}])
        session = created["session_handle"]
        await self.portal_request(interface, "BindShortcuts", "oa(sa{sv})sa{sv}", [session,
            [["dictate", {"description": Variant("s", "Start or finish Reverb dictation"),
                          "preferred_trigger": Variant("s", "CTRL+ALT+space")}]], "", {}])
        bus = await self.session_bus()

        def activated(message):
            if (message.message_type == MessageType.SIGNAL and message.interface == interface
                    and message.member == "Activated" and message.body[:2] == [session, "dictate"]):
                callback()
        bus.add_message_handler(activated)
        await self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "AddMatch", "s",
                        ["type='signal',interface='" + interface + "',member='Activated'"])

    def gnome_shortcut_installed(self):
        try:
            paths = parse_gvariant(gsettings("get", GNOME_KEYS, "custom-keybindings"))
            schema = GNOME_KEYS + ".custom-keybinding:" + GNOME_PATH
            return (GNOME_PATH in paths
                    and parse_gvariant(gsettings("get", schema, "binding")) == GNOME_BINDING
                    and parse_gvariant(gsettings("get", schema, "command")) == shlex.join(toggle_command()))
        except (OSError, subprocess.SubprocessError, ValueError, SyntaxError):
            return False

    def install_gnome_shortcut(self):
        """Add Ctrl+Alt+Space under GNOME Settings → Keyboard → Custom Shortcuts. Only when asked."""
        paths = list(parse_gvariant(gsettings("get", GNOME_KEYS, "custom-keybindings")))
        schema = GNOME_KEYS + ".custom-keybinding:" + GNOME_PATH
        gsettings("set", schema, "name", gvariant_string("Reverb dictation"))
        gsettings("set", schema, "command", gvariant_string(shlex.join(toggle_command())))
        gsettings("set", schema, "binding", gvariant_string(GNOME_BINDING))
        if GNOME_PATH not in paths:
            gsettings("set", GNOME_KEYS, "custom-keybindings", "[" + ", ".join(map(gvariant_string, paths + [GNOME_PATH])) + "]")

    # Typing into the focused app

    def wait_for_modifiers(self, timeout=1.5):
        """X11: never paste while Ctrl or Alt from the shortcut is still held down."""
        from Xlib import XK, display
        connection = display.Display()
        try:
            codes = {connection.keysym_to_keycode(XK.string_to_keysym(name)) for name in MODIFIERS} - {0}
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                keys = connection.query_keymap()
                if not any(keys[code // 8] & (1 << (code % 8)) for code in codes):
                    return
                time.sleep(0.03)
        finally:
            connection.close()

    def paste_x11(self):
        """Press Ctrl+V (Ctrl+Shift+V in terminals). The text must already be on the clipboard."""
        from Xlib import X, XK, display
        from Xlib.ext import xtest
        connection = display.Display()
        try:
            names = ["Control_L", "Shift_L", "v"] if self.terminal_focused(connection) else ["Control_L", "v"]
            codes = [connection.keysym_to_keycode(XK.string_to_keysym(name)) for name in names]
            for code in codes:
                xtest.fake_input(connection, X.KeyPress, code)
            for code in reversed(codes):
                xtest.fake_input(connection, X.KeyRelease, code)
            connection.sync()
        finally:
            connection.close()

    def terminal_focused(self, connection):
        from Xlib import X
        try:
            root = connection.screen().root
            active = root.get_full_property(connection.intern_atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType)
            window = connection.create_resource_object("window", active.value[0])
            return any(name.lower() in TERMINALS for name in window.get_wm_class() or ())
        except Exception:
            return False

    def type_wayland(self, text, destination=None):
        """Type through the RemoteDesktop portal. Raises if keyboard permission is unavailable."""
        if self.niri:
            niri.type_text(text, destination)
            return
        if self.typing_refused:
            raise RuntimeError("Typing permission was declined")
        try:
            self.run(self.portal_type(text), timeout=150 + len(text) * 0.05)
        except RuntimeError:
            if self.typing_refused:
                raise
            # The desktop may have ended a kept session, for example from its sharing indicator.
            # Nothing was typed yet (see TypingStopped), so start a new session and try once more.
            self.session = None
            self.run(self.portal_type(text), timeout=150 + len(text) * 0.05)

    def allow_typing(self):
        """Ask for keyboard permission now, so the first dictation doesn't pause for the dialog."""
        self.typing_refused = False
        self.run(self.keyboard_session(close_if_restorable=True), timeout=130)

    async def keyboard_session(self, close_if_restorable=False):
        from dbus_next import Variant
        if self.session:
            return self.session, False
        interface = "org.freedesktop.portal.RemoteDesktop"
        created = await self.portal_request(interface, "CreateSession", "a{sv}",
                                            [{"session_handle_token": Variant("s", "reverb_" + uuid.uuid4().hex)}])
        session = created["session_handle"]
        try:
            options = {"types": Variant("u", 1)}  # Keyboard only. No pointer, no screen.
            if await self.portal_version(interface) >= 2:
                # Remember the approval so later dictations don't ask again.
                options["persist_mode"] = Variant("u", 2)
                if self.state.get("restore_token"):
                    options["restore_token"] = Variant("s", self.state["restore_token"])
            await self.portal_request(interface, "SelectDevices", "oa{sv}", [session, options])
            result = await self.portal_request(interface, "Start", "osa{sv}", [session, "", {}])
            if not result.get("devices", 0) & 1:
                raise RuntimeError("Keyboard permission was not granted")
        except BaseException:
            self.typing_refused = True
            await self.close_session(session)
            raise
        restorable = bool(result.get("restore_token"))
        if restorable:
            self.state["restore_token"] = result["restore_token"]
            save_state(self.state)
        if restorable and close_if_restorable:
            await self.close_session(session)
            return None, True
        if not restorable:
            # Without a restore token the desktop would ask every time, so keep this session open.
            self.session = session
        return session, restorable

    async def close_session(self, session):
        try:
            await self.call(PORTAL[0], session, "org.freedesktop.portal.Session", "Close")
        except (RuntimeError, asyncio.TimeoutError):
            pass

    async def portal_type(self, text):
        session, temporary = await self.keyboard_session()

        async def key(symbol, state):
            await self.call(*PORTAL, "org.freedesktop.portal.RemoteDesktop", "NotifyKeyboardKeysym", "oa{sv}iu",
                            [session, {}, symbol, state])
        typed = 0
        try:
            for character in text:
                symbol = keysym(character)
                await key(symbol, 1)
                typed += 1
                try:
                    await asyncio.sleep(0.002)
                finally:
                    await key(symbol, 0)
                await asyncio.sleep(0.003)
        except (RuntimeError, asyncio.TimeoutError) as error:
            if typed:
                raise TypingStopped("Typing stopped partway") from error
            raise
        finally:
            if temporary:
                # Hold keyboard access only while typing; the restore token reopens it silently.
                await self.close_session(session)
