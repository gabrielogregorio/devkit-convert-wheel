#!/usr/bin/env python3
"""Convert Wheel: hold a mouse button over a file and pick the format on a wheel.

- Trigger: passive grab of the button on X11 (libX11 through ctypes, no python-xlib).
  Outside Nautilus/the desktop the click is handed back (ReplayPointer), so the
  browser's "back" button keeps working.
- File under the cursor: a fake left click (XTest) selects the item and a fake Ctrl+C
  copies it; the clipboard hands back the path and is restored afterwards.
- Wheel: SVG rendered by GdkPixbuf (no cairo, which is not installed).
  Inner ring = convert right away; outer ring = open the settings.
- Conversions live in converters.py and run in a thread; each one opens a progress
  popup with loading / success / error + how to fix.
"""
import ctypes
import json
import math
import os
import subprocess
import sys
import threading
import time
import traceback
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GdkX11", "3.0")
from gi.repository import Gdk, GdkPixbuf, GdkX11, Gio, GLib, Gtk, Pango  # noqa: E402

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
except (ValueError, ImportError):
    AppIndicator = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import converters as conv  # noqa: E402
from i18n import decimal, tr, tr_noop  # noqa: E402

APP_ID = "io.github.gabrielogregorio.ConvertWheel"
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION"), encoding="utf-8") as _f:
    VERSION = _f.read().strip()
APP_NAME = tr("Convert Wheel")
CONFIG_DIR = os.path.expanduser("~/.config/devkit-convert-wheel")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LOG_PATH = os.path.expanduser("~/.cache/devkit-convert-wheel/convert-wheel.log")
ICONS_DIR = os.path.expanduser("~/.cache/devkit-convert-wheel/icons")

DEFAULTS = {
    "button": 2,               # 2 = wheel click (middle), 8/9 = side buttons
    "paused": False,
    "size": 100,               # wheel size in %
    "output_dir": "",          # empty = same folder as the file
    "settings": {},            # target.key -> options remembered for quick convert
}

FILE_MANAGERS = {"org.gnome.nautilus", "nautilus", "nemo", "caja", "thunar", "pcmanfm",
                 "pcmanfm-qt", "dolphin"}
SENTINEL = "⁣convert-wheel-waiting⁣"

CSS = """
#wheel, #task-win { background-color: transparent; }
.task { background-color: #1b1d22; color: #e8e8e8; border-radius: 10px; }
.task label { color: #e8e8e8; }
.task .title { font-weight: bold; font-size: 11pt; }
.task .icon { font-size: 18pt; }
.task .ok { color: #5fd38d; }
.task .failure { color: #ff6b6b; }
.task .reason { color: #ffb3b3; font-weight: bold; }
.task .hint-title { color: #ffd479; font-weight: bold; }
.task .hint { color: #f3f3f3; }
.task .muted { color: #9aa0a8; font-size: 9pt; }
.task textview, .task textview text { background-color: #111216; color: #c9c9c9;
  font-family: monospace; font-size: 8.5pt; }
.task progressbar trough { min-height: 8px; background-color: #2c2f36; border-radius: 4px; }
.task progressbar progress { min-height: 8px; background-color: #4fa3ff; border-radius: 4px; }
"""


def log(*parts):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 512_000:
            os.replace(LOG_PATH, LOG_PATH + ".1")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(p) for p in parts) + "\n")
    except OSError:
        pass


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else decimal(f"{n:.1f} {unit}")
        n /= 1024


# ====================================================================== X11 (ctypes)

class XButtonEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("root", ctypes.c_ulong),
                ("subwindow", ctypes.c_ulong), ("time", ctypes.c_ulong), ("x", ctypes.c_int),
                ("y", ctypes.c_int), ("x_root", ctypes.c_int), ("y_root", ctypes.c_int),
                ("state", ctypes.c_uint), ("button", ctypes.c_uint), ("same_screen", ctypes.c_int)]


class XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("xbutton", XButtonEvent), ("pad", ctypes.c_long * 24)]


class XClassHint(ctypes.Structure):
    _fields_ = [("res_name", ctypes.c_void_p), ("res_class", ctypes.c_void_p)]


class XErrorEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("display", ctypes.c_void_p), ("resourceid", ctypes.c_ulong),
                ("serial", ctypes.c_ulong), ("error_code", ctypes.c_ubyte),
                ("request_code", ctypes.c_ubyte), ("minor_code", ctypes.c_ubyte)]


ButtonPress, ButtonRelease, MotionNotify = 4, 5, 6
ButtonPressMask, ButtonReleaseMask, PointerMotionMask = 1 << 2, 1 << 3, 1 << 6
GrabModeSync, GrabModeAsync = 0, 1
AnyModifier = 1 << 15
AsyncPointer, ReplayPointer = 0, 2
XK_Control_L, XK_c = 0xFFE3, 0x0063


