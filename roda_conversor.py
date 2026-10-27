#!/usr/bin/env python3
"""Roda Conversora: segure o botão lateral do mouse sobre um arquivo e escolha o formato.

- Gatilho: grab passivo do botão no X11 (libX11 por ctypes, sem python-xlib).
  Fora do Nautilus/Área de trabalho o clique é devolvido (ReplayPointer), então o
  "voltar" do navegador continua funcionando.
- Arquivo sob o cursor: clique esquerdo falso (XTest) seleciona o item e Ctrl+C
  falso copia; a área de transferência devolve o caminho e depois é restaurada.
- Roda: SVG renderizado pelo GdkPixbuf (sem cairo, que não está instalado).
  Anel interno = converter direto; anel externo = abrir os ajustes.
- Conversões em conversores.py, em thread; cada uma abre a tela de progresso com
  carregando / sucesso / erro + como resolver.
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
import conversores as conv  # noqa: E402

APP_ID = "br.local.RodaConversora"
CONFIG_DIR = os.path.expanduser("~/.config/roda-conversor")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LOG_PATH = os.path.expanduser("~/.cache/roda-conversor/roda.log")

PADRAO = {
    "botao": 2,                # 2 = clique da rodinha (padrão desde 2026-10-26), 8/9 = laterais
    "pausado": False,
    "tamanho": 100,            # % do tamanho da roda
    "pasta_saida": "",         # vazio = mesma pasta do arquivo
    "ajustes": {},             # alvo.chave -> opções lembradas para o converter rápido
}

GERENCIADORES = {"org.gnome.nautilus", "nautilus", "nemo", "caja", "thunar", "pcmanfm",
                 "pcmanfm-qt", "dolphin"}
SENTINELA = "⁣roda-conversor-esperando⁣"

CSS = """
#roda, #tarefa-win { background-color: transparent; }
.tarefa { background-color: #1b1d22; color: #e8e8e8; border-radius: 10px; }
.tarefa label { color: #e8e8e8; }
.tarefa .titulo { font-weight: bold; font-size: 11pt; }
.tarefa .icone { font-size: 18pt; }
.tarefa .ok { color: #5fd38d; }
.tarefa .falha { color: #ff6b6b; }
.tarefa .motivo { color: #ffb3b3; font-weight: bold; }
.tarefa .sugestao-titulo { color: #ffd479; font-weight: bold; }
.tarefa .sugestao { color: #f3f3f3; }
.tarefa .discreto { color: #9aa0a8; font-size: 9pt; }
.tarefa textview, .tarefa textview text { background-color: #111216; color: #c9c9c9;
  font-family: monospace; font-size: 8.5pt; }
.tarefa progressbar trough { min-height: 8px; background-color: #2c2f36; border-radius: 4px; }
.tarefa progressbar progress { min-height: 8px; background-color: #4fa3ff; border-radius: 4px; }
"""


def log(*partes):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 512_000:
            os.replace(LOG_PATH, LOG_PATH + ".1")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(p) for p in partes) + "\n")
    except OSError:
        pass


def carregar_config():
    cfg = dict(PADRAO)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def salvar_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def tamanho_legivel(n):
    for un in ("B", "KB", "MB", "GB"):
        if n < 1024 or un == "GB":
            return f"{n:.0f} {un}" if un == "B" else f"{n:.1f} {un}".replace(".", ",")
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
    """Conexão própria com o X: grab do botão, ponteiro, XTest."""

    def __init__(self, ao_evento):
        self.ao_evento = ao_evento
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
        x.XWarpPointer.argtypes = [ctypes.c_void_p, u, u, i, i, ctypes.c_uint, ctypes.c_uint, i, i]
        x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, u]
        self.t.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, u]
        self.t.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, u]

        self._erro_cb = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(XErrorEvent))(self._erro)
        x.XSetErrorHandler(self._erro_cb)  # sem isso, um BadAccess derruba o processo
        self.dpy = x.XOpenDisplay(None)
        if not self.dpy:
            raise RuntimeError("não consegui abrir o display X11")
        self.root = x.XDefaultRootWindow(self.dpy)
        self.botao = None
        self.ultimo_erro = None
        self.ultimo_cliente = 0
        GLib.io_add_watch(x.XConnectionNumber(self.dpy), GLib.PRIORITY_HIGH, GLib.IO_IN, self._ler)
        # Rede de segurança: toda chamada com resposta (XQueryPointer, XSync…) pode puxar um
        # ButtonPress pra fila interna da Xlib sem o fd ficar legível de novo. Com o grab
        # síncrono isso CONGELA o mouse do PC inteiro até o próximo evento. Drena a cada 20 ms.
        GLib.timeout_add(20, self._ler)

    def _erro(self, _dpy, ev):
        e = ev.contents
        self.ultimo_erro = e.error_code
        log("erro X11", e.error_code, "request", e.request_code)
        return 0

    def capturar_botao(self, botao):
        if self.botao:
            self.x.XUngrabButton(self.dpy, self.botao, AnyModifier, self.root)
        self.botao = botao
        self.ultimo_erro = None
        if botao:
            self.x.XGrabButton(self.dpy, botao, AnyModifier, self.root, False,
                               ButtonPressMask | ButtonReleaseMask, GrabModeSync, GrabModeAsync, 0, 0)
        self.x.XSync(self.dpy, False)
        return self.ultimo_erro is None  # 10 = BadAccess: outro programa já pegou o botão

    def _ler(self, *_):
        ev = XEvent()
        while self.x.XPending(self.dpy):
            self.x.XNextEvent(self.dpy, ctypes.byref(ev))
            if ev.type in (ButtonPress, ButtonRelease, MotionNotify):
                b = ev.xbutton
                try:
                    self.ao_evento(ev.type, b.button, b.x_root, b.y_root, b.subwindow)
                except Exception:
                    log("falha no evento:", traceback.format_exc())
                    self.x.XAllowEvents(self.dpy, AsyncPointer, 0)  # nunca deixar o ponteiro congelado
                    self.liberar_ponteiro()
        return True

    # ---- grab
    def soltar_evento(self, repassar):
        """Fecha o grab passivo: repassar=True devolve o clique à janela de baixo."""
        self.x.XAllowEvents(self.dpy, ReplayPointer if repassar else AsyncPointer, 0)
        if not repassar:
            self.x.XUngrabPointer(self.dpy, 0)
        self.x.XFlush(self.dpy)

    def pegar_ponteiro(self):
        mask = ButtonPressMask | ButtonReleaseMask | PointerMotionMask
        r = self.x.XGrabPointer(self.dpy, self.root, False, mask, GrabModeAsync, GrabModeAsync, 0, 0, 0)
        self.x.XFlush(self.dpy)
        return r == 0

    def liberar_ponteiro(self):
        self.x.XUngrabPointer(self.dpy, 0)
        self.x.XFlush(self.dpy)

    # ---- consultas e XTest
    def ponteiro(self):
        r, c = ctypes.c_ulong(), ctypes.c_ulong()
        rx, ry, wx, wy = (ctypes.c_int() for _ in range(4))
        m = ctypes.c_uint()
        self.x.XQueryPointer(self.dpy, self.root, ctypes.byref(r), ctypes.byref(c), ctypes.byref(rx),
                             ctypes.byref(ry), ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(m))
        return rx.value, ry.value, c.value

    def classe(self, w, prof=0):
        """(classe, nome da janela) do cliente dentro de `w` (frame do mutter)."""
        if not w:
            return None
        h = XClassHint()
        if self.x.XGetClassHint(self.dpy, w, ctypes.byref(h)):
            cls = ctypes.string_at(h.res_class).decode("utf-8", "replace") if h.res_class else ""
            for p in (h.res_name, h.res_class):
                if p:
                    self.x.XFree(p)
            self.ultimo_cliente = w
            nome = ctypes.c_void_p()
            titulo = ""
            if self.x.XFetchName(self.dpy, w, ctypes.byref(nome)) and nome.value:
                titulo = ctypes.string_at(nome.value).decode("utf-8", "replace")
                self.x.XFree(nome)
            return cls, titulo
        if prof >= 3:
            return None
        raiz, pai = ctypes.c_ulong(), ctypes.c_ulong()
        filhos = ctypes.POINTER(ctypes.c_ulong)()
        n = ctypes.c_uint()
        if not self.x.XQueryTree(self.dpy, w, ctypes.byref(raiz), ctypes.byref(pai), ctypes.byref(filhos),
                                 ctypes.byref(n)):
            return None
        lista = [filhos[i] for i in range(n.value)]
        if filhos:
            self.x.XFree(filhos)
        for f in reversed(lista):  # o último é o de cima
            r = self.classe(f, prof + 1)
            if r:
                return r
        return None

    def foco(self):
        """(classe, título) da janela com o foco do teclado, subindo até achar o cliente."""
        w, rev = ctypes.c_ulong(), ctypes.c_int()
        self.x.XGetInputFocus(self.dpy, ctypes.byref(w), ctypes.byref(rev))
        alvo = w.value
        for _ in range(6):
            if alvo in (0, 1, self.root):   # None / PointerRoot / root
                return None
            h = XClassHint()
            if self.x.XGetClassHint(self.dpy, alvo, ctypes.byref(h)):
                for p in (h.res_name, h.res_class):
                    if p:
                        self.x.XFree(p)
                return self.classe(alvo)
            raiz, pai = ctypes.c_ulong(), ctypes.c_ulong()
            filhos = ctypes.POINTER(ctypes.c_ulong)()
            n = ctypes.c_uint()
            if not self.x.XQueryTree(self.dpy, alvo, ctypes.byref(raiz), ctypes.byref(pai),
                                     ctypes.byref(filhos), ctypes.byref(n)):
                return None
            if filhos:
                self.x.XFree(filhos)
            alvo = pai.value
        return None

    def mover(self, x, y):
        self.x.XWarpPointer(self.dpy, 0, self.root, 0, 0, 0, 0, int(x), int(y))
        self.x.XFlush(self.dpy)

    def focar(self, w):
        """Põe o foco do teclado na janela do arquivo: o clique falso nem sempre leva
        (na área de trabalho o foco ficava no terminal)."""
        if w:
            self.ultimo_erro = None
            self.x.XSetInputFocus(self.dpy, w, 2, 0)   # RevertToParent, CurrentTime
            self.x.XSync(self.dpy, False)

    def clique_esquerdo(self):
        self.t.XTestFakeButtonEvent(self.dpy, 1, True, 0)
        self.t.XTestFakeButtonEvent(self.dpy, 1, False, 0)
        self.x.XFlush(self.dpy)

    def ctrl_c(self):
        ctrl = self.x.XKeysymToKeycode(self.dpy, XK_Control_L)
        c = self.x.XKeysymToKeycode(self.dpy, XK_c)
        for k, desce in ((ctrl, True), (c, True), (c, False), (ctrl, False)):
            self.t.XTestFakeKeyEvent(self.dpy, k, desce, 0)
        self.x.XFlush(self.dpy)


def e_gerenciador(info):
    if not info:
        return False
    cls, titulo = info
    if cls.lower() in GERENCIADORES:
        return True
    return cls.lower() == "gjs" and titulo.startswith("Desktop Icons")  # ícones da área de trabalho (DING)


# ====================================================================== área de transferência

class Captura:
    """Seleciona o item sob o cursor e lê o caminho pela área de transferência.

    Rápido de propósito: o texto antigo já fica guardado (atualizado a cada troca de dono),
    o Ctrl+C sai ~40 ms depois do clique e a resposta chega pelo sinal owner-change, sem
    esperar timer. A sentinela garante que o dono mude, então nunca se lê cópia velha.
    """

    def __init__(self, x11):
        self.x11 = x11
        self.cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.atom = Gdk.Atom.intern("x-special/gnome-copied-files", False)
        self.esperando = False
        self.feito = True
        self.guardado = None   # texto da área de transferência antes da captura
        self.cb.connect("owner-change", self._dono_mudou)
        self.cb.request_text(self._guardar)

    def _guardar(self, _cb, texto):
        if not self.esperando and texto is not None and texto != SENTINELA:
            self.guardado = texto

    def _dono_mudou(self, *_):
        if self.esperando and not self.feito:
            self._olhar()
        elif not self.esperando:
            self.cb.request_text(self._guardar)

    def iniciar(self, ao_fim):
        self.ao_fim = ao_fim
        self.feito = False
        self.esperando = True
        self.antigo = self.guardado
        self.t0 = time.monotonic()
        self.cb.set_text(SENTINELA, -1)   # agora o dono somos nós; o Ctrl+C tem que trocar
        self.copiou = False
        GLib.timeout_add(30, self._copiar)   # repete até o foco chegar no gerenciador
        GLib.timeout_add(150, self._olhar_timer)      # rede de segurança se o sinal falhar
        GLib.timeout_add(1300, self._desistir)

    def _copiar(self):
        """Ctrl+C só UMA vez e só se o foco estiver no Nautilus/área de trabalho.
        Antes ia pra qualquer janela focada: caiu no terminal e fechou o Claude Code."""
        if self.feito or self.copiou:
            return False
        info = self.x11.foco()
        if e_gerenciador(info):
            self.copiou = True
            self.x11.ctrl_c()
            return False
        if time.monotonic() - self.t0 > 0.45:
            log("foco em", info, "e não no gerenciador de arquivos: Ctrl+C NÃO enviado")
            self._terminar(None)
            return False
        return True

    def _olhar_timer(self):
        if self.feito:
            return False
        self._olhar()
        return True

    def _olhar(self):
        self.cb.request_contents(self.atom, self._chegou_gnome)

    def _chegou_gnome(self, _cb, sel):
        if self.feito:
            return
        dados = sel.get_data() if sel else None
        if dados:
            linhas = dados.decode("utf-8", "replace").splitlines()
            if linhas and linhas[0] in ("copy", "cut"):
                linhas = linhas[1:]
            caminhos = [c for c in (self._caminho(l) for l in linhas) if c]
            if caminhos:
                return self._terminar(caminhos)
        self.cb.request_text(self._chegou_texto)

    def _chegou_texto(self, _cb, texto):
        if self.feito or not texto or texto == SENTINELA:
            return
        caminhos = [c for c in (self._caminho(l) for l in texto.splitlines() if l.strip()) if c]
        if caminhos:
            self._terminar(caminhos)

    def _desistir(self):
        self._terminar(None)
        return False

    @staticmethod
    def _caminho(linha):
        linha = linha.strip()
        if linha.startswith("file://"):
            linha = unquote(urlparse(linha).path)
        return linha if linha.startswith("/") and os.path.exists(linha) else None

    def _terminar(self, caminhos):
        if self.feito:
            return
        self.feito = True
        log(f"captura em {(time.monotonic() - self.t0) * 1000:.0f} ms:", caminhos)
        if self.antigo is not None:  # devolve o texto que o usuário tinha copiado
            self.cb.set_text(self.antigo, -1)
            self.cb.store()
        self.esperando = False
        self.ao_fim(caminhos)


# ====================================================================== roda (SVG)

def esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def cortar(t, n):
    return t if len(t) <= n else t[: n - 1] + "…"


def _lim(p):
    return 0.0 if p < 0 else 1.0 if p > 1 else p


def _sai_cubica(p):
    return 1 - (1 - p) ** 3


def _sai_volta(p):
    """Passa um pouco do ponto e volta: o "desabrochar"."""
    c = 1.9
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


def _entra_sai(p):
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


class Roda:
    """Animações (abrir = flor desabrochando; escolher = pétalas se fecham na escolhida;
    fechar = recolhe) são o mesmo SVG redesenhado a ~60 fps com transform por pétala."""
    R0, R1, R2, PAD = 62, 196, 252, 14
    DUR_ABRIR, DUR_ESCOLHER, DUR_FECHAR = 0.15, 0.2, 0.1   # curto: ele quer agilidade
    FORA = 24   # px além da borda externa que ainda contam como anel ⚙

    def __init__(self, app):
        self.app = app
        w = Gtk.Window(type=Gtk.WindowType.POPUP)
        w.set_name("roda")
        w.set_app_paintable(False)
        visual = w.get_screen().get_rgba_visual()
        if visual:
            w.set_visual(visual)
        w.set_keep_above(True)
        self.img = Gtk.Image()
        w.add(self.img)
        self.win = w
        self.estado = None
        self.visivel = False
        self.anim = None
        self.tick_id = None

    def preparar(self, cx, cy, escala, wx, wy):
        """Arma a roda sem mostrar: ela só aparece quando o formato do arquivo é conhecido."""
        self.k = escala
        self.S = int(2 * (self.R2 + self.PAD) * escala)
        self.cx, self.cy = cx, cy      # pixels do X, usados por zona()
        self.wx, self.wy = wx, wy      # coordenadas lógicas do GTK, usadas pela janela
        self.alvos, self.arquivos, self.msg = [], [], ""
        self.sel = (None, None)
        self.estado = None
        self._parar_anim()
        self.win.hide()   # roda anterior ainda se fechando: some na hora
        self.visivel = False

    # ---- animação
    def _animar(self, tipo, **extra):
        self.anim = dict(tipo=tipo, t0=time.monotonic(), **extra)
        if not self.tick_id:
            self.tick_id = GLib.timeout_add(15, self._tick)
        self._render()

    def _parar_anim(self):
        self.anim = None
        if self.tick_id:
            GLib.source_remove(self.tick_id)
            self.tick_id = None

    def _tick(self):
        a = self.anim
        if not a:
            self.tick_id = None
            return False
        dur = {"abrir": self.DUR_ABRIR + a.get("atraso", 0) * max(0, len(self.alvos) - 1),
               "escolher": self.DUR_ESCOLHER, "fechar": self.DUR_FECHAR}[a["tipo"]]
        if time.monotonic() - a["t0"] >= dur:
            self.tick_id = None
            self.anim = None
            if a["tipo"] == "abrir":
                self.estado = None
                self._render()
            else:
                self.visivel = False
                self.win.hide()
            return False
        self._render()
        return True

    def _petala(self, i, n):
        """(escala, giro em rad, opacidade) da pétala i neste quadro."""
        a = self.anim
        if not a:
            return 1.0, 0.0, 1.0
        t = time.monotonic() - a["t0"]
        if a["tipo"] == "abrir":
            p = _lim((t - i * a["atraso"]) / self.DUR_ABRIR)
            return 0.25 + 0.75 * _sai_volta(p), -0.6 * (1 - _sai_cubica(p)), _lim(p * 1.8)
        p = _lim(t / (self.DUR_ESCOLHER if a["tipo"] == "escolher" else self.DUR_FECHAR))
        if a["tipo"] == "fechar":
            e = p ** 3
            return 1 - 0.55 * e, 0.4 * e, 1 - e
        j = a["i"]
        if i == j:  # a escolhida dá um pulso e some no fim
            return 1 + 0.12 * math.sin(math.pi * _lim(p / 0.55)), 0.0, 1 - _lim((p - 0.72) / 0.28)
        passo = 2 * math.pi / n
        delta = ((j - i) * passo + math.pi) % (2 * math.pi) - math.pi   # caminho mais curto até ela
        e = _entra_sai(p)
        return 1 - 0.6 * e, delta * e, 1 - _lim(e * 1.25)

    def _miolo(self):
        a = self.anim
        if not a:
            return 1.0, 1.0
        t = time.monotonic() - a["t0"]
        if a["tipo"] == "abrir":
            p = _lim(t / 0.12)
            return 0.4 + 0.6 * _sai_volta(p), _lim(p * 2)
        p = _lim(t / (self.DUR_ESCOLHER if a["tipo"] == "escolher" else self.DUR_FECHAR))
        q = _lim((p - 0.55) / 0.45) if a["tipo"] == "escolher" else p
        return 1 - 0.5 * q ** 2, 1 - q

    def mostrar(self):
        if self.visivel:
            return
        self.visivel = True
        n = max(1, len(self.alvos))
        self._animar("abrir", atraso=min(0.008, 0.05 / n))
        self.win.resize(self.S, self.S)
        self.win.move(int(self.wx - self.S / 2), int(self.wy - self.S / 2))
        self.win.show_all()

    def preencher(self, arquivos, alvos, msg=""):
        tinha = bool(self.alvos)
        self.arquivos, self.alvos, self.msg = arquivos, alvos, msg
        if not self.visivel:
            self.mostrar()
        elif alvos and not tinha:  # estava em "lendo…": desabrocha agora
            self._animar("abrir", atraso=min(0.008, 0.05 / len(alvos)))
        else:
            self._render()

    def fechar(self, i=None, zona=None):
        """Com escolha: as pétalas se fecham na escolhida. Sem: a roda recolhe."""
        if not self.visivel:
            self._parar_anim()
            self.win.hide()
            return
        if i is not None:
            self.sel = (i, zona)
            self._animar("escolher", i=i)
        else:
            self.sel = (None, None)
            self._animar("fechar")

    def trocar(self, alvos):
        """Troca as pétalas (principais <-> extras) desabrochando de novo."""
        self.alvos = alvos
        self.sel = (None, None)
        self.estado = None
        self._animar("abrir", atraso=min(0.008, 0.05 / max(1, len(alvos))))

    def mover(self, x, y):
        if self.anim and self.anim["tipo"] != "abrir":
            return  # já escolheu/fechou: o desenho não segue mais o mouse
        self.sel = self.zona(x, y)
        if self.visivel:
            self._render()

    def zona(self, x, y):
        dx, dy = (x - self.cx) / self.k, (y - self.cy) / self.k
        d = math.hypot(dx, dy)
        n = len(self.alvos)
        if d < self.R0 or d > self.R2 + self.FORA or not n:
            return (None, None)  # centro ou longe da roda: nada marcado, soltar/clicar cancela
        passo = 2 * math.pi / n
        ang = math.atan2(dx, -dy) % (2 * math.pi)
        i = int(((ang + passo / 2) % (2 * math.pi)) // passo) % n
        return (i, "conv" if d < self.R1 else "cfg")

    def _render(self):
        chave = (self.sel, len(self.alvos), self.msg, tuple(self.arquivos))
        if chave == self.estado and not self.anim:
            return
        self.estado = chave
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
        n = len(self.alvos)
        i_sel, z_sel = self.sel
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{S}" height="{S}" '
               f'font-family="Ubuntu, Cantarell, DejaVu Sans, sans-serif">']

        def p(r, a):
            return f"{c + r * math.sin(a):.2f},{c - r * math.cos(a):.2f}"

        def setor(ri, re, a0, a1, cor, borda="none"):
            g = 1 if a1 - a0 > math.pi else 0
            return (f'<path d="M {p(re, a0)} A {re:.2f} {re:.2f} 0 {g} 1 {p(re, a1)} L {p(ri, a1)} '
                    f'A {ri:.2f} {ri:.2f} 0 {g} 0 {p(ri, a0)} Z" fill="{cor}" stroke="{borda}" stroke-width="1.5"/>')

        esc_m, opac_m = self._miolo()
        out.append(f'<circle cx="{c}" cy="{c}" r="{(R2 + 6 * k) * min(1, esc_m):.1f}" '
                   f'fill="rgba(0,0,0,{0.25 * opac_m:.3f})"/>')
        if n:
            passo = 2 * math.pi / n
            folga = min(0.02, passo * 0.08)
            fonte = (24 if n <= 6 else 20 if n <= 9 else 16) * k
            ordem = [i for i in range(n) if i != i_sel] + ([i_sel] if i_sel is not None else [])
            for i in ordem:  # a marcada por último, por cima das que se fecham nela
                a = self.alvos[i]
                esc_p, giro, opac = self._petala(i, n)
                if opac <= 0.01:
                    continue
                out.append(f'<g opacity="{opac:.3f}" transform="translate({c} {c}) '
                           f'rotate({math.degrees(giro):.2f}) scale({esc_p:.4f}) translate({-c} {-c})">')
                meio = i * passo
                a0, a1 = meio - passo / 2 + folga, meio + passo / 2 - folga
                ativo = i == i_sel
                menu = a.familia == "menu"
                cor = "rgba(245,245,245,0.94)" if ativo and z_sel == "conv" else \
                      "rgba(255,255,255,0.22)" if ativo else \
                      "rgba(60,48,20,0.85)" if menu else "rgba(14,15,18,0.80)"
                out.append(setor(R0 + 4 * k, R1, a0, a1, cor))
                cor_cfg = ("rgba(255,190,80,0.9)" if ativo else "rgba(60,48,20,0.62)") if menu else \
                          "rgba(79,163,255,0.95)" if ativo and z_sel == "cfg" else \
                          "rgba(79,163,255,0.35)" if ativo else "rgba(14,15,18,0.62)"
                out.append(setor(R1 + 4 * k, R2, a0, a1, cor_cfg))
                rr = (R0 + R1) / 2 + 6 * k
                tx, ty = c + rr * math.sin(meio), c - rr * math.cos(meio)
                cor_txt = "#111" if ativo and z_sel == "conv" else "#fff"
                out.append(f'<text x="{tx:.1f}" y="{ty:.1f}" fill="{cor_txt}" font-size="{fonte:.1f}" '
                           f'font-weight="bold" text-anchor="middle">{esc(a.rotulo)}</text>')
                if a.sub:
                    out.append(f'<text x="{tx:.1f}" y="{ty + 16 * k:.1f}" fill="{cor_txt}" opacity="0.7" '
                               f'font-size="{11 * k:.1f}" text-anchor="middle">{esc(a.sub)}</text>')
                if menu:  # pétala de menu: anel externo inteiro vale como ela, sem ⚙
                    out.append("</g>")
                    continue
                rg = (R1 + R2) / 2 + 2 * k
                gx, gy = c + rg * math.sin(meio), c - rg * math.cos(meio) + 5 * k
                out.append(f'<text x="{gx:.1f}" y="{gy:.1f}" fill="#fff" opacity="{1 if ativo else 0.55}" '
                           f'font-size="{14 * k:.1f}" text-anchor="middle">⚙</text>')
                out.append("</g>")
        else:
            out.append(f'<circle cx="{c}" cy="{c}" r="{(R1 + R0) / 2:.1f}" fill="none" '
                       f'stroke="rgba(14,15,18,0.8)" stroke-width="{R1 - R0:.1f}"/>')
        # miolo
        out.append(f'<g opacity="{opac_m:.3f}" transform="translate({c} {c}) scale({esc_m:.4f}) '
                   f'translate({-c} {-c})">')
        out.append(f'<circle cx="{c}" cy="{c}" r="{R0:.1f}" fill="rgba(8,8,10,0.90)" '
                   f'stroke="rgba(255,255,255,0.25)" stroke-width="1.5"/>')
        if self.arquivos:
            arq = self.arquivos[0]
            nome = os.path.basename(arq.rstrip("/"))
            extra = f" +{len(self.arquivos) - 1}" if len(self.arquivos) > 1 else ""
            try:
                info = "pasta" if os.path.isdir(arq) else tamanho_legivel(os.path.getsize(arq))
            except OSError:
                info = ""
            linhas = [(cortar(nome, 15) + extra, 11.5, "#fff", "bold"), (info, 10, "#9aa0a8", "normal")]
        else:
            linhas = []
        if i_sel is not None:
            a = self.alvos[i_sel]
            acao = (a.rotulo if a.familia == "menu" else
                    ("→ " + a.rotulo) if z_sel == "conv" else ("⚙ ajustar " + a.rotulo))
            linhas.append((acao, 13, "#4fa3ff" if z_sel == "cfg" else "#5fd38d", "bold"))
        elif self.msg:
            linhas.append((cortar(self.msg, 18), 10.5, "#ffd479", "normal"))
        else:
            linhas.append(("solte: cancelar", 10, "#9aa0a8", "normal"))
        y0 = c - (len(linhas) - 1) * 8 * k + 4 * k
        for j, (t, tam, cor, peso) in enumerate(linhas):
            out.append(f'<text x="{c}" y="{y0 + j * 17 * k:.1f}" fill="{cor}" font-size="{tam * k:.1f}" '
                       f'font-weight="{peso}" text-anchor="middle">{esc(t)}</text>')
        out.append("</g></svg>")
        return "".join(out)


# ====================================================================== tela de progresso / erro

class TelaTarefa:
    """Uma conversão: carregando → sucesso (abrir/pasta) ou erro + como resolver."""

    abertas = []

    def __init__(self, app, origens, alvo, op, destino):
        self.app, self.origens, self.alvo, self.op, self.destino = app, origens, alvo, op, destino
        self.prog = conv.Progresso(lambda f: GLib.idle_add(self._fracao, f),
                                   lambda t: GLib.idle_add(self._texto, t))
        self.tem_fracao = False
        self.fechar_id = None
        self.resultado = None

        # POPUP (override-redirect): o gerenciador de janelas não vê, então o GNOME não
        # solta a notificação "Roda Conversora está pronto" que uma toplevel sem foco gera.
        w = Gtk.Window(type=Gtk.WindowType.POPUP)
        w.set_name("tarefa-win")
        visual = w.get_screen().get_rgba_visual()
        if visual:
            w.set_visual(visual)
        w.set_size_request(440, -1)
        w.connect("enter-notify-event", lambda *_: self._parar_fechamento())
        self._tam = None
        w.connect("size-allocate", self._redimensionou)
        self.win = w

        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        caixa.get_style_context().add_class("tarefa")
        caixa.set_border_width(14)
        topo = Gtk.Box(spacing=10)
        self.icone = Gtk.Label(label="⏳")
        self.icone.get_style_context().add_class("icone")
        topo.pack_start(self.icone, False, False, 0)
        nome = os.path.basename(origens[0].rstrip("/"))
        nome = conv.cortar_meio(nome, 26) + (f" +{len(origens) - 1}" if len(origens) > 1 else "")
        titulo = Gtk.Label(xalign=0)
        titulo.set_markup(f"<b>{GLib.markup_escape_text(conv.cortar_meio(nome, 34))}</b>  →  "
                          f"<b>{GLib.markup_escape_text(alvo.rotulo)}</b>"
                          + (f"  <small>({GLib.markup_escape_text(alvo.sub)})</small>" if alvo.sub else ""))
        titulo.get_style_context().add_class("titulo")
        titulo.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        topo.pack_start(titulo, True, True, 0)
        caixa.pack_start(topo, False, False, 0)

        self.status = Gtk.Label(label="convertendo…", xalign=0)
        self.status.get_style_context().add_class("discreto")
        self.status.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.status.set_max_width_chars(48)
        caixa.pack_start(self.status, False, False, 0)
        self.barra = Gtk.ProgressBar()
        caixa.pack_start(self.barra, False, False, 0)

        # bloco de erro
        self.erro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.motivo = Gtk.Label(xalign=0, wrap=True, max_width_chars=44, selectable=True)
        self.motivo.get_style_context().add_class("motivo")
        self.erro.pack_start(self.motivo, False, False, 0)
        st = Gtk.Label(label="Como resolver", xalign=0)
        st.get_style_context().add_class("sugestao-titulo")
        self.erro.pack_start(st, False, False, 0)
        self.sugestao = Gtk.Label(xalign=0, wrap=True, max_width_chars=44, selectable=True)
        self.sugestao.get_style_context().add_class("sugestao")
        self.erro.pack_start(self.sugestao, False, False, 0)
        self.exp = Gtk.Expander(label="Detalhes técnicos")
        rol = Gtk.ScrolledWindow()
        rol.set_size_request(-1, 150)
        self.detalhes = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.CHAR)
        rol.add(self.detalhes)
        self.exp.add(rol)
        self.erro.pack_start(self.exp, False, False, 0)
        caixa.pack_start(self.erro, False, False, 0)

        self.botoes = Gtk.Box(spacing=6)
        caixa.pack_end(self.botoes, False, False, 0)
        w.add(caixa)
        self._botoes([("Cancelar", self._cancelar)])
        w.show_all()
        self.erro.hide()
        TelaTarefa.abertas.append(self)
        self._empilhar()
        self.pulso = GLib.timeout_add(120, self._pulsar)
        threading.Thread(target=self._rodar, daemon=True).start()

    # ---- layout
    def _redimensionou(self, _w, aloc):
        tam = (aloc.width, aloc.height)
        if tam != self._tam:
            self._tam = tam
            GLib.idle_add(TelaTarefa._empilhar)

    def _botoes(self, lista):
        for b in self.botoes.get_children():
            self.botoes.remove(b)
        for rotulo, cb in reversed(lista):
            b = Gtk.Button(label=rotulo)
            b.connect("clicked", lambda _b, f=cb: f())
            self.botoes.pack_end(b, False, False, 0)
        self.botoes.show_all()

    @classmethod
    def _empilhar(cls):
        mon = Gdk.Display.get_default().get_primary_monitor() or Gdk.Display.get_default().get_monitor(0)
        r = mon.get_workarea()
        y = r.y + 16   # canto superior direito, abaixo da barra do GNOME; empilha pra baixo
        for t in cls.abertas:
            w, h = t.win.get_size()
            t.win.move(r.x + r.width - w - 16, y)
            y += h + 10

    # ---- thread
    def _rodar(self):
        try:
            final = conv.converter(self.origens, self.alvo, self.op, self.destino, self.prog)
            GLib.idle_add(self._sucesso, final)
        except conv.Cancelado:
            GLib.idle_add(self._fechar)
        except conv.ErroConversao as e:
            log("falha", self.origens, "->", self.alvo.chave, e.motivo, e.detalhes[-400:])
            GLib.idle_add(self._falha, e)
        except Exception as e:  # não deveria chegar aqui, converter() já embrulha
            GLib.idle_add(self._falha, conv.ErroConversao(str(e), "", traceback.format_exc()))

    def _pulsar(self):
        if self.tem_fracao or self.resultado:
            self.pulso = None
            return False
        self.barra.pulse()
        return True

    def _fracao(self, f):
        self.tem_fracao = True
        self.barra.set_fraction(f)
        if not self.status.get_text().startswith(("página", "LibreOffice", "ghostscript", "extraindo",
                                                   "empacotando")):
            self.status.set_text(f"convertendo… {f * 100:.0f}%")

    def _texto(self, t):
        self.status.set_text(t)

    # ---- fim
    def _sucesso(self, final):
        """Deu certo: some na hora. Só o erro fica na tela."""
        self.resultado = final
        log("ok", self.origens[0], "->", final)
        self._fechar()

    def _falha(self, e):
        self.resultado = e
        self.icone.set_text("✗")
        self.icone.get_style_context().add_class("falha")
        self.barra.hide()
        self.status.set_text("a conversão falhou")
        self.motivo.set_text(e.motivo)
        self.sugestao.set_text(e.sugestao or "Tente de novo pelo ⚙ (anel externo) com outros ajustes.")
        self.detalhes.get_buffer().set_text(e.detalhes or "(sem detalhes)")
        self.exp.set_visible(bool(e.detalhes))
        self.erro.show_all()
        self.exp.set_visible(bool(e.detalhes))
        self._botoes([("Copiar erro", lambda: self._copiar(e)),
                      ("Ajustar e tentar", self._ajustar),
                      ("Fechar", self._fechar)])
        GLib.idle_add(TelaTarefa._empilhar)

    def _copiar(self, e):
        txt = f"{self.origens[0]} -> {self.alvo.rotulo}\n{e.motivo}\n\n{e.sugestao}\n\n{e.detalhes}"
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        cb.set_text(txt, -1)
        cb.store()
        self.status.set_text("erro copiado para a área de transferência")

    def _ajustar(self):
        self._fechar()
        TelaAjustes(self.app, self.origens, self.alvo, self.op)

    def _cancelar(self):
        self.status.set_text("cancelando…")
        self.prog.cancelar()

    def _parar_fechamento(self):
        if self.fechar_id:
            GLib.source_remove(self.fechar_id)
            self.fechar_id = None

    def _fechar(self):
        self._parar_fechamento()
        if self in TelaTarefa.abertas:
            TelaTarefa.abertas.remove(self)
        self.win.destroy()
        TelaTarefa._empilhar()
        return False


def apresentar(w):
    """Mostra e foca com o horário do servidor X: sem horário o mutter nega o foco e o
    GNOME troca por uma notificação "está pronto"."""
    w.show_all()
    try:
        t = GdkX11.x11_get_server_time(w.get_window())
    except (TypeError, AttributeError):
        t = 0
    w.present_with_time(t)


def abrir(caminho):
    subprocess.Popen(["xdg-open", caminho], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def mostrar_na_pasta(caminho):
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                      "org.freedesktop.FileManager1", "ShowItems",
                      GLib.Variant("(ass)", ([Gio.File.new_for_path(caminho).get_uri()], "")),
                      None, Gio.DBusCallFlags.NONE, 3000, None)
    except GLib.Error:
        abrir(os.path.dirname(caminho))


# ====================================================================== tela de ajustes

class TelaAjustes:
    def __init__(self, app, origens, alvo, op_atual=None):
        self.app, self.origens, self.alvo = app, origens, alvo
        op = alvo.padroes(app.cfg["ajustes"].get(alvo.chave))
        if op_atual:
            op.update(op_atual)
        w = Gtk.Window(title=f"Ajustar conversão → {alvo.rotulo}")
        w.set_keep_above(True)
        w.set_position(Gtk.WindowPosition.MOUSE)
        w.set_default_size(460, -1)
        w.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.win = w

        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        caixa.set_border_width(16)
        cab = Gtk.Label(xalign=0)
        nome = os.path.basename(origens[0].rstrip("/"))
        cab.set_markup(f"<big><b>{GLib.markup_escape_text(conv.cortar_meio(nome, 40))}</b></big>\n"
                       f"para <b>{GLib.markup_escape_text(alvo.rotulo)}</b>"
                       + (f" ({GLib.markup_escape_text(alvo.sub)})" if alvo.sub else ""))
        caixa.pack_start(cab, False, False, 0)

        g = Gtk.Grid(column_spacing=12, row_spacing=8)
        self.campos = {}
        linha = 0
        for o in alvo.opcoes:
            rot = Gtk.Label(label=o.rotulo, xalign=0)
            if o.dica:
                rot.set_tooltip_text(o.dica)
            g.attach(rot, 0, linha, 1, 1)
            v = op.get(o.chave, o.padrao)
            if o.tipo == "escolha":
                wd = Gtk.ComboBoxText()
                for val, txt in o.escolhas:
                    wd.append(str(val), txt)
                if not wd.set_active_id(str(v)):
                    wd.set_active(0)
            elif o.tipo == "numero":
                wd = Gtk.SpinButton.new_with_range(o.minimo, o.maximo, o.passo)
                wd.set_value(float(v or 0))
            elif o.tipo == "bool":
                wd = Gtk.Switch(active=bool(v), halign=Gtk.Align.START)
            else:
                wd = Gtk.Entry(text=str(v or ""))
            wd.set_hexpand(True)
            g.attach(wd, 1, linha, 1, 1)
            self.campos[o.chave] = (o, wd)
            linha += 1

        destino = (conv.destino_juntar(origens, alvo, app.cfg.get("pasta_saida", "")) if alvo.junta
                   else conv.destino_padrao(origens[0], alvo, app.cfg.get("pasta_saida", "")))
        g.attach(Gtk.Separator(), 0, linha, 2, 1)
        linha += 1
        g.attach(Gtk.Label(label="Nome do arquivo", xalign=0), 0, linha, 1, 1)
        self.nome = Gtk.Entry(text=os.path.basename(destino))
        g.attach(self.nome, 1, linha, 1, 1)
        linha += 1
        g.attach(Gtk.Label(label="Pasta", xalign=0), 0, linha, 1, 1)
        self.pasta = Gtk.FileChooserButton(title="Pasta de saída", action=Gtk.FileChooserAction.SELECT_FOLDER)
        self.pasta.set_filename(os.path.dirname(destino))
        g.attach(self.pasta, 1, linha, 1, 1)
        linha += 1
        if len(origens) > 1:
            txt = (f"{len(origens)} arquivos viram um só" if alvo.junta
                   else f"+{len(origens) - 1} arquivo(s): mesmo ajuste, nome automático")
            g.attach(Gtk.Label(label=txt, xalign=0), 0, linha, 2, 1)
            linha += 1
        self.lembrar = Gtk.CheckButton(label="Lembrar estes ajustes para o converter rápido")
        g.attach(self.lembrar, 0, linha, 2, 1)
        caixa.pack_start(g, False, False, 0)
        if not alvo.opcoes:
            caixa.pack_start(Gtk.Label(label="Esse formato não tem ajustes; só nome e pasta.", xalign=0),
                             False, False, 0)

        bts = Gtk.Box(spacing=8)
        ok = Gtk.Button(label="Converter")
        ok.get_style_context().add_class("suggested-action")
        ok.connect("clicked", self._ok)
        cancelar = Gtk.Button(label="Cancelar")
        cancelar.connect("clicked", lambda *_: w.destroy())
        bts.pack_end(ok, False, False, 0)
        bts.pack_end(cancelar, False, False, 0)
        caixa.pack_end(bts, False, False, 0)
        w.add(caixa)
        w.connect("key-press-event", lambda _w, e: e.keyval == Gdk.KEY_Escape and w.destroy())
        apresentar(w)
        ok.grab_focus()

    def _valores(self):
        op = {}
        for k, (o, wd) in self.campos.items():
            if o.tipo == "escolha":
                op[k] = wd.get_active_id() or ""
            elif o.tipo == "numero":
                op[k] = int(wd.get_value()) if float(o.passo).is_integer() else wd.get_value()
            elif o.tipo == "bool":
                op[k] = wd.get_active()
            else:
                op[k] = wd.get_text()
        return op

    def _ok(self, *_):
        op = self._valores()
        if self.lembrar.get_active():
            self.app.cfg["ajustes"][self.alvo.chave] = op
            salvar_config(self.app.cfg)
        pasta = self.pasta.get_filename() or os.path.dirname(self.origens[0])
        padrao = (conv.destino_juntar(self.origens, self.alvo) if self.alvo.junta
                  else conv.destino_padrao(self.origens[0], self.alvo))
        nome = self.nome.get_text().strip() or os.path.basename(padrao)
        base, ext = conv.separar_ext(nome)
        if ext != conv.separar_ext("x." + self.alvo.ext)[1]:
            base = nome  # tirou a extensão: devolve a certa
        self.win.destroy()
        if self.alvo.junta:
            TelaTarefa(self.app, list(self.origens), self.alvo, op, conv.caminho_livre(pasta, base, self.alvo.ext))
            return
        TelaTarefa(self.app, [self.origens[0]], self.alvo, op, conv.caminho_livre(pasta, base, self.alvo.ext))
        for o in self.origens[1:]:
            TelaTarefa(self.app, [o], self.alvo, op, conv.destino_padrao(o, self.alvo, pasta))


# ====================================================================== configurações do app

BOTOES = [(8, "Lateral de trás (8)"), (9, "Lateral da frente (9)"), (2, "Meio / rodinha (2)")]


class TelaConfig:
    def __init__(self, app):
        self.app = app
        cfg = app.cfg
        w = Gtk.Window(title="Roda Conversora - configurações")
        w.set_default_size(440, -1)
        w.set_position(Gtk.WindowPosition.CENTER)
        self.win = w
        g = Gtk.Grid(column_spacing=12, row_spacing=10)
        g.set_border_width(16)

        g.attach(Gtk.Label(label="Botão do mouse", xalign=0), 0, 0, 1, 1)
        self.botao = Gtk.ComboBoxText()
        ids = [b for b, _ in BOTOES]
        for b, txt in BOTOES:
            self.botao.append(str(b), txt)
        if cfg["botao"] not in ids:
            self.botao.append(str(cfg["botao"]), f"Botão {cfg['botao']}")
        self.botao.set_active_id(str(cfg["botao"]))
        g.attach(self.botao, 1, 0, 1, 1)

        detectar = Gtk.EventBox()
        self.det_label = Gtk.Label(label="ou clique AQUI com o botão que quer usar")
        self.det_label.set_margin_top(8)
        self.det_label.set_margin_bottom(8)
        detectar.add(self.det_label)
        detectar.connect("button-press-event", self._detectar)
        moldura = Gtk.Frame()
        moldura.add(detectar)
        g.attach(moldura, 0, 1, 2, 1)

        g.attach(Gtk.Label(label="Tamanho da roda (%)", xalign=0), 0, 2, 1, 1)
        self.tamanho = Gtk.SpinButton.new_with_range(60, 200, 5)
        self.tamanho.set_value(cfg["tamanho"])
        g.attach(self.tamanho, 1, 2, 1, 1)


        g.attach(Gtk.Label(label="Pasta de saída fixa", xalign=0), 0, 4, 1, 1)
        caixa_p = Gtk.Box(spacing=6)
        self.pasta = Gtk.FileChooserButton(title="Pasta de saída", action=Gtk.FileChooserAction.SELECT_FOLDER)
        if cfg["pasta_saida"]:
            self.pasta.set_filename(cfg["pasta_saida"])
        limpar = Gtk.Button(label="Mesma do arquivo")
        limpar.connect("clicked", lambda *_: self.pasta.unselect_all())
        caixa_p.pack_start(self.pasta, True, True, 0)
        caixa_p.pack_start(limpar, False, False, 0)
        g.attach(caixa_p, 1, 4, 1, 1)

        n = len(cfg["ajustes"])
        esquecer = Gtk.Button(label=f"Esquecer ajustes lembrados ({n})")
        esquecer.set_sensitive(n > 0)
        esquecer.connect("clicked", lambda b: (cfg["ajustes"].clear(), b.set_label("Esquecer ajustes lembrados (0)"),
                                               b.set_sensitive(False)))
        g.attach(esquecer, 0, 5, 2, 1)

        dica = Gtk.Label(xalign=0, wrap=True, max_width_chars=60)
        dica.set_markup("<small>Segure o botão sobre um arquivo no Nautilus ou na área de trabalho, "
                        "arraste até o formato e solte. Anel de dentro: converte direto. Anel de fora "
                        "(⚙): abre os ajustes. Solte no centro ou longe da roda para cancelar. Toque rápido no botão deixa "
                        "a roda aberta: escolha com clique esquerdo, direito cancela.</small>")
        g.attach(dica, 0, 6, 2, 1)

        bts = Gtk.Box(spacing=8)
        salvar = Gtk.Button(label="Salvar")
        salvar.get_style_context().add_class("suggested-action")
        salvar.connect("clicked", self._salvar)
        bts.pack_end(salvar, False, False, 0)
        g.attach(bts, 0, 7, 2, 1)
        w.add(g)
        apresentar(w)

    def _detectar(self, _w, ev):
        b = ev.button
        if self.botao.get_active_id() != str(b) and not self.botao.set_active_id(str(b)):
            self.botao.append(str(b), f"Botão {b}")
            self.botao.set_active_id(str(b))
        self.det_label.set_text(f"detectado: botão {b}")
        return True

    def _salvar(self, *_):
        cfg = self.app.cfg
        b = int(self.botao.get_active_id() or 8)
        if b in (1, 3):
            self.det_label.set_markup("<b>Botão esquerdo/direito não pode ser o gatilho.</b>")
            return
        cfg["botao"] = b
        cfg["tamanho"] = int(self.tamanho.get_value())
        cfg["pasta_saida"] = self.pasta.get_filename() or ""
        salvar_config(cfg)
        self.app.aplicar_botao()
        self.win.destroy()


# ====================================================================== app

class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.iniciado = False

    def do_command_line(self, cmdline):
        args = [a for a in cmdline.get_arguments()[1:] if not a.startswith("--")]
        if not self.iniciado:
            self._iniciar()
            if "--desligado" in cmdline.get_arguments() and not self.cfg["pausado"]:
                self._pausar(True)  # autostart: sobe só o ícone (cinza), roda desligada
        caminhos = [os.path.abspath(os.path.join(cmdline.get_cwd() or ".", a)) for a in args]
        caminhos = [c for c in caminhos if os.path.exists(c)]
        chave = next((a.split("=", 1)[1] for a in cmdline.get_arguments() if a.startswith("--alvo=")), None)
        if caminhos and chave:  # menu do Nautilus: formato já escolhido, sem roda
            alvo = conv.achar_alvo(caminhos, chave)
            if alvo and "--ajustes" in cmdline.get_arguments():
                TelaAjustes(self, caminhos, alvo)
            elif alvo:
                self.disparar(caminhos, alvo)
            else:
                log("alvo não encontrado", chave, caminhos)
        elif caminhos:
            GLib.timeout_add(150, self.roda_para, caminhos)
        elif "--config" in cmdline.get_arguments():
            TelaConfig(self)
        return 0

    def _iniciar(self):
        self.iniciado = True
        self.hold()
        self.cfg = carregar_config()
        css = Gtk.CssProvider()
        css.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.x11 = X11(self._evento)
        self.captura = Captura(self.x11)
        self.roda = Roda(self)
        self.ativo = False       # roda aberta com o ponteiro preso
        self.modo_clique = False  # roda aberta esperando clique esquerdo
        self.arquivos = None
        self.aplicar_botao()
        self._criar_bandeja()
        log("iniciado, botão", self.cfg["botao"])

    def aplicar_botao(self):
        b = None if self.cfg["pausado"] else self.cfg["botao"]
        if not self.x11.capturar_botao(b):
            log("botão", b, "já está preso por outro programa")
            self.aviso(f"O botão {b} do mouse já está capturado por outro programa.",
                       "Feche o programa que usa esse botão (ex.: input-remapper, Solaar, easystroke) ou "
                       "escolha outro botão em Configurações.")

    def aviso(self, motivo, sugestao):
        d = Gtk.MessageDialog(message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.OK,
                              text=motivo)
        d.format_secondary_text("Como resolver: " + sugestao)
        d.set_keep_above(True)
        d.connect("response", lambda *_: d.destroy())
        apresentar(d)

    # ---- gatilho
    def _evento(self, tipo, botao, x, y, sub):
        if tipo == ButtonPress and not self.ativo:
            if botao != self.cfg["botao"]:
                return
            info = self.x11.classe(sub)
            if not e_gerenciador(info):
                self.x11.soltar_evento(repassar=True)  # não é arquivo: o clique segue normal
                return
            janela = self.x11.ultimo_cliente   # o cliente que classe() achou
            self.x11.soltar_evento(repassar=False)
            self._abrir_por_botao(x, y, janela)
            return
        if not self.ativo:
            return
        if tipo == MotionNotify:
            self.roda.mover(x, y)
            self._talvez_menu(x, y)
        elif tipo == ButtonRelease and botao == self.cfg["botao"] and not self.modo_clique:
            rapido = time.monotonic() - self.t_abriu < 0.35
            i, _ = self.roda.zona(x, y)
            if i is None and (rapido or self.arquivos is None):
                self.modo_clique = True  # toque rápido: a roda fica aberta
                return
            self._decidir(x, y)
        elif tipo == ButtonPress and botao in (1, self.cfg["botao"]):
            self._decidir(x, y)
        elif tipo == ButtonPress and botao == 3:
            self._fechar_roda()

    def _abrir_por_botao(self, x, y, janela=None):
        self.x11.clique_esquerdo()   # seleciona o item sob o cursor
        self.x11.focar(janela)       # e garante o teclado nela antes do Ctrl+C
        self._abrir_roda(x, y, modo_clique=False)
        self.arquivos = None
        self.captura.iniciar(self._capturou)
        sessao = self.sessao
        # só se a captura demorar aparece a roda vazia com "lendo…"
        GLib.timeout_add(300, lambda: self.ativo and self.sessao == sessao and not self.roda.visivel
                         and self.roda.preencher([], [], "lendo arquivo…") and False)

    def _abrir_roda(self, x, y, modo_clique):
        escala_mon, cx, cy = self._centro(x, y)
        if not self.x11.pegar_ponteiro():
            # outro grab ativo (ex.: menu do Nautilus fechando): tenta de novo por ~1 s
            tentativas = [15]

            def de_novo():
                tentativas[0] -= 1
                if not self.ativo or self.x11.pegar_ponteiro():
                    return False
                if tentativas[0] <= 0:
                    log("não consegui prender o ponteiro; fechando a roda")
                    self._fechar_roda()
                    return False
                return True
            GLib.timeout_add(70, de_novo)
        self.ativo = True
        self.sessao = getattr(self, "sessao", 0) + 1
        sessao = self.sessao
        GLib.timeout_add_seconds(45, lambda: self.ativo and self.sessao == sessao and self._fechar_roda())
        self.modo_clique = modo_clique
        self.t_abriu = time.monotonic()
        self.roda.preparar(cx, cy, self.cfg["tamanho"] / 100, cx / escala_mon, cy / escala_mon)

    def _centro(self, x, y):
        disp = Gdk.Display.get_default()
        mon = disp.get_monitor_at_point(x, y) or disp.get_monitor(0)
        # Centro = onde o mouse está, SEMPRE. Antes a roda era empurrada pra caber no monitor e o
        # cursor ia junto (pulava ~2 dedos perto da borda/divisa dos monitores). Perto da borda
        # a roda fica cortada, mas o mouse não se mexe.
        return mon.get_scale_factor(), int(x), int(y)

    def _capturou(self, caminhos):
        if not self.ativo:
            return
        if not caminhos:
            self.arquivos = []
            self.roda.preencher([], [], "nenhum arquivo aqui")
            GLib.timeout_add(900, self._fechar_roda)
            return
        self._mostrar_alvos(caminhos)

    # ---- 2ª roda (extras)
    def _menu_alvo(self, destino):
        """Pétala que troca de roda: 'mais' (extras), 'juntar' (vários → um) ou 'voltar'."""
        if destino == "mais":
            a = conv.Alvo("", "menu", None, rotulo="+ MAIS", sub=f"{len(self.extras)} extras")
        elif destino == "juntar":
            a = conv.Alvo("", "menu", None, rotulo="⧉ JUNTAR", sub=f"{len(self.arquivos)} em 1")
        else:
            a = conv.Alvo("", "menu", None, rotulo="← VOLTAR", sub="principais")
        a.destino = destino
        return a

    def _roda_principal(self):
        alvos = list(self.principais)
        if self.juntar:
            alvos.append(self._menu_alvo("juntar"))
        if self.extras:
            alvos.append(self._menu_alvo("mais"))
        return alvos

    def _talvez_menu(self, x, y):
        """Segurando o botão: parar ~0,45 s em cima de "+ MAIS"/"← VOLTAR" troca de roda."""
        i, _ = self.roda.zona(x, y)
        no_menu = i is not None and self.roda.alvos[i].familia == "menu"
        if not no_menu:
            if getattr(self, "_menu_id", None):
                GLib.source_remove(self._menu_id)
                self._menu_id = None
            return
        if not getattr(self, "_menu_id", None):
            def trocar():
                self._menu_id = None
                px, py, _ = self.x11.ponteiro()
                j, _ = self.roda.zona(px, py)
                if self.ativo and j == i and self.roda.alvos[i].familia == "menu":
                    self._trocar_roda(self.roda.alvos[i])
                return False
            self._menu_id = GLib.timeout_add(450, trocar)

    def _trocar_roda(self, menu):
        destino = getattr(menu, "destino", "voltar")
        if destino == "mais":
            alvos = self.extras + [self._menu_alvo("voltar")]
        elif destino == "juntar":
            alvos = self.juntar + ([self._menu_alvo("voltar")] if self.principais or self.extras else [])
        else:
            alvos = self._roda_principal()
        self.roda.trocar(alvos)

    def _mostrar_alvos(self, caminhos):
        self.arquivos = caminhos
        # converter um a um só faz sentido se todos forem da mesma família (todas imagens etc.)
        mesma = len({conv.familia_de(c) for c in caminhos}) == 1
        todos = conv.alvos_para(caminhos[0]) if mesma else []
        self.principais = [a for a in todos if not a.extra]
        self.extras = [a for a in todos if a.extra]
        self.juntar = conv.alvos_juntar(caminhos)
        if not todos and self.juntar:  # só dá pra juntar: a roda já abre nas opções de juntar
            self.principais, self.juntar = self.juntar, []
        alvos = self._roda_principal()
        self.alvos = alvos
        _, ext = conv.separar_ext(caminhos[0])
        self.roda.preencher(caminhos, alvos, "" if alvos else f".{ext or '?'} sem conversão")
        x, y, _ = self.x11.ponteiro()
        self.roda.mover(x, y)
        if not alvos:
            GLib.timeout_add(1400, self._fechar_roda)

    def roda_para(self, caminhos):
        """Abre a roda no ponteiro para arquivos vindos da linha de comando/script do Nautilus."""
        if self.ativo:
            return False
        x, y, _ = self.x11.ponteiro()
        self._abrir_roda(x, y, modo_clique=True)
        self._mostrar_alvos(caminhos)
        return False

    def _decidir(self, x, y):
        i, z = self.roda.zona(x, y)
        arquivos = self.arquivos
        if i is not None and arquivos and self.roda.alvos[i].familia == "menu":
            self.modo_clique = True   # soltou/clicou em "+ MAIS": a roda nova fica aberta
            self._trocar_roda(self.roda.alvos[i])
            return
        self._fechar_roda(i if arquivos else None, z)
        if i is None or not arquivos:
            return
        alvo = self.roda.alvos[i]
        if z == "cfg":
            TelaAjustes(self, arquivos, alvo)
            return
        self.disparar(arquivos, alvo)

    def disparar(self, arquivos, alvo):
        """Converte com os ajustes lembrados: junta = uma tarefa com tudo; senão uma por arquivo."""
        op = alvo.padroes(self.cfg["ajustes"].get(alvo.chave))
        pasta = self.cfg.get("pasta_saida", "")
        if alvo.junta:
            TelaTarefa(self, list(arquivos), alvo, op, conv.destino_juntar(arquivos, alvo, pasta))
            return
        for a in arquivos:
            TelaTarefa(self, [a], alvo, op, conv.destino_padrao(a, alvo, pasta))

    def _fechar_roda(self, i=None, zona=None):
        self.ativo = False
        self.modo_clique = False
        self.x11.liberar_ponteiro()   # o mouse volta na hora; a animação segue sozinha
        self.roda.fechar(i, zona)
        return False

    # ---- menu
    def _menu(self):
        m = Gtk.Menu()

        def item(rotulo, cb):
            it = Gtk.MenuItem(label=rotulo)
            it.connect("activate", lambda *_: cb())
            m.append(it)

        pausa = Gtk.CheckMenuItem(label="Ligada")
        pausa.set_active(not self.cfg["pausado"])
        pausa.connect("toggled", lambda w: self._pausar(not w.get_active()))
        m.append(pausa)
        item("Converter arquivo…", self._escolher_arquivo)
        item("Configurações…", lambda: TelaConfig(self))
        item("Abrir log", lambda: abrir(LOG_PATH) if os.path.exists(LOG_PATH) else None)
        # sem "Sair" de propósito: o ícone fica sempre na barra; "Ligada" desmarcada é o desligar
        m.show_all()
        return m

    def _pausar(self, on):
        self.cfg["pausado"] = on
        salvar_config(self.cfg)
        self.aplicar_botao()
        if self.ind:
            self.ind.set_icon_full(self._nome_icone(), "Roda Conversora" + (" (pausada)" if on else ""))
            GLib.idle_add(self._refazer_menu_bandeja)  # o check "Ligada" segue o estado
        if self.icone:
            self.icone.set_from_file(os.path.join(ICONES_DIR, self._nome_icone() + ".svg"))
            self.icone.set_tooltip_text("Roda Conversora" + (" (pausada)" if on else ""))

    def _refazer_menu_bandeja(self):
        self._menu_bandeja = self._menu()
        self.ind.set_menu(self._menu_bandeja)
        return False

    def _escolher_arquivo(self):
        d = Gtk.FileChooserNative(title="Arquivo para converter", action=Gtk.FileChooserAction.OPEN)
        d.set_select_multiple(True)
        if d.run() == Gtk.ResponseType.ACCEPT:
            arqs = d.get_filenames()
            GLib.timeout_add(250, self.roda_para, arqs)
        d.destroy()

    def _nome_icone(self):
        return "roda-conversor-" + ("off" if self.cfg["pausado"] else "on")

    def _criar_bandeja(self):
        self.ind = self.icone = None
        gerar_icones_bandeja()
        nome_icone = self._nome_icone()
        if AppIndicator:
            self.ind = AppIndicator.Indicator.new("roda-conversor", nome_icone,
                                                  AppIndicator.IndicatorCategory.APPLICATION_STATUS)
            self.ind.set_icon_theme_path(ICONES_DIR)
            self.ind.set_icon_full(nome_icone, "Roda Conversora")
            self.ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
            self._menu_bandeja = self._menu()
            self.ind.set_menu(self._menu_bandeja)
        else:
            icone = Gtk.StatusIcon.new_from_file(os.path.join(ICONES_DIR, nome_icone + ".svg"))
            icone.set_tooltip_text("Roda Conversora" + (" (pausada)" if self.cfg["pausado"] else ""))
            icone.set_title("Roda Conversora")
            icone.connect("activate", lambda *_: TelaConfig(self))
            icone.connect("popup-menu", self._menu_icone)
            self.icone = icone

    def _menu_icone(self, icone, botao, tempo):
        self._menu_bandeja = self._menu()
        self._menu_bandeja.popup(None, None, Gtk.StatusIcon.position_menu, icone, botao, tempo)

    def sair(self):
        self.x11.capturar_botao(None)
        self.release()
        self.quit()


ICONES_DIR = os.path.expanduser("~/.cache/roda-conversor/icones")


def svg_icone_bandeja(cor, detalhe):
    """Ícone 22x22 da bandeja: roda de 6 fatias (estilo seleção de arma) com seta girando no meio."""
    fatias = []
    for i in range(6):
        a0, a1 = math.radians(i * 60 - 90 + 4), math.radians(i * 60 - 30 - 4)
        pts = [(11 + r * math.cos(a), 11 + r * math.sin(a)) for r, a in ((10, a0), (10, a1), (6, a1), (6, a0))]
        fatias.append(
            f'<path d="M{pts[0][0]:.2f} {pts[0][1]:.2f} A10 10 0 0 1 {pts[1][0]:.2f} {pts[1][1]:.2f} '
            f'L{pts[2][0]:.2f} {pts[2][1]:.2f} A6 6 0 0 0 {pts[3][0]:.2f} {pts[3][1]:.2f} Z" '
            f'fill="{cor}" opacity="{1 if i % 2 == 0 else 0.7}"/>')
    seta = (f'<path d="M13.6 9.0 A3.3 3.3 0 1 0 14.3 12.4" fill="none" stroke="{detalhe}" '
            f'stroke-width="1.5" stroke-linecap="round"/>'
            f'<path d="M12.2 6.6 L16.6 8.0 L13.4 11.4 Z" fill="{detalhe}"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">'
            + "".join(fatias) + seta + "</svg>")


def gerar_icones_bandeja():
    """Colorido = ativa, cinza = pausada (mesmo padrão da bandeja-apps)."""
    os.makedirs(ICONES_DIR, exist_ok=True)
    for estado, cor, detalhe in (("on", "#16a085", "#f1c40f"), ("off", "#9a9a9a", "#d0d0d0")):
        with open(os.path.join(ICONES_DIR, f"roda-conversor-{estado}.svg"), "w") as f:
            f.write(svg_icone_bandeja(cor, detalhe))


def main():
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)  # Gtk.StatusIcon
    GLib.set_prgname("roda-conversor")
    sys.exit(App().run(sys.argv))


if __name__ == "__main__":
    main()
