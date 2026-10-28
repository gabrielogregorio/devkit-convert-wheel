# Screenshots of the task popups and the settings dialog (run ./check.sh first: it creates the samples).
import os
import sys
import types

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)
sys.dont_write_bytecode = True
import convert_wheel as w, converters as c  # noqa: E402
from gi.repository import Gtk, Gdk, GLib  # noqa: E402

css = Gtk.CssProvider(); css.load_from_data(w.CSS.encode())
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
app = types.SimpleNamespace(cfg=dict(w.DEFAULTS, settings={}))
A = os.path.join(DIR, "tmp/check/samples")
S = os.path.join(DIR, "tmp/check/outputs")
fake = next(a for a in c.targets_for(A + "/fake.mp3") if a.ext == "wav")
t0 = w.TaskPopup(app, [A + "/fake.mp3"], fake, fake.defaults(), S + "/x.wav")
GLib.timeout_add(1500, lambda: t0.exp.set_expanded(True))
png = next(a for a in c.targets_for(A + "/photo.webp") if a.ext == "png")
w.TaskPopup(app, [A + "/photo.webp"], png, png.defaults(), c.default_destination(A + "/photo.webp", png, S))
adj = w.AdjustDialog(app, [A + "/video.mp4"], next(a for a in c.targets_for(A + "/video.mp4") if a.ext == "webm"))


def shoot():
    root = Gdk.get_default_root_window()
    W, H = root.get_width(), root.get_height()
    for n, t in enumerate(w.TaskPopup.open_popups):
        x, y = t.win.get_position(); ww, hh = t.win.get_size(); print("task", n, x, y, ww, hh, W, H)
        Gdk.pixbuf_get_from_window(root, x, y, ww, hh).savev(S + f"/../task{n}.png", "png", [], [])
    x, y = adj.win.get_position(); ww, hh = adj.win.get_size()
    Gdk.pixbuf_get_from_window(root, x, y, ww, hh).savev(S + "/../adjust.png", "png", [], [])
    Gtk.main_quit()


GLib.timeout_add(2500, shoot)
Gtk.main()