class X11:
    """Own connection to X: button grab, pointer, XTest."""

    def __init__(self, on_event):
        self.on_event = on_event
        self.x = ctypes.cdll.LoadLibrary("libX11.so.6")
        self.t = ctypes.cdll.LoadLibrary("libXtst.so.6")
        x = self.x
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XDefaultRootWindow.restype = ctypes.c_ulong
        x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x.XGrabButton.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int,
                                  ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong]
        x.XUngrabButton.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong]
        x.XAllowEvents.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ulong]
        x.XGrabPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_uint, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        x.XUngrabPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x.XPending.argtypes = [ctypes.c_void_p]
        x.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(XEvent)]
        x.XConnectionNumber.argtypes = [ctypes.c_void_p]
        x.XFlush.argtypes = [ctypes.c_void_p]
        x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u = ctypes.c_ulong
        i = ctypes.c_int
        x.XQueryPointer.argtypes = [ctypes.c_void_p, u, ctypes.POINTER(u), ctypes.POINTER(u), ctypes.POINTER(i),
                                    ctypes.POINTER(i), ctypes.POINTER(i), ctypes.POINTER(i),
                                    ctypes.POINTER(ctypes.c_uint)]
        x.XQueryTree.argtypes = [ctypes.c_void_p, u, ctypes.POINTER(u), ctypes.POINTER(u),
                                 ctypes.POINTER(ctypes.POINTER(u)), ctypes.POINTER(ctypes.c_uint)]
        x.XGetClassHint.argtypes = [ctypes.c_void_p, u, ctypes.POINTER(XClassHint)]
        x.XFetchName.argtypes = [ctypes.c_void_p, u, ctypes.POINTER(ctypes.c_void_p)]
        x.XGetInputFocus.argtypes = [ctypes.c_void_p, ctypes.POINTER(u), ctypes.POINTER(i)]
        x.XSetInputFocus.argtypes = [ctypes.c_void_p, u, i, u]
        x.XFree.argtypes = [ctypes.c_void_p]
        x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, u]
        self.t.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, u]
        self.t.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, u]

        self._error_cb = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(XErrorEvent))(self._error)
        x.XSetErrorHandler(self._error_cb)  # without this, a BadAccess kills the process
        self.dpy = x.XOpenDisplay(None)
        if not self.dpy:
            raise RuntimeError("could not open the X11 display")
        self.root = x.XDefaultRootWindow(self.dpy)
        self.button = None
        self.last_error = None
        self.last_client = 0
        GLib.io_add_watch(x.XConnectionNumber(self.dpy), GLib.PRIORITY_HIGH, GLib.IO_IN, self._read)
        # Safety net: any call with a reply (XQueryPointer, XSync…) can pull a ButtonPress into
        # Xlib's internal queue without the fd becoming readable again. With the synchronous grab
        # that FREEZES the mouse of the whole PC until the next event. Drain every 20 ms.
        GLib.timeout_add(20, self._read)

    def _error(self, _dpy, ev):
        e = ev.contents
        self.last_error = e.error_code
        log("X11 error", e.error_code, "request", e.request_code)
        return 0

    def grab_button(self, button):
        if self.button:
            self.x.XUngrabButton(self.dpy, self.button, AnyModifier, self.root)
        self.button = button
        self.last_error = None
        if button:
            self.x.XGrabButton(self.dpy, button, AnyModifier, self.root, False,
                               ButtonPressMask | ButtonReleaseMask, GrabModeSync, GrabModeAsync, 0, 0)
        self.x.XSync(self.dpy, False)
        return self.last_error is None  # 10 = BadAccess: another program already has the button

    def _read(self, *_):
        ev = XEvent()
        while self.x.XPending(self.dpy):
            self.x.XNextEvent(self.dpy, ctypes.byref(ev))
            if ev.type in (ButtonPress, ButtonRelease, MotionNotify):
                b = ev.xbutton
                try:
                    self.on_event(ev.type, b.button, b.x_root, b.y_root, b.subwindow)
                except Exception:
                    log("event failed:", traceback.format_exc())
                    self.x.XAllowEvents(self.dpy, AsyncPointer, 0)  # never leave the pointer frozen
                    self.release_pointer()
        return True

    # ---- grab
    def release_event(self, replay):
        """Ends the passive grab: replay=True hands the click to the window below."""
        self.x.XAllowEvents(self.dpy, ReplayPointer if replay else AsyncPointer, 0)
        if not replay:
            self.x.XUngrabPointer(self.dpy, 0)
        self.x.XFlush(self.dpy)

    def grab_pointer(self):
        mask = ButtonPressMask | ButtonReleaseMask | PointerMotionMask
        r = self.x.XGrabPointer(self.dpy, self.root, False, mask, GrabModeAsync, GrabModeAsync, 0, 0, 0)
        self.x.XFlush(self.dpy)
        return r == 0

    def release_pointer(self):
        self.x.XUngrabPointer(self.dpy, 0)
        self.x.XFlush(self.dpy)

    # ---- queries and XTest
    def pointer(self):
        r, c = ctypes.c_ulong(), ctypes.c_ulong()
        rx, ry, wx, wy = (ctypes.c_int() for _ in range(4))
        m = ctypes.c_uint()
        self.x.XQueryPointer(self.dpy, self.root, ctypes.byref(r), ctypes.byref(c), ctypes.byref(rx),
                             ctypes.byref(ry), ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(m))
        return rx.value, ry.value, c.value

    def client_info(self, w, depth=0):
        """(class, window title) of the client inside `w` (mutter frame)."""
        if not w:
            return None
        h = XClassHint()
        if self.x.XGetClassHint(self.dpy, w, ctypes.byref(h)):
            cls = ctypes.string_at(h.res_class).decode("utf-8", "replace") if h.res_class else ""
            for p in (h.res_name, h.res_class):
                if p:
                    self.x.XFree(p)
            self.last_client = w
            name = ctypes.c_void_p()
            title = ""
            if self.x.XFetchName(self.dpy, w, ctypes.byref(name)) and name.value:
                title = ctypes.string_at(name.value).decode("utf-8", "replace")
                self.x.XFree(name)
            return cls, title
        if depth >= 3:
            return None
        root, parent = ctypes.c_ulong(), ctypes.c_ulong()
        children = ctypes.POINTER(ctypes.c_ulong)()
        n = ctypes.c_uint()
        if not self.x.XQueryTree(self.dpy, w, ctypes.byref(root), ctypes.byref(parent), ctypes.byref(children),
                                 ctypes.byref(n)):
            return None
        kids = [children[i] for i in range(n.value)]
        if children:
            self.x.XFree(children)
        for k in reversed(kids):  # the last one is on top
            r = self.client_info(k, depth + 1)
            if r:
                return r
        return None

    def focused(self):
        """(class, title) of the window with keyboard focus, walking up until the client."""
        w, rev = ctypes.c_ulong(), ctypes.c_int()
        self.x.XGetInputFocus(self.dpy, ctypes.byref(w), ctypes.byref(rev))
        target = w.value
        for _ in range(6):
            if target in (0, 1, self.root):   # None / PointerRoot / root
                return None
            h = XClassHint()
            if self.x.XGetClassHint(self.dpy, target, ctypes.byref(h)):
                for p in (h.res_name, h.res_class):
                    if p:
                        self.x.XFree(p)
                return self.client_info(target)
            root, parent = ctypes.c_ulong(), ctypes.c_ulong()
            children = ctypes.POINTER(ctypes.c_ulong)()
            n = ctypes.c_uint()
            if not self.x.XQueryTree(self.dpy, target, ctypes.byref(root), ctypes.byref(parent),
                                     ctypes.byref(children), ctypes.byref(n)):
                return None
            if children:
                self.x.XFree(children)
            target = parent.value
        return None

    def focus(self, w):
        """Gives keyboard focus to the file's window: the fake click does not always do it
        (on the desktop the focus stayed in the terminal)."""
        if w:
            self.last_error = None
            self.x.XSetInputFocus(self.dpy, w, 2, 0)   # RevertToParent, CurrentTime
            self.x.XSync(self.dpy, False)

    def left_click(self):
        self.t.XTestFakeButtonEvent(self.dpy, 1, True, 0)
        self.t.XTestFakeButtonEvent(self.dpy, 1, False, 0)
        self.x.XFlush(self.dpy)

    def ctrl_c(self):
        ctrl = self.x.XKeysymToKeycode(self.dpy, XK_Control_L)
        c = self.x.XKeysymToKeycode(self.dpy, XK_c)
        for k, down in ((ctrl, True), (c, True), (c, False), (ctrl, False)):
            self.t.XTestFakeKeyEvent(self.dpy, k, down, 0)
        self.x.XFlush(self.dpy)


def is_file_manager(info):
    if not info:
        return False
    cls, title = info
    if cls.lower() in FILE_MANAGERS:
        return True
    return cls.lower() == "gjs" and title.startswith("Desktop Icons")  # desktop icons (DING)


# ====================================================================== clipboard

