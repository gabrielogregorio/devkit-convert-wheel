# Print das telas de tarefa e ajustes (rode ./verifica.sh antes: ele gera as amostras).
import sys, types, os
DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)
sys.dont_write_bytecode = True
import roda_conversor as r, conversores as c
from gi.repository import Gtk, Gdk, GLib
css = Gtk.CssProvider(); css.load_from_data(r.CSS.encode())
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
app = types.SimpleNamespace(cfg=dict(r.PADRAO, fechar_sucesso_s=0))
A = os.path.join(DIR, "tmp/verifica/amostras")
S = os.path.join(DIR, "tmp/verifica/saidas")
falso = next(a for a in c.alvos_para(A + "/falso.mp3") if a.ext == "wav")
t0 = r.TelaTarefa(app, [A + "/falso.mp3"], falso, falso.padroes(), S + "/x.wav")
GLib.timeout_add(1500, lambda: t0.exp.set_expanded(True))
png = next(a for a in c.alvos_para(A + "/foto.webp") if a.ext == "png")
r.TelaTarefa(app, [A + "/foto.webp"], png, png.padroes(), c.destino_padrao(A + "/foto.webp", png, S))
aj = r.TelaAjustes(app, [A + "/video.mp4"], next(a for a in c.alvos_para(A + "/video.mp4") if a.ext == "webm"))
def foto():
    root = Gdk.get_default_root_window(); W, H = root.get_width(), root.get_height()
    for n, t in enumerate(r.TelaTarefa.abertas):
        x, y = t.win.get_position(); w, h = t.win.get_size(); print("tarefa", n, x, y, w, h, W, H)
        Gdk.pixbuf_get_from_window(root, x, y, w, h).savev(S + f"/../tarefa{n}.png", "png", [], [])
    x, y = aj.win.get_position(); w, h = aj.win.get_size()
    Gdk.pixbuf_get_from_window(root, x, y, w, h).savev(S + "/../ajustes.png", "png", [], [])
    Gtk.main_quit()
GLib.timeout_add(2500, foto)
Gtk.main()