class Capture:
    """Selects the item under the cursor and reads its path through the clipboard.

    Fast on purpose: the old text is already cached (refreshed on every owner change),
    Ctrl+C goes out ~40 ms after the click and the answer arrives through the owner-change
    signal, without waiting for a timer. The sentinel makes sure the owner changes, so a
    stale copy is never read.
    """

    def __init__(self, x11):
        self.x11 = x11
        self.cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.atom = Gdk.Atom.intern("x-special/gnome-copied-files", False)
        self.waiting = False
        self.done = True
        self.saved = None   # clipboard text before the capture
        self.cb.connect("owner-change", self._owner_changed)
        self.cb.request_text(self._save)

    def _save(self, _cb, text):
        if not self.waiting and text is not None and text != SENTINEL:
            self.saved = text

    def _owner_changed(self, *_):
        if self.waiting and not self.done:
            self._look()
        elif not self.waiting:
            self.cb.request_text(self._save)

    def start(self, on_done):
        self.on_done = on_done
        self.done = False
        self.waiting = True
        self.previous = self.saved
        self.t0 = time.monotonic()
        self.cb.set_text(SENTINEL, -1)   # now we own it; the Ctrl+C has to change that
        self.copied = False
        GLib.timeout_add(30, self._copy)        # repeats until the focus reaches the file manager
        GLib.timeout_add(150, self._look_timer)  # safety net in case the signal fails
        GLib.timeout_add(1300, self._give_up)

    def _copy(self):
        """Ctrl+C only ONCE and only if the focus is on Nautilus/the desktop.
        It used to go to whatever window had focus: it landed in a terminal and closed it."""
        if self.done or self.copied:
            return False
        info = self.x11.focused()
        if is_file_manager(info):
            self.copied = True
            self.x11.ctrl_c()
            return False
        if time.monotonic() - self.t0 > 0.45:
            log("focus on", info, "and not on the file manager: Ctrl+C NOT sent")
            self._finish(None)
            return False
        return True

    def _look_timer(self):
        if self.done:
            return False
        self._look()
        return True

    def _look(self):
        self.cb.request_contents(self.atom, self._got_gnome)

    def _got_gnome(self, _cb, sel):
        if self.done:
            return
        data = sel.get_data() if sel else None
        if data:
            lines = data.decode("utf-8", "replace").splitlines()
            if lines and lines[0] in ("copy", "cut"):
                lines = lines[1:]
            paths = [p for p in (self._path(ln) for ln in lines) if p]
            if paths:
                return self._finish(paths)
        self.cb.request_text(self._got_text)

    def _got_text(self, _cb, text):
        if self.done or not text or text == SENTINEL:
            return
        paths = [p for p in (self._path(ln) for ln in text.splitlines() if ln.strip()) if p]
        if paths:
            self._finish(paths)

    def _give_up(self):
        self._finish(None)
        return False

    @staticmethod
    def _path(line):
        line = line.strip()
        if line.startswith("file://"):
            line = unquote(urlparse(line).path)
        return line if line.startswith("/") and os.path.exists(line) else None

    def _finish(self, paths):
        if self.done:
            return
        self.done = True
        log(f"capture in {(time.monotonic() - self.t0) * 1000:.0f} ms:", paths)
        if self.previous is not None:  # put back the text the user had copied
            self.cb.set_text(self.previous, -1)
            self.cb.store()
        self.waiting = False
        self.on_done(paths)


# ====================================================================== wheel (SVG)

def esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def clip(t, n):
    return t if len(t) <= n else t[: n - 1] + "…"


def _clamp(p):
    return 0.0 if p < 0 else 1.0 if p > 1 else p


def _ease_out_cubic(p):
    return 1 - (1 - p) ** 3


def _ease_out_back(p):
    """Overshoots a little and comes back: the "blooming"."""
    c = 1.9
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


def _ease_in_out(p):
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


class Wheel:
    """Animations (open = flower blooming; pick = petals fold into the chosen one;
    close = shrinks) are the same SVG redrawn at ~60 fps with a transform per petal."""
    R0, R1, R2, PAD = 62, 196, 252, 14
    DUR_OPEN, DUR_PICK, DUR_CLOSE = 0.15, 0.2, 0.1   # short: the user wants it snappy
    OUTSIDE = 24   # px past the outer edge that still count as the ⚙ ring

    def __init__(self, app):
        self.app = app
        w = Gtk.Window(type=Gtk.WindowType.POPUP)
        w.set_name("wheel")
        w.set_app_paintable(False)
        visual = w.get_screen().get_rgba_visual()
        if visual:
            w.set_visual(visual)
        w.set_keep_above(True)
        self.img = Gtk.Image()
        w.add(self.img)
        self.win = w
        self.state = None
        self.visible = False
        self.anim = None
        self.tick_id = None

    def prepare(self, cx, cy, scale, wx, wy):
        """Sets the wheel up without showing it: it only appears once the file format is known."""
        self.k = scale
        self.S = int(2 * (self.R2 + self.PAD) * scale)
        self.cx, self.cy = cx, cy      # X pixels, used by zone()
        self.wx, self.wy = wx, wy      # GTK logical coordinates, used by the window
        self.targets, self.files, self.msg = [], [], ""
        self.sel = (None, None)
        self.state = None
        self._stop_anim()
        self.win.hide()   # previous wheel still closing: hide it right away
        self.visible = False

    # ---- animation
    def _animate(self, kind, **extra):
        self.anim = dict(kind=kind, t0=time.monotonic(), **extra)
        if not self.tick_id:
            self.tick_id = GLib.timeout_add(15, self._tick)
        self._render()

    def _stop_anim(self):
        self.anim = None
        if self.tick_id:
            GLib.source_remove(self.tick_id)
            self.tick_id = None

    def _tick(self):
        a = self.anim
        if not a:
            self.tick_id = None
            return False
        dur = {"open": self.DUR_OPEN + a.get("delay", 0) * max(0, len(self.targets) - 1),
               "pick": self.DUR_PICK, "close": self.DUR_CLOSE}[a["kind"]]
        if time.monotonic() - a["t0"] >= dur:
            self.tick_id = None
            self.anim = None
            if a["kind"] == "open":
                self.state = None
                self._render()
            else:
                self.visible = False
                self.win.hide()
            return False
        self._render()
        return True

    def _petal(self, i, n):
        """(scale, rotation in rad, opacity) of petal i in this frame."""
        a = self.anim
        if not a:
            return 1.0, 0.0, 1.0
        t = time.monotonic() - a["t0"]
        if a["kind"] == "open":
            p = _clamp((t - i * a["delay"]) / self.DUR_OPEN)
            return 0.25 + 0.75 * _ease_out_back(p), -0.6 * (1 - _ease_out_cubic(p)), _clamp(p * 1.8)
        p = _clamp(t / (self.DUR_PICK if a["kind"] == "pick" else self.DUR_CLOSE))
        if a["kind"] == "close":
            e = p ** 3
            return 1 - 0.55 * e, 0.4 * e, 1 - e
        j = a["i"]
        if i == j:  # the chosen one pulses and fades at the end
            return 1 + 0.12 * math.sin(math.pi * _clamp(p / 0.55)), 0.0, 1 - _clamp((p - 0.72) / 0.28)
        step = 2 * math.pi / n
        delta = ((j - i) * step + math.pi) % (2 * math.pi) - math.pi   # shortest way to it
        e = _ease_in_out(p)
        return 1 - 0.6 * e, delta * e, 1 - _clamp(e * 1.25)

    def _hub(self):
        a = self.anim
        if not a:
            return 1.0, 1.0
        t = time.monotonic() - a["t0"]
        if a["kind"] == "open":
            p = _clamp(t / 0.12)
            return 0.4 + 0.6 * _ease_out_back(p), _clamp(p * 2)
        p = _clamp(t / (self.DUR_PICK if a["kind"] == "pick" else self.DUR_CLOSE))
        q = _clamp((p - 0.55) / 0.45) if a["kind"] == "pick" else p
        return 1 - 0.5 * q ** 2, 1 - q

    def show(self):
        if self.visible:
            return
        self.visible = True
        n = max(1, len(self.targets))
        self._animate("open", delay=min(0.008, 0.05 / n))
        self.win.resize(self.S, self.S)
        self.win.move(int(self.wx - self.S / 2), int(self.wy - self.S / 2))
        self.win.show_all()

    def fill(self, files, targets, msg=""):
        had = bool(self.targets)
        self.files, self.targets, self.msg = files, targets, msg
        if not self.visible:
            self.show()
        elif targets and not had:  # was showing "reading…": bloom now
            self._animate("open", delay=min(0.008, 0.05 / len(targets)))
        else:
            self._render()

    def close(self, i=None, zone=None):
        """With a pick: the petals fold into the chosen one. Without: the wheel shrinks."""
        if not self.visible:
            self._stop_anim()
            self.win.hide()
            return
        if i is not None:
            self.sel = (i, zone)
            self._animate("pick", i=i)
        else:
            self.sel = (None, None)
            self._animate("close")

    def swap(self, targets):
        """Swaps the petals (main <-> extras) blooming again."""
        self.targets = targets
        self.sel = (None, None)
        self.state = None
        self._animate("open", delay=min(0.008, 0.05 / max(1, len(targets))))

    def move(self, x, y):
        if self.anim and self.anim["kind"] != "open":
            return  # already picked/closed: the drawing no longer follows the mouse
        self.sel = self.zone(x, y)
        if self.visible:
            self._render()

    def zone(self, x, y):
        dx, dy = (x - self.cx) / self.k, (y - self.cy) / self.k
        d = math.hypot(dx, dy)
        n = len(self.targets)
        if d < self.R0 or d > self.R2 + self.OUTSIDE or not n:
            return (None, None)  # center or far from the wheel: nothing marked, release/click cancels
        step = 2 * math.pi / n
        ang = math.atan2(dx, -dy) % (2 * math.pi)
        i = int(((ang + step / 2) % (2 * math.pi)) // step) % n
        return (i, "conv" if d < self.R1 else "cfg")

    def _render(self):
        key = (self.sel, len(self.targets), self.msg, tuple(self.files))
        if key == self.state and not self.anim:
            return
        self.state = key
        svg = self.svg()
        ld = GdkPixbuf.PixbufLoader.new_with_type("svg")
        ld.write(svg.encode("utf-8"))
        ld.close()
        self.img.set_from_pixbuf(ld.get_pixbuf())

    def svg(self):
        k = self.k
        S = self.S
        c = S / 2
        R0, R1, R2 = self.R0 * k, self.R1 * k, self.R2 * k
        n = len(self.targets)
        i_sel, z_sel = self.sel
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{S}" height="{S}" '
               f'font-family="Ubuntu, Cantarell, DejaVu Sans, sans-serif">']

        def p(r, a):
            return f"{c + r * math.sin(a):.2f},{c - r * math.cos(a):.2f}"

        def sector(ri, re, a0, a1, color, border="none"):
            g = 1 if a1 - a0 > math.pi else 0
            return (f'<path d="M {p(re, a0)} A {re:.2f} {re:.2f} 0 {g} 1 {p(re, a1)} L {p(ri, a1)} '
                    f'A {ri:.2f} {ri:.2f} 0 {g} 0 {p(ri, a0)} Z" fill="{color}" stroke="{border}" stroke-width="1.5"/>')

        hub_scale, hub_opacity = self._hub()
        out.append(f'<circle cx="{c}" cy="{c}" r="{(R2 + 6 * k) * min(1, hub_scale):.1f}" '
                   f'fill="rgba(0,0,0,{0.25 * hub_opacity:.3f})"/>')
        if n:
            step = 2 * math.pi / n
            gap = min(0.02, step * 0.08)
            font = (24 if n <= 6 else 20 if n <= 9 else 16) * k
            order = [i for i in range(n) if i != i_sel] + ([i_sel] if i_sel is not None else [])
            for i in order:  # the marked one last, on top of the ones folding into it
                a = self.targets[i]
                petal_scale, rot, opacity = self._petal(i, n)
                if opacity <= 0.01:
                    continue
                out.append(f'<g opacity="{opacity:.3f}" transform="translate({c} {c}) '
                           f'rotate({math.degrees(rot):.2f}) scale({petal_scale:.4f}) translate({-c} {-c})">')
                mid = i * step
                a0, a1 = mid - step / 2 + gap, mid + step / 2 - gap
                active = i == i_sel
                menu = a.family == "menu"
                color = "rgba(245,245,245,0.94)" if active and z_sel == "conv" else \
                        "rgba(255,255,255,0.22)" if active else \
                        "rgba(60,48,20,0.85)" if menu else "rgba(14,15,18,0.80)"
                out.append(sector(R0 + 4 * k, R1, a0, a1, color))
                color_cfg = ("rgba(255,190,80,0.9)" if active else "rgba(60,48,20,0.62)") if menu else \
                            "rgba(79,163,255,0.95)" if active and z_sel == "cfg" else \
                            "rgba(79,163,255,0.35)" if active else "rgba(14,15,18,0.62)"
                out.append(sector(R1 + 4 * k, R2, a0, a1, color_cfg))
                rr = (R0 + R1) / 2 + 6 * k
                tx, ty = c + rr * math.sin(mid), c - rr * math.cos(mid)
                color_txt = "#111" if active and z_sel == "conv" else "#fff"
                out.append(f'<text x="{tx:.1f}" y="{ty:.1f}" fill="{color_txt}" font-size="{font:.1f}" '
                           f'font-weight="bold" text-anchor="middle">{esc(tr(a.label))}</text>')
                if a.sub:
                    out.append(f'<text x="{tx:.1f}" y="{ty + 16 * k:.1f}" fill="{color_txt}" opacity="0.7" '
                               f'font-size="{11 * k:.1f}" text-anchor="middle">{esc(tr(a.sub))}</text>')
                if menu:  # menu petal: the whole outer ring counts as it, no ⚙
                    out.append("</g>")
                    continue
                rg = (R1 + R2) / 2 + 2 * k
                gx, gy = c + rg * math.sin(mid), c - rg * math.cos(mid) + 5 * k
                out.append(f'<text x="{gx:.1f}" y="{gy:.1f}" fill="#fff" opacity="{1 if active else 0.55}" '
                           f'font-size="{14 * k:.1f}" text-anchor="middle">⚙</text>')
                out.append("</g>")
        else:
            out.append(f'<circle cx="{c}" cy="{c}" r="{(R1 + R0) / 2:.1f}" fill="none" '
                       f'stroke="rgba(14,15,18,0.8)" stroke-width="{R1 - R0:.1f}"/>')
        # hub
        out.append(f'<g opacity="{hub_opacity:.3f}" transform="translate({c} {c}) scale({hub_scale:.4f}) '
                   f'translate({-c} {-c})">')
        out.append(f'<circle cx="{c}" cy="{c}" r="{R0:.1f}" fill="rgba(8,8,10,0.90)" '
                   f'stroke="rgba(255,255,255,0.25)" stroke-width="1.5"/>')
        if self.files:
            f0 = self.files[0]
            name = os.path.basename(f0.rstrip("/"))
            more = f" +{len(self.files) - 1}" if len(self.files) > 1 else ""
            try:
                info = tr("folder") if os.path.isdir(f0) else human_size(os.path.getsize(f0))
            except OSError:
                info = ""
            lines = [(clip(name, 15) + more, 11.5, "#fff", "bold"), (info, 10, "#9aa0a8", "normal")]
        else:
            lines = []
        if i_sel is not None:
            a = self.targets[i_sel]
            label = tr(a.label)
            action = (label if a.family == "menu" else
                      ("→ " + label) if z_sel == "conv" else tr("⚙ adjust {label}").format(label=label))
            lines.append((action, 13, "#4fa3ff" if z_sel == "cfg" else "#5fd38d", "bold"))
        elif self.msg:
            lines.append((clip(self.msg, 18), 10.5, "#ffd479", "normal"))
        else:
            lines.append((tr("release: cancel"), 10, "#9aa0a8", "normal"))
        y0 = c - (len(lines) - 1) * 8 * k + 4 * k
        for j, (t, size, color, weight) in enumerate(lines):
            out.append(f'<text x="{c}" y="{y0 + j * 17 * k:.1f}" fill="{color}" font-size="{size * k:.1f}" '
                       f'font-weight="{weight}" text-anchor="middle">{esc(t)}</text>')
        out.append("</g></svg>")
        return "".join(out)


# ====================================================================== progress / error popup

class TaskPopup:
    """One conversion: loading → success (closes) or error + how to fix."""

    open_popups = []

    def __init__(self, app, sources, target, op, destination):
        self.app, self.sources, self.target, self.op, self.destination = app, sources, target, op, destination
        self.prog = conv.Progress(lambda f: GLib.idle_add(self._fraction, f),
                                  lambda t: GLib.idle_add(self._text, t))
        self.has_fraction = False
        self.custom_status = False   # a converter sent its own text: the % does not overwrite it
        self.close_id = None
        self.result = None

        # POPUP (override-redirect): the window manager does not see it, so GNOME does not
        # raise the "is ready" notification that an unfocused toplevel triggers.
        w = Gtk.Window(type=Gtk.WindowType.POPUP)
        w.set_name("task-win")
        visual = w.get_screen().get_rgba_visual()
        if visual:
            w.set_visual(visual)
        w.set_size_request(440, -1)
        w.connect("enter-notify-event", lambda *_: self._stop_closing())
        self._size = None
        w.connect("size-allocate", self._resized)
        self.win = w

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.get_style_context().add_class("task")
        box.set_border_width(14)
        top = Gtk.Box(spacing=10)
        self.icon = Gtk.Label(label="⏳")
        self.icon.get_style_context().add_class("icon")
        top.pack_start(self.icon, False, False, 0)
        name = os.path.basename(sources[0].rstrip("/"))
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>{GLib.markup_escape_text(conv.shorten_middle(name, 34))}</b>  →  "
                         f"<b>{GLib.markup_escape_text(tr(target.label))}</b>"
                         + (f"  <small>({GLib.markup_escape_text(tr(target.sub))})</small>" if target.sub else ""))
        title.get_style_context().add_class("title")
        title.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        top.pack_start(title, True, True, 0)
        box.pack_start(top, False, False, 0)

        self.status = Gtk.Label(label=tr("converting…"), xalign=0)
        self.status.get_style_context().add_class("muted")
        self.status.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.status.set_max_width_chars(48)
        box.pack_start(self.status, False, False, 0)
        self.bar = Gtk.ProgressBar()
        box.pack_start(self.bar, False, False, 0)

        # error block
        self.error = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.reason = Gtk.Label(xalign=0, wrap=True, max_width_chars=44, selectable=True)
        self.reason.get_style_context().add_class("reason")
        self.error.pack_start(self.reason, False, False, 0)
        ht = Gtk.Label(label=tr("How to fix"), xalign=0)
        ht.get_style_context().add_class("hint-title")
        self.error.pack_start(ht, False, False, 0)
        self.hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=44, selectable=True)
        self.hint.get_style_context().add_class("hint")
        self.error.pack_start(self.hint, False, False, 0)
        self.exp = Gtk.Expander(label=tr("Technical details"))
        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(-1, 150)
        self.details = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.CHAR)
        scroll.add(self.details)
        self.exp.add(scroll)
        self.error.pack_start(self.exp, False, False, 0)
        box.pack_start(self.error, False, False, 0)

        self.buttons = Gtk.Box(spacing=6)
        box.pack_end(self.buttons, False, False, 0)
        w.add(box)
        self._set_buttons([(tr("Cancel"), self._cancel)])
        w.show_all()
        self.error.hide()
        TaskPopup.open_popups.append(self)
        self._stack()
        self.pulse = GLib.timeout_add(120, self._pulse)
        threading.Thread(target=self._run, daemon=True).start()

    # ---- layout
    def _resized(self, _w, alloc):
        size = (alloc.width, alloc.height)
        if size != self._size:
            self._size = size
            GLib.idle_add(TaskPopup._stack)

    def _set_buttons(self, items):
        for b in self.buttons.get_children():
            self.buttons.remove(b)
        for label, cb in reversed(items):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, f=cb: f())
            self.buttons.pack_end(b, False, False, 0)
        self.buttons.show_all()

    @classmethod
    def _stack(cls):
        mon = Gdk.Display.get_default().get_primary_monitor() or Gdk.Display.get_default().get_monitor(0)
        r = mon.get_workarea()
        y = r.y + 16   # top right corner, below the GNOME bar; stacks downwards
        for t in cls.open_popups:
            w, h = t.win.get_size()
            t.win.move(r.x + r.width - w - 16, y)
            y += h + 10

    # ---- thread
    def _run(self):
        try:
            final = conv.convert(self.sources, self.target, self.op, self.destination, self.prog)
            GLib.idle_add(self._success, final)
        except conv.Cancelled:
            GLib.idle_add(self._close)
        except conv.ConversionError as e:
            log("failed", self.sources, "->", self.target.key, e.reason, e.details[-400:])
            GLib.idle_add(self._failure, e)
        except Exception as e:  # should not get here, convert() already wraps it
            GLib.idle_add(self._failure, conv.ConversionError(str(e), "", traceback.format_exc()))

    def _pulse(self):
        if self.has_fraction or self.result:
            self.pulse = None
            return False
        self.bar.pulse()
        return True

    def _fraction(self, f):
        self.has_fraction = True
        self.bar.set_fraction(f)
        if not self.custom_status:
            self.status.set_text(tr("converting… {pct}%").format(pct=f"{f * 100:.0f}"))

    def _text(self, t):
        self.custom_status = True
        self.status.set_text(t)

    # ---- end
    def _success(self, final):
        """It worked: disappears right away. Only the error stays on screen."""
        self.result = final
        log("ok", self.sources[0], "->", final)
        self._close()

    def _failure(self, e):
        self.result = e
        self.icon.set_text("✗")
        self.icon.get_style_context().add_class("failure")
        self.bar.hide()
        self.status.set_text(tr("conversion failed"))
        self.reason.set_text(e.reason)
        self.hint.set_text(e.hint or tr("Try again through ⚙ (outer ring) with other settings."))
        self.details.get_buffer().set_text(e.details or tr("(no details)"))
        self.exp.set_visible(bool(e.details))
        self.error.show_all()
        self.exp.set_visible(bool(e.details))
        self._set_buttons([(tr("Copy error"), lambda: self._copy(e)),
                           (tr("Adjust and retry"), self._adjust),
                           (tr("Close"), self._close)])
        GLib.idle_add(TaskPopup._stack)

    def _copy(self, e):
        txt = f"{self.sources[0]} -> {self.target.label}\n{e.reason}\n\n{e.hint}\n\n{e.details}"
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        cb.set_text(txt, -1)
        cb.store()
        self.status.set_text(tr("error copied to the clipboard"))

    def _adjust(self):
        self._close()
        AdjustDialog(self.app, self.sources, self.target, self.op)

    def _cancel(self):
        self.status.set_text(tr("cancelling…"))
        self.prog.cancel()

    def _stop_closing(self):
        if self.close_id:
            GLib.source_remove(self.close_id)
            self.close_id = None

    def _close(self):
        self._stop_closing()
        if self in TaskPopup.open_popups:
            TaskPopup.open_popups.remove(self)
        self.win.destroy()
        TaskPopup._stack()
        return False


def present(w):
    """Shows and focuses with the X server time: without it mutter denies the focus and
    GNOME swaps it for an "is ready" notification."""
    w.show_all()
    try:
        t = GdkX11.x11_get_server_time(w.get_window())
    except (TypeError, AttributeError):
        t = 0
    w.present_with_time(t)


def open_path(path):
    subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


# ====================================================================== per-format settings

class AdjustDialog:
    def __init__(self, app, sources, target, current_op=None):
        self.app, self.sources, self.target = app, sources, target
        op = target.defaults(app.cfg["settings"].get(target.key))
        if current_op:
            op.update(current_op)
        w = Gtk.Window(title=tr("Adjust conversion → {label}").format(label=tr(target.label)))
        w.set_keep_above(True)
        w.set_position(Gtk.WindowPosition.MOUSE)
        w.set_default_size(460, -1)
        w.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.win = w

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(16)
        head = Gtk.Label(xalign=0)
        name = os.path.basename(sources[0].rstrip("/"))
        to = tr("to {label}").format(label=f"<b>{GLib.markup_escape_text(tr(target.label))}</b>")
        head.set_markup(f"<big><b>{GLib.markup_escape_text(conv.shorten_middle(name, 40))}</b></big>\n{to}"
                        + (f" ({GLib.markup_escape_text(tr(target.sub))})" if target.sub else ""))
        box.pack_start(head, False, False, 0)

        g = Gtk.Grid(column_spacing=12, row_spacing=8)
        self.fields = {}
        row = 0
        for o in target.options:
            g.attach(Gtk.Label(label=o.label, xalign=0), 0, row, 1, 1)
            v = op.get(o.key, o.default)
            if o.kind == "choice":
                wd = Gtk.ComboBoxText()
                for val, txt in o.choices:
                    wd.append(str(val), txt)
                if not wd.set_active_id(str(v)):
                    wd.set_active(0)
            elif o.kind == "number":
                wd = Gtk.SpinButton.new_with_range(o.minimum, o.maximum, o.step)
                wd.set_value(float(v or 0))
            elif o.kind == "bool":
                wd = Gtk.Switch(active=bool(v), halign=Gtk.Align.START)
            else:
                wd = Gtk.Entry(text=str(v or ""))
            wd.set_hexpand(True)
            g.attach(wd, 1, row, 1, 1)
            self.fields[o.key] = (o, wd)
            row += 1

        destination = conv.default_destination(sources[0], target, app.cfg.get("output_dir", ""))
        g.attach(Gtk.Separator(), 0, row, 2, 1)
        row += 1
        g.attach(Gtk.Label(label=tr("File name"), xalign=0), 0, row, 1, 1)
        self.name = Gtk.Entry(text=os.path.basename(destination))
        g.attach(self.name, 1, row, 1, 1)
        row += 1
        g.attach(Gtk.Label(label=tr("Folder"), xalign=0), 0, row, 1, 1)
        self.folder = Gtk.FileChooserButton(title=tr("Output folder"), action=Gtk.FileChooserAction.SELECT_FOLDER)
        self.folder.set_filename(os.path.dirname(destination))
        g.attach(self.folder, 1, row, 1, 1)
        row += 1
        if len(sources) > 1:
            g.attach(Gtk.Label(label=tr("+{n} more file(s): same settings, automatic name").format(
                n=len(sources) - 1), xalign=0), 0, row, 2, 1)
            row += 1
        self.remember = Gtk.CheckButton(label=tr("Remember these settings for quick convert"))
        g.attach(self.remember, 0, row, 2, 1)
        box.pack_start(g, False, False, 0)
        if not target.options:
            box.pack_start(Gtk.Label(label=tr("This format has no settings; only name and folder."), xalign=0),
                           False, False, 0)

        bts = Gtk.Box(spacing=8)
        ok = Gtk.Button(label=tr("Convert"))
        ok.get_style_context().add_class("suggested-action")
        ok.connect("clicked", self._ok)
        cancel = Gtk.Button(label=tr("Cancel"))
        cancel.connect("clicked", lambda *_: w.destroy())
        bts.pack_end(ok, False, False, 0)
        bts.pack_end(cancel, False, False, 0)
        box.pack_end(bts, False, False, 0)
        w.add(box)
        w.connect("key-press-event", lambda _w, e: e.keyval == Gdk.KEY_Escape and w.destroy())
        present(w)
        ok.grab_focus()

    def _values(self):
        op = {}
        for k, (o, wd) in self.fields.items():
            if o.kind == "choice":
                op[k] = wd.get_active_id() or ""
            elif o.kind == "number":
                op[k] = int(wd.get_value()) if float(o.step).is_integer() else wd.get_value()
            elif o.kind == "bool":
                op[k] = wd.get_active()
            else:
                op[k] = wd.get_text()
        return op

    def _ok(self, *_):
        op = self._values()
        if self.remember.get_active():
            self.app.cfg["settings"][self.target.key] = op
            save_config(self.app.cfg)
        folder = self.folder.get_filename() or os.path.dirname(self.sources[0])
        name = self.name.get_text().strip() or os.path.basename(conv.default_destination(self.sources[0], self.target))
        base, ext = conv.split_ext(name)
        if ext != conv.split_ext("x." + self.target.ext)[1]:
            base = name  # the extension was removed: put the right one back
        self.win.destroy()
        TaskPopup(self.app, [self.sources[0]], self.target, op, conv.free_path(folder, base, self.target.ext))
        for s in self.sources[1:]:
            TaskPopup(self.app, [s], self.target, op, conv.default_destination(s, self.target, folder))


# ====================================================================== app settings

BUTTONS = [(8, tr("Back side button (8)")), (9, tr("Front side button (9)")), (2, tr("Middle / wheel click (2)"))]


class SettingsDialog:
    def __init__(self, app):
        self.app = app
        cfg = app.cfg
        w = Gtk.Window(title=tr("{app} - settings").format(app=APP_NAME))
        w.set_default_size(440, -1)
        w.set_position(Gtk.WindowPosition.CENTER)
        self.win = w
        g = Gtk.Grid(column_spacing=12, row_spacing=10)
        g.set_border_width(16)

        g.attach(Gtk.Label(label=tr("Mouse button"), xalign=0), 0, 0, 1, 1)
        self.button = Gtk.ComboBoxText()
        ids = [b for b, _ in BUTTONS]
        for b, txt in BUTTONS:
            self.button.append(str(b), txt)
        if cfg["button"] not in ids:
            self.button.append(str(cfg["button"]), tr("Button {n}").format(n=cfg["button"]))
        self.button.set_active_id(str(cfg["button"]))
        g.attach(self.button, 1, 0, 1, 1)

        detect = Gtk.EventBox()
        self.detect_label = Gtk.Label(label=tr("or click HERE with the button you want to use"))
        self.detect_label.set_margin_top(8)
        self.detect_label.set_margin_bottom(8)
        detect.add(self.detect_label)
        detect.connect("button-press-event", self._detect)
        frame = Gtk.Frame()
        frame.add(detect)
        g.attach(frame, 0, 1, 2, 1)

        g.attach(Gtk.Label(label=tr("Wheel size (%)"), xalign=0), 0, 2, 1, 1)
        self.size = Gtk.SpinButton.new_with_range(60, 200, 5)
        self.size.set_value(cfg["size"])
        g.attach(self.size, 1, 2, 1, 1)

        g.attach(Gtk.Label(label=tr("Fixed output folder"), xalign=0), 0, 3, 1, 1)
        folder_box = Gtk.Box(spacing=6)
        self.folder = Gtk.FileChooserButton(title=tr("Output folder"), action=Gtk.FileChooserAction.SELECT_FOLDER)
        if cfg["output_dir"]:
            self.folder.set_filename(cfg["output_dir"])
        same = Gtk.Button(label=tr("Same as the file"))
        same.connect("clicked", lambda *_: self.folder.unselect_all())
        folder_box.pack_start(self.folder, True, True, 0)
        folder_box.pack_start(same, False, False, 0)
        g.attach(folder_box, 1, 3, 1, 1)

        n = len(cfg["settings"])
        forget = Gtk.Button(label=tr("Forget remembered settings ({n})").format(n=n))
        forget.set_sensitive(n > 0)
        forget.connect("clicked", lambda b: (cfg["settings"].clear(),
                                             b.set_label(tr("Forget remembered settings ({n})").format(n=0)),
                                             b.set_sensitive(False)))
        g.attach(forget, 0, 4, 2, 1)

        hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=60)
        hint.set_markup("<small>" + GLib.markup_escape_text(tr(
            "Hold the button over a file in Nautilus or on the desktop, drag to the format and release. "
            "Inner ring: converts right away. Outer ring (⚙): opens the settings. Release in the center or "
            "far from the wheel to cancel. A quick tap on the button keeps the wheel open: pick with the "
            "left click, the right click cancels.")) + "</small>")
        g.attach(hint, 0, 5, 2, 1)

        bts = Gtk.Box(spacing=8)
        save = Gtk.Button(label=tr("Save"))
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self._save)
        bts.pack_end(save, False, False, 0)
        g.attach(bts, 0, 6, 2, 1)
        w.add(g)
        present(w)

    def _detect(self, _w, ev):
        b = ev.button
        if self.button.get_active_id() != str(b) and not self.button.set_active_id(str(b)):
            self.button.append(str(b), tr("Button {n}").format(n=b))
            self.button.set_active_id(str(b))
        self.detect_label.set_text(tr("detected: button {n}").format(n=b))
        return True

    def _save(self, *_):
        cfg = self.app.cfg
        b = int(self.button.get_active_id() or 2)
        if b in (1, 3):
            self.detect_label.set_markup("<b>" + GLib.markup_escape_text(
                tr("The left/right button cannot be the trigger.")) + "</b>")
            return
        cfg["button"] = b
        cfg["size"] = int(self.size.get_value())
        cfg["output_dir"] = self.folder.get_filename() or ""
        save_config(cfg)
        self.app.apply_button()
        self.win.destroy()


# ====================================================================== app

class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.started = False

    def do_command_line(self, cmdline):
        argv = cmdline.get_arguments()
        args = [a for a in argv[1:] if not a.startswith("--")]
        if not self.started:
            self._start()
            if "--off" in argv and not self.cfg["paused"]:
                self._set_paused(True)  # autostart: only the (gray) icon comes up, the wheel is off
        paths = [os.path.abspath(os.path.join(cmdline.get_cwd() or ".", a)) for a in args]
        paths = [p for p in paths if os.path.exists(p)]
        if paths:
            GLib.timeout_add(150, self.wheel_for, paths)
        elif "--config" in argv:
            SettingsDialog(self)
        return 0

    def _start(self):
        self.started = True
        self.hold()
        self.cfg = load_config()
        css = Gtk.CssProvider()
        css.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.x11 = X11(self._event)
        self.capture = Capture(self.x11)
        self.wheel = Wheel(self)
        self.active = False       # wheel open with the pointer grabbed
        self.click_mode = False   # wheel open waiting for a left click
        self.files = None
        self.apply_button()
        self._create_tray()
        log("started, button", self.cfg["button"])

    def apply_button(self):
        b = None if self.cfg["paused"] else self.cfg["button"]
        if not self.x11.grab_button(b):
            log("button", b, "is already grabbed by another program")
            self.warn(tr("Mouse button {n} is already grabbed by another program.").format(n=b),
                      tr("Close the program that uses this button (e.g. input-remapper, Solaar, easystroke) "
                         "or pick another button in Settings."))

    def warn(self, reason, hint):
        d = Gtk.MessageDialog(message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.OK,
                              text=reason)
        d.format_secondary_text(tr("How to fix: {hint}").format(hint=hint))
        d.set_keep_above(True)
        d.connect("response", lambda *_: d.destroy())
        present(d)

    # ---- trigger
    def _event(self, kind, button, x, y, sub):
        if kind == ButtonPress and not self.active:
            if button != self.cfg["button"]:
                return
            info = self.x11.client_info(sub)
            if not is_file_manager(info):
                self.x11.release_event(replay=True)  # not a file: the click goes on as usual
                return
            window = self.x11.last_client   # the client client_info() found
            self.x11.release_event(replay=False)
            self._open_by_button(x, y, window)
            return
        if not self.active:
            return
        if kind == MotionNotify:
            self.wheel.move(x, y)
            self._maybe_menu(x, y)
        elif kind == ButtonRelease and button == self.cfg["button"] and not self.click_mode:
            quick = time.monotonic() - self.t_opened < 0.35
            i, _ = self.wheel.zone(x, y)
            if i is None and (quick or self.files is None):
                self.click_mode = True  # quick tap: the wheel stays open
                return
            self._decide(x, y)
        elif kind == ButtonPress and button in (1, self.cfg["button"]):
            self._decide(x, y)
        elif kind == ButtonPress and button == 3:
            self._close_wheel()

    def _open_by_button(self, x, y, window=None):
        self.x11.left_click()   # selects the item under the cursor
        self.x11.focus(window)  # and makes sure the keyboard is on it before the Ctrl+C
        self._open_wheel(x, y, click_mode=False)
        self.files = None
        self.capture.start(self._captured)
        session = self.session
        # only if the capture is slow does the empty wheel show up with "reading…"
        GLib.timeout_add(300, lambda: self.active and self.session == session and not self.wheel.visible
                         and self.wheel.fill([], [], tr("reading file…")) and False)

    def _open_wheel(self, x, y, click_mode):
        mon_scale, cx, cy = self._center(x, y)
        if not self.x11.grab_pointer():
            # another active grab (e.g. a Nautilus menu closing): retry for ~1 s
            tries = [15]

            def again():
                tries[0] -= 1
                if not self.active or self.x11.grab_pointer():
                    return False
                if tries[0] <= 0:
                    log("could not grab the pointer; closing the wheel")
                    self._close_wheel()
                    return False
                return True
            GLib.timeout_add(70, again)
        self.active = True
        self.session = getattr(self, "session", 0) + 1
        session = self.session
        GLib.timeout_add_seconds(45, lambda: self.active and self.session == session and self._close_wheel())
        self.click_mode = click_mode
        self.t_opened = time.monotonic()
        self.wheel.prepare(cx, cy, self.cfg["size"] / 100, cx / mon_scale, cy / mon_scale)

    def _center(self, x, y):
        disp = Gdk.Display.get_default()
        mon = disp.get_monitor_at_point(x, y) or disp.get_monitor(0)
        # Center = where the mouse is, ALWAYS. The wheel used to be pushed to fit the monitor and
        # the cursor went with it (jumping near the edge/the seam between monitors). Near the edge
        # the wheel is cut off, but the mouse does not move.
        return mon.get_scale_factor(), int(x), int(y)

    def _captured(self, paths):
        if not self.active:
            return
        if not paths:
            self.files = []
            self.wheel.fill([], [], tr("no file here"))
            GLib.timeout_add(900, self._close_wheel)
            return
        self._show_targets(paths)

    # ---- 2nd wheel (extras)
    def _menu_target(self, more):
        if more:
            return conv.Target("more", "menu", None, label=tr_noop("+ MORE"),
                               sub=tr("{n} extras").format(n=len(self.extras)))
        return conv.Target("back", "menu", None, label=tr_noop("← BACK"), sub=tr_noop("main"))

    def _maybe_menu(self, x, y):
        """While holding the button: resting ~0.45 s on "+ MORE"/"← BACK" swaps the wheel."""
        i, _ = self.wheel.zone(x, y)
        on_menu = i is not None and self.wheel.targets[i].family == "menu"
        if not on_menu:
            if getattr(self, "_menu_id", None):
                GLib.source_remove(self._menu_id)
                self._menu_id = None
            return
        if not getattr(self, "_menu_id", None):
            def swap():
                self._menu_id = None
                px, py, _ = self.x11.pointer()
                j, _ = self.wheel.zone(px, py)
                if self.active and j == i and self.wheel.targets[i].family == "menu":
                    self._swap_wheel(self.wheel.targets[i])
                return False
            self._menu_id = GLib.timeout_add(450, swap)

    def _swap_wheel(self, menu):
        if menu.ext == "more":
            targets = self.extras + [self._menu_target(False)]
        else:
            targets = self.main + [self._menu_target(True)]
        self.wheel.swap(targets)

    def _show_targets(self, paths):
        every = conv.targets_for(paths[0])
        self.main = [a for a in every if not a.extra]
        self.extras = [a for a in every if a.extra]
        targets = self.main + ([self._menu_target(True)] if self.extras else [])
        self.files = paths
        _, ext = conv.split_ext(paths[0])
        self.wheel.fill(paths, targets, "" if targets else tr(".{ext}: no conversion").format(ext=ext or "?"))
        x, y, _ = self.x11.pointer()
        self.wheel.move(x, y)
        if not targets:
            GLib.timeout_add(1400, self._close_wheel)

    def wheel_for(self, paths):
        """Opens the wheel at the pointer for files coming from the command line/Nautilus script."""
        if self.active:
            return False
        x, y, _ = self.x11.pointer()
        self._open_wheel(x, y, click_mode=True)
        self._show_targets(paths)
        return False

    def _decide(self, x, y):
        i, z = self.wheel.zone(x, y)
        files = self.files
        if i is not None and files and self.wheel.targets[i].family == "menu":
            self.click_mode = True   # released/clicked on "+ MORE": the new wheel stays open
            self._swap_wheel(self.wheel.targets[i])
            return
        self._close_wheel(i if files else None, z)
        if i is None or not files:
            return
        target = self.wheel.targets[i]
        if z == "cfg":
            AdjustDialog(self, files, target)
            return
        op = target.defaults(self.cfg["settings"].get(target.key))
        for f in files:
            TaskPopup(self, [f], target, op, conv.default_destination(f, target, self.cfg.get("output_dir", "")))

    def _close_wheel(self, i=None, zone=None):
        self.active = False
        self.click_mode = False
        self.x11.release_pointer()   # the mouse comes back right away; the animation runs on its own
        self.wheel.close(i, zone)
        return False

    # ---- tray menu
    def _menu(self):
        m = Gtk.Menu()

        def item(label, cb):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda *_: cb())
            m.append(it)

        # first line: name + what it is + state, like every other app icon on the bar
        title = APP_NAME + " (" + tr("file converter") + ")"
        status = Gtk.MenuItem(label=(tr("{app}: off") if self.cfg["paused"] else tr("{app}: on")).format(app=title))
        status.set_sensitive(False)
        m.append(status)
        enabled = Gtk.CheckMenuItem(label=tr("On"))
        enabled.set_active(not self.cfg["paused"])
        enabled.connect("toggled", lambda w: self._set_paused(not w.get_active()))
        m.append(enabled)
        item(tr("Convert file…"), self._choose_file)
        item(tr("Settings…"), lambda: SettingsDialog(self))
        item(tr("Open log"), lambda: open_path(LOG_PATH) if os.path.exists(LOG_PATH) else None)
        # no "Quit" on purpose: the icon always stays on the bar; unchecking "On" turns it off
        m.show_all()
        return m

    def _tooltip(self):
        return tr("{app} (paused)").format(app=APP_NAME) if self.cfg["paused"] else APP_NAME

    def _set_paused(self, on):
        self.cfg["paused"] = on
        save_config(self.cfg)
        self.apply_button()
        if self.ind:
            self.ind.set_icon_full(self._icon_name(), self._tooltip())
            GLib.idle_add(self._rebuild_tray_menu)  # the "On" check and the status line follow the state
        if self.icon:
            self.icon.set_from_file(os.path.join(ICONS_DIR, self._icon_name() + ".svg"))
            self.icon.set_tooltip_text(self._tooltip())

    def _rebuild_tray_menu(self):
        self._tray_menu = self._menu()
        self.ind.set_menu(self._tray_menu)
        return False

    def _choose_file(self):
        d = Gtk.FileChooserNative(title=tr("File to convert"), action=Gtk.FileChooserAction.OPEN)
        d.set_select_multiple(True)
        if d.run() == Gtk.ResponseType.ACCEPT:
            files = d.get_filenames()
            GLib.timeout_add(250, self.wheel_for, files)
        d.destroy()

    def _icon_name(self):
        return "convert-wheel-" + ("off" if self.cfg["paused"] else "on")

    def _create_tray(self):
        self.ind = self.icon = None
        write_tray_icons()
        icon_name = self._icon_name()
        if AppIndicator:
            self.ind = AppIndicator.Indicator.new("convert-wheel", icon_name,
                                                  AppIndicator.IndicatorCategory.APPLICATION_STATUS)
            self.ind.set_icon_theme_path(ICONS_DIR)
            self.ind.set_icon_full(icon_name, self._tooltip())
            self.ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
            self._tray_menu = self._menu()
            self.ind.set_menu(self._tray_menu)
        else:
            icon = Gtk.StatusIcon.new_from_file(os.path.join(ICONS_DIR, icon_name + ".svg"))
            icon.set_tooltip_text(self._tooltip())
            icon.set_title(APP_NAME)
            icon.connect("activate", lambda *_: SettingsDialog(self))
            icon.connect("popup-menu", self._icon_menu)
            self.icon = icon

    def _icon_menu(self, icon, button, when):
        self._tray_menu = self._menu()
        self._tray_menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, when)


def tray_icon_svg(color, detail):
    """22x22 tray icon: 6-slice wheel (weapon-wheel style) with an arrow turning in the middle."""
    slices = []
    for i in range(6):
        a0, a1 = math.radians(i * 60 - 90 + 4), math.radians(i * 60 - 30 - 4)
        pts = [(11 + r * math.cos(a), 11 + r * math.sin(a)) for r, a in ((10, a0), (10, a1), (6, a1), (6, a0))]
        slices.append(
            f'<path d="M{pts[0][0]:.2f} {pts[0][1]:.2f} A10 10 0 0 1 {pts[1][0]:.2f} {pts[1][1]:.2f} '
            f'L{pts[2][0]:.2f} {pts[2][1]:.2f} A6 6 0 0 0 {pts[3][0]:.2f} {pts[3][1]:.2f} Z" '
            f'fill="{color}" opacity="{1 if i % 2 == 0 else 0.7}"/>')
    arrow = (f'<path d="M13.6 9.0 A3.3 3.3 0 1 0 14.3 12.4" fill="none" stroke="{detail}" '
             f'stroke-width="1.5" stroke-linecap="round"/>'
             f'<path d="M12.2 6.6 L16.6 8.0 L13.4 11.4 Z" fill="{detail}"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">'
            + "".join(slices) + arrow + "</svg>")


def write_tray_icons():
    """Colored = enabled, gray = paused."""
    os.makedirs(ICONS_DIR, exist_ok=True)
    for state, color, detail in (("on", "#16a085", "#f1c40f"), ("off", "#9a9a9a", "#d0d0d0")):
        with open(os.path.join(ICONS_DIR, f"convert-wheel-{state}.svg"), "w") as f:
            f.write(tray_icon_svg(color, detail))


def main():
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)  # Gtk.StatusIcon
    if "--version" in sys.argv:
        print(f"devkit-convert-wheel {VERSION}")
        return
    GLib.set_prgname("convert-wheel")
    sys.exit(App().run(sys.argv))


if __name__ == "__main__":
    main()
