"""Motor de conversões da Roda Conversora.

Sem GTK aqui: tudo roda em thread de trabalho e é testável sem tela (verifica.sh).
Cada formato de saída é um `Alvo`; `alvos_para(caminho)` devolve os que servem
para aquele arquivo. Falha vira `ErroConversao(motivo, sugestao, detalhes)`, que a
tela de progresso mostra como erro + "como resolver".
"""
import csv
import html
import io
import json
import math
import os
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import zipfile
from html.parser import HTMLParser

# ---------------------------------------------------------------- erros e progresso


class ErroConversao(Exception):
    def __init__(self, motivo, sugestao="", detalhes=""):
        super().__init__(motivo)
        self.motivo = motivo
        self.sugestao = sugestao
        self.detalhes = detalhes


class Cancelado(Exception):
    pass


PACOTE = {  # executável -> pacote apt
    "ffmpeg": "ffmpeg", "ffprobe": "ffmpeg", "soffice": "libreoffice",
    "gs": "ghostscript", "pdftotext": "poppler-utils",
}


class Progresso:
    """Ponte entre a conversão (thread) e a tela. A tela troca os callbacks."""

    def __init__(self, ao_fracao=None, ao_texto=None):
        self.ao_fracao = ao_fracao or (lambda f: None)
        self.ao_texto = ao_texto or (lambda t: None)
        self.cancelado = False
        self._proc = None

    def fracao(self, f):
        self.ao_fracao(max(0.0, min(1.0, f)))

    def texto(self, t):
        self.ao_texto(t)

    def checar(self):
        if self.cancelado:
            raise Cancelado()

    def cancelar(self):
        self.cancelado = True
        p = self._proc
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass

    def rodar(self, cmd, duracao=None, timeout=None):
        """Roda um processo; se `duracao` (s) vier, lê o -progress do ffmpeg."""
        exe = cmd[0]
        if not shutil.which(exe):
            pac = PACOTE.get(exe, exe)
            raise ErroConversao(
                f"Ferramenta '{exe}' não está instalada.",
                f"Instale com:\n  sudo apt install {pac}",
            )
        self.checar()
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        self._proc = p
        err = []
        import threading
        t = threading.Thread(target=lambda: err.extend(p.stderr), daemon=True)
        t.start()
        inicio = time.time()
        for linha in p.stdout:
            if duracao and linha.startswith(b"out_time_us="):
                try:
                    us = int(linha.split(b"=")[1])
                    self.fracao(us / 1e6 / duracao)
                except ValueError:
                    pass
            if timeout and time.time() - inicio > timeout:
                self.cancelar()
        p.wait()
        t.join(2)
        p.stdout.close()  # sem isso cada conversão deixa 2 descritores abertos na roda (processo longo)
        p.stderr.close()
        self._proc = None
        self.checar()
        saida = b"".join(err).decode("utf-8", "replace")
        if p.returncode != 0:
            raise erro_de_processo(exe, saida, p.returncode)
        return saida


def erro_de_processo(exe, stderr, codigo):
    """Traduz a saída de erro numa causa e numa sugestão de como resolver."""
    s = stderr.lower()
    cauda = "\n".join(stderr.strip().splitlines()[-25:])
    regras = [
        ("no space left", "Disco cheio.", "Libere espaço no disco ou escolha outra pasta de saída no ⚙."),
        ("permission denied", "Sem permissão para ler ou gravar.",
         "Escolha outra pasta de saída no ⚙ (anel externo da roda) ou confira as permissões do arquivo."),
        ("invalid data found", "O arquivo não parece ser mídia válida (corrompido ou extensão errada).",
         "Abra o arquivo num player para confirmar. Se a extensão estiver errada, renomeie para a certa."),
        ("moov atom not found", "Vídeo incompleto (download ou gravação interrompida).",
         "Baixe/grave de novo. Arquivo truncado não tem índice e não converte."),
        ("unknown encoder", "Este ffmpeg não tem o codificador necessário.",
         "Tente outro formato de saída ou instale o ffmpeg completo: sudo apt install ffmpeg"),
        ("does not contain any stream", "O arquivo não tem a faixa pedida (ex.: vídeo sem áudio).",
         "Escolha um formato compatível com o conteúdo do arquivo."),
        ("output file #0 does not contain", "O arquivo não tem a faixa pedida (ex.: vídeo sem áudio).",
         "Escolha um formato compatível com o conteúdo do arquivo."),
        ("matches no streams", "O arquivo não tem a faixa pedida (ex.: vídeo sem áudio).",
         "Escolha um formato compatível com o conteúdo do arquivo."),
        ("could not write header", "O formato de saída não aceita os codecs do arquivo.",
         "No ⚙, desligue 'copiar sem recodificar' ou escolha mp4/mkv."),
        ("password", "PDF protegido por senha.", "Remova a senha do PDF antes de converter."),
        ("height not divisible by 2", "Resolução ímpar não é aceita por esse codec.",
         "No ⚙, escolha uma resolução da lista (ela já sai par)."),
        ("width not divisible by 2", "Resolução ímpar não é aceita por esse codec.",
         "No ⚙, escolha uma resolução da lista (ela já sai par)."),
        ("source file could not be loaded", "O LibreOffice não conseguiu abrir o documento.",
         "Abra no LibreOffice para ver se o arquivo está íntegro; se for protegido, remova a senha."),
    ]
    for chave, motivo, sug in regras:
        if chave in s:
            return ErroConversao(motivo, sug, cauda)
    return ErroConversao(f"'{exe}' terminou com erro (código {codigo}).",
                         "Veja os detalhes técnicos abaixo. Tente o ⚙ (anel externo) com ajustes mais simples, "
                         "ou outro formato de saída.", cauda)


# ---------------------------------------------------------------- opções e alvos


class Opcao:
    """Um campo da tela de ajustes. tipo: escolha | numero | texto | bool."""

    def __init__(self, chave, rotulo, tipo, padrao, escolhas=None, minimo=0, maximo=100,
                 passo=1, dica=""):
        self.chave, self.rotulo, self.tipo, self.padrao = chave, rotulo, tipo, padrao
        self.escolhas = escolhas or []   # [(valor, rótulo)]
        self.minimo, self.maximo, self.passo, self.dica = minimo, maximo, passo, dica


class Alvo:
    def __init__(self, ext, familia, func, opcoes=(), rotulo=None, sub="", extra=False, junta=False):
        self.ext = ext                    # extensão de saída, sem ponto
        self.familia = familia
        self.func = func                  # func(origens, destino, op, prog) -> caminho final
        self.opcoes = list(opcoes)
        self.rotulo = rotulo or ext.upper()
        self.sub = sub                    # linha pequena embaixo do rótulo na roda
        self.extra = extra                # True = fica na 2ª roda, atrás da pétala "+ MAIS"
        self.junta = junta                # True = todas as origens viram UM arquivo (pétala "⧉ JUNTAR")

    @property
    def chave(self):
        return f"{self.familia}:{self.rotulo}:{self.sub}"

    def padroes(self, salvos=None):
        op = {o.chave: o.padrao for o in self.opcoes}
        if salvos:
            op.update({k: v for k, v in salvos.items() if k in op})
        return op


def caminho_livre(pasta, base, ext):
    """`base.ext`; se existir, `base (1).ext`, `base (2).ext`..."""
    sufixo = f".{ext}" if ext else ""
    p = os.path.join(pasta, base + sufixo)
    n = 1
    while os.path.exists(p):
        p = os.path.join(pasta, f"{base} ({n}){sufixo}")
        n += 1
    return p


def cortar_meio(t, n):
    """'um-nome-muito-comprido.webp' -> 'um-nome-m…rido.webp' (mantém a extensão à vista)."""
    if len(t) <= n:
        return t
    a = (n - 1) * 2 // 3
    return t[:a] + "…" + t[-(n - 1 - a):]


EXT_DUPLA =("tar.gz", "tar.xz", "tar.bz2", "tar.zst")


def separar_ext(caminho):
    nome = os.path.basename(caminho.rstrip("/"))
    baixo = nome.lower()
    for d in EXT_DUPLA:
        if baixo.endswith("." + d):
            return nome[: -len(d) - 1], d
    for d, eq in (("tgz", "tar.gz"), ("txz", "tar.xz")):
        if baixo.endswith("." + d):
            return nome[: -len(d) - 1], eq
    base, ext = os.path.splitext(nome)
    return base, ext[1:].lower()


def destino_padrao(origem, alvo, pasta_saida=""):
    base, _ = separar_ext(origem)
    pasta = pasta_saida or os.path.dirname(os.path.abspath(origem.rstrip("/")))
    return caminho_livre(pasta, base, alvo.ext)


# ---------------------------------------------------------------- utilidades de mídia


def ffprobe_duracao(caminho):
    if not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", caminho],
                           capture_output=True, text=True, timeout=20)
        return float(r.stdout.strip())
    except (ValueError, subprocess.SubprocessError):
        return None


def ffprobe_tem(caminho, tipo):
    """tipo 'a' ou 'v': o arquivo tem faixa desse tipo?"""
    if not shutil.which("ffprobe"):
        return True
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", tipo, "-show_entries",
                        "stream=index", "-of", "csv=p=0", caminho],
                       capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise ErroConversao("O arquivo não parece ser mídia válida (corrompido ou extensão errada).",
                            "Abra o arquivo num player para confirmar. Se a extensão estiver errada, "
                            "renomeie para a certa.", r.stderr.strip()[-1500:])
    return bool(r.stdout.strip())


def segundos(txt):
    """'90', '1:30', '00:01:30.5' -> segundos. Vazio -> None."""
    txt = (txt or "").strip().replace(",", ".")
    if not txt:
        return None
    try:
        partes = [float(p) for p in txt.split(":")]
    except ValueError:
        raise ErroConversao(f"Tempo '{txt}' inválido.", "Use segundos (90) ou mm:ss (1:30) ou hh:mm:ss.")
    s = 0.0
    for p in partes:
        s = s * 60 + p
    return s


def corte_ffmpeg(op, dur):
    """Argumentos -ss/-to e a duração efetiva para o progresso."""
    ini, fim = segundos(op.get("inicio")), segundos(op.get("fim"))
    args = []
    if ini:
        args += ["-ss", f"{ini}"]
    if fim:
        args += ["-to", f"{fim}"]
    efetiva = dur
    if dur:
        efetiva = (fim or dur) - (ini or 0)
    return args, (efetiva if efetiva and efetiva > 0 else None)


def ffmpeg_base():
    return ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats"]


# ---------------------------------------------------------------- imagem

IMG_IN = {"png", "jpg", "jpeg", "jfif", "webp", "bmp", "gif", "tif", "tiff", "ico", "tga",
          "ppm", "pgm", "pbm", "heic", "heif", "avif", "psd", "pcx"}
FUNDOS = [("branco", "Branco"), ("preto", "Preto"), ("cinza", "Cinza")]
COR_FUNDO = {"branco": (255, 255, 255), "preto": (0, 0, 0), "cinza": (128, 128, 128)}


def abrir_imagem(caminho):
    """PIL; se não abrir (HEIC/AVIF), tenta o GdkPixbuf, que tem loader de heif."""
    from PIL import Image
    try:
        im = Image.open(caminho)
        im.load()
        return im
    except Exception as e:
        primeiro = e
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        pb = GdkPixbuf.Pixbuf.new_from_file(caminho)
        modo = "RGBA" if pb.get_has_alpha() else "RGB"
        return Image.frombuffer(modo, (pb.get_width(), pb.get_height()), pb.get_pixels(),
                                "raw", modo, pb.get_rowstride(), 1).copy()
    except Exception:
        pass
    raise ErroConversao("Não consegui abrir a imagem (corrompida ou formato não suportado).",
                        "Abra no visualizador de imagens para conferir. HEIC/AVIF exigem o loader "
                        "do GdkPixbuf (sudo apt install heif-gdk-pixbuf).", str(primeiro))


def redimensionar(im, op):
    from PIL import Image
    w, h = int(op.get("largura") or 0), int(op.get("altura") or 0)
    pct = int(op.get("escala") or 100)
    if pct != 100 and not (w or h):
        w = max(1, im.width * pct // 100)
    if not (w or h):
        return im
    if w and not h:
        h = max(1, round(im.height * w / im.width))
    elif h and not w:
        w = max(1, round(im.width * h / im.height))
    return im.resize((w, h), Image.LANCZOS)


def achatar(im, fundo):
    from PIL import Image
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        base = Image.new("RGB", im.size, COR_FUNDO.get(fundo, (255, 255, 255)))
        base.paste(im, mask=im.getchannel("A"))
        return base
    return im.convert("RGB")


def quadros(im):
    from PIL import ImageSequence
    return [f.copy() for f in ImageSequence.Iterator(im)]


def conv_imagem(origens, destino, op, prog, fmt):
    from PIL import Image, ImageOps
    im = abrir_imagem(origens[0])
    animada = getattr(im, "n_frames", 1) > 1
    exif = im.info.get("exif") if op.get("manter_exif") else None
    prog.fracao(0.2)
    if animada and fmt in ("GIF", "WEBP"):
        fs = [redimensionar(f.convert("RGBA"), op) for f in quadros(im)]
        dur = im.info.get("duration", 100)
        extra = {"quality": int(op.get("qualidade", 85))} if fmt == "WEBP" else {"disposal": 2}
        fs[0].save(destino, fmt, save_all=True, append_images=fs[1:], duration=dur,
                   loop=im.info.get("loop", 0), **extra)
        return destino
    im = ImageOps.exif_transpose(im) if op.get("girar_exif", True) else im
    im = redimensionar(im, op)
    prog.fracao(0.6)
    kw = {}
    if exif:
        kw["exif"] = exif
    q = int(op.get("qualidade", 90))
    if fmt == "JPEG":
        im = achatar(im, op.get("fundo"))
        kw.update(quality=q, optimize=True, progressive=bool(op.get("progressivo", True)))
    elif fmt == "WEBP":
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA")
        kw.update(quality=q, lossless=bool(op.get("sem_perdas")), method=5)
    elif fmt == "PNG":
        if im.mode not in ("RGB", "RGBA", "L", "LA", "P", "I", "1"):
            im = im.convert("RGBA")
        kw.update(optimize=True, compress_level=int(op.get("compressao", 9)))
    elif fmt == "BMP":
        im = achatar(im, op.get("fundo"))
    elif fmt == "TIFF":
        kw.update(compression=op.get("compressao_tiff", "tiff_lzw"))
    elif fmt == "GIF":
        im = im.convert("RGBA") if im.mode != "P" else im
    elif fmt == "ICO":
        tams = [int(x) for x in str(op.get("tamanhos", "16,32,48,64,128,256")).split(",") if x.strip()]
        im = im.convert("RGBA")
        lado = max(im.size)
        quad = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
        quad.paste(im, ((lado - im.width) // 2, (lado - im.height) // 2))
        im = quad
        kw.update(sizes=[(t, t) for t in tams])
    elif fmt == "PDF":
        im = achatar(im, op.get("fundo"))
        kw.update(resolution=float(op.get("dpi", 150)))
    im.save(destino, fmt, **kw)
    return destino


def conv_imagem_ffmpeg(origens, destino, op, prog, codec_args):
    """AVIF e afins: PIL não grava aqui, o ffmpeg (libaom) grava."""
    from PIL import Image
    im = redimensionar(abrir_imagem(origens[0]), op)
    with tempfile.TemporaryDirectory(prefix="roda-") as tmp:
        png = os.path.join(tmp, "in.png")
        (im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im).save(png)
        crf = str(int(63 - int(op.get("qualidade", 70)) * 0.6))
        prog.rodar(ffmpeg_base() + ["-i", png] + codec_args(crf) + [destino])
    return destino


def conv_anim_video(origens, destino, op, prog):
    """GIF/WebP animado -> mp4/webm."""
    v = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if destino.endswith(".webm"):
        v = ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "32"]
    escala = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    prog.rodar(ffmpeg_base() + ["-i", origens[0], "-vf", escala] + v + ["-an", destino],
               duracao=ffprobe_duracao(origens[0]))
    return destino


def op_imagem(qualidade=True, fundo=False, extra=()):
    ops = [Opcao("largura", "Largura (px, 0 = original)", "numero", 0, maximo=20000, passo=10),
           Opcao("altura", "Altura (px, 0 = proporcional)", "numero", 0, maximo=20000, passo=10),
           Opcao("escala", "Escala (%) se largura/altura = 0", "numero", 100, minimo=1, maximo=800)]
    if qualidade:
        ops.append(Opcao("qualidade", "Qualidade (1-100)", "numero", 90, minimo=1, maximo=100))
    if fundo:
        ops.append(Opcao("fundo", "Fundo no lugar da transparência", "escolha", "branco", FUNDOS))
    ops.append(Opcao("manter_exif", "Manter metadados EXIF (câmera, GPS)", "bool", False))
    return ops + list(extra)


def alvos_imagem():
    def pil(fmt):
        return lambda o, d, op, p: conv_imagem(o, d, op, p, fmt)
    avif = lambda o, d, op, p: conv_imagem_ffmpeg(
        o, d, op, p, lambda crf: ["-c:v", "libaom-av1", "-still-picture", "1", "-crf", crf, "-b:v", "0"])
    return [
        Alvo("png", "imagem", pil("PNG"), op_imagem(False, extra=[
            Opcao("compressao", "Compressão PNG (0-9)", "numero", 9, minimo=0, maximo=9)])),
        Alvo("jpg", "imagem", pil("JPEG"), op_imagem(True, True, [
            Opcao("progressivo", "JPEG progressivo", "bool", True)])),
        Alvo("webp", "imagem", pil("WEBP"), op_imagem(True, extra=[
            Opcao("sem_perdas", "Sem perdas (lossless)", "bool", False)])),
        Alvo("avif", "imagem", avif, op_imagem(True), extra=True),
        Alvo("gif", "imagem", pil("GIF"), op_imagem(False)),
        Alvo("bmp", "imagem", pil("BMP"), op_imagem(False, True), extra=True),
        Alvo("tiff", "imagem", pil("TIFF"), op_imagem(False, extra=[
            Opcao("compressao_tiff", "Compressão", "escolha", "tiff_lzw",
                  [("tiff_lzw", "LZW"), ("tiff_deflate", "Deflate"), ("raw", "Nenhuma")])]), extra=True),
        Alvo("ico", "imagem", pil("ICO"), [
            Opcao("tamanhos", "Tamanhos (px, separados por vírgula)", "texto", "16,32,48,64,128,256")],
             sub="ícone"),
        Alvo("pdf", "imagem", pil("PDF"), op_imagem(False, True, [
            Opcao("dpi", "DPI da página", "numero", 150, minimo=36, maximo=1200)])),
    ]


ALVOS_ANIM = [
    Alvo("mp4", "imagem", conv_anim_video, sub="animação"),
    Alvo("webm", "imagem", conv_anim_video, sub="animação"),
]


def e_animada(caminho):
    try:
        from PIL import Image
        with Image.open(caminho) as im:
            return getattr(im, "n_frames", 1) > 1
    except Exception:
        return False


# ---------------------------------------------------------------- svg


def conv_svg(origens, destino, op, prog, fmt):
    import fitz
    doc = fitz.open(origens[0])
    if fmt == "PDF":
        pdf = fitz.open("pdf", doc.convert_to_pdf())
        pdf.save(destino)
        return destino
    pag = doc[0]
    larg = int(op.get("largura") or 0)
    zoom = larg / pag.rect.width if larg else float(op.get("escala", 100)) / 100
    pix = pag.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=fmt != "JPEG")
    from PIL import Image
    im = Image.open(io.BytesIO(pix.tobytes("png")))
    with tempfile.TemporaryDirectory(prefix="roda-") as tmp:
        png = os.path.join(tmp, "svg.png")
        im.save(png)
        op2 = dict(op, largura=0, altura=0, escala=100)
        return conv_imagem([png], destino, op2, prog, fmt)


def alvos_svg():
    def f(fmt):
        return lambda o, d, op, p: conv_svg(o, d, op, p, fmt)
    tam = [Opcao("largura", "Largura (px, 0 = usa a escala)", "numero", 1024, maximo=20000, passo=16),
           Opcao("escala", "Escala (%)", "numero", 100, minimo=10, maximo=2000)]
    return [Alvo("png", "svg", f("PNG"), tam),
            Alvo("jpg", "svg", f("JPEG"), tam + [Opcao("qualidade", "Qualidade", "numero", 92, minimo=1, maximo=100),
                                                  Opcao("fundo", "Fundo", "escolha", "branco", FUNDOS)]),
            Alvo("webp", "svg", f("WEBP"), tam + [Opcao("qualidade", "Qualidade", "numero", 90, minimo=1, maximo=100)]),
            Alvo("ico", "svg", f("ICO"), [Opcao("largura", "Resolução base (px)", "numero", 256, maximo=1024),
                                          Opcao("tamanhos", "Tamanhos", "texto", "16,32,48,64,128,256")]),
            Alvo("pdf", "svg", f("PDF"))]


# ---------------------------------------------------------------- áudio

AUDIO_IN = {"mp3", "wav", "ogg", "oga", "flac", "m4a", "aac", "opus", "wma", "aiff", "aif",
            "amr", "ac3", "mka", "wv", "ape", "mp2"}
TAXAS = [("", "Original"), ("22050", "22,05 kHz"), ("44100", "44,1 kHz"), ("48000", "48 kHz")]
CANAIS = [("", "Original"), ("1", "Mono"), ("2", "Estéreo")]
TAXA_BITS = [("96k", "96 kbps"), ("128k", "128 kbps"), ("160k", "160 kbps"), ("192k", "192 kbps"),
             ("256k", "256 kbps"), ("320k", "320 kbps")]

CODEC_AUDIO = {
    "mp3": ["-c:a", "libmp3lame"], "ogg": ["-c:a", "libvorbis"], "opus": ["-c:a", "libopus"],
    "m4a": ["-c:a", "aac"], "aac": ["-c:a", "aac"], "flac": ["-c:a", "flac"], "wav": ["-c:a", "pcm_s16le"],
}


def args_audio(ext, op):
    a = list(CODEC_AUDIO[ext])
    if ext not in ("flac", "wav") and op.get("bitrate"):
        a += ["-b:a", op["bitrate"]]
    if op.get("taxa"):
        a += ["-ar", op["taxa"]]
    if op.get("canais"):
        a += ["-ac", op["canais"]]
    filtros = []
    if op.get("normalizar"):
        filtros.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    vol = float(op.get("volume", 100) or 100)
    if vol != 100:
        filtros.append(f"volume={vol / 100:.2f}")
    if filtros:
        a += ["-af", ",".join(filtros)]
    return a


def conv_audio(origens, destino, op, prog):
    ext = destino.rsplit(".", 1)[1]
    if not ffprobe_tem(origens[0], "a"):
        raise ErroConversao("Esse arquivo não tem faixa de áudio.",
                            "Confira se o vídeo tem som. Sem áudio não há o que extrair.")
    corte, dur = corte_ffmpeg(op, ffprobe_duracao(origens[0]))
    prog.rodar(ffmpeg_base() + ["-i", origens[0]] + corte + ["-vn", "-map_metadata", "0"]
               + args_audio(ext, op) + [destino], duracao=dur)
    return destino


def op_audio(ext):
    ops = []
    if ext not in ("flac", "wav"):
        ops.append(Opcao("bitrate", "Qualidade (bitrate)", "escolha",
                         "192k" if ext != "opus" else "128k", TAXA_BITS))
    return ops + [
        Opcao("taxa", "Taxa de amostragem", "escolha", "", TAXAS),
        Opcao("canais", "Canais", "escolha", "", CANAIS),
        Opcao("inicio", "Cortar: início (ex. 0:30)", "texto", ""),
        Opcao("fim", "Cortar: fim (ex. 2:10)", "texto", ""),
        Opcao("volume", "Volume (%)", "numero", 100, minimo=10, maximo=400, passo=5),
        Opcao("normalizar", "Normalizar volume (loudnorm -16 LUFS)", "bool", False),
    ]


def alvos_audio(familia="audio"):
    return [Alvo(e, familia, conv_audio, op_audio(e), sub="áudio" if familia == "video" else "")
            for e in ("mp3", "wav", "ogg", "flac", "m4a", "opus")]


# ---------------------------------------------------------------- vídeo

VIDEO_IN = {"mp4", "mkv", "webm", "avi", "mov", "wmv", "flv", "m4v", "mpg", "mpeg", "3gp",
            "ts", "mts", "m2ts", "ogv", "vob"}
RESOLUCOES = [("", "Original"), ("2160", "4K (2160p)"), ("1440", "1440p"), ("1080", "1080p"),
              ("720", "720p"), ("480", "480p"), ("360", "360p")]
QUALIDADES = [("18", "Alta (arquivo grande)"), ("23", "Média"), ("28", "Baixa"), ("33", "Mínima")]
FPS = [("", "Original"), ("60", "60"), ("30", "30"), ("24", "24"), ("15", "15")]
PRESETS = [("veryfast", "Rápido"), ("medium", "Médio"), ("slow", "Lento (menor arquivo)")]


def conv_video(origens, destino, op, prog):
    ext = destino.rsplit(".", 1)[1]
    src = origens[0]
    corte, dur = corte_ffmpeg(op, ffprobe_duracao(src))
    cmd = ffmpeg_base() + ["-i", src] + corte
    if op.get("copiar"):
        cmd += ["-map", "0", "-c", "copy"]
        if op.get("sem_audio"):
            cmd += ["-an"]
        prog.rodar(cmd + [destino], duracao=dur)
        return destino
    filtros = []
    if op.get("altura"):
        filtros.append(f"scale=-2:{op['altura']}")
    else:
        filtros.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    if op.get("fps"):
        filtros.append(f"fps={op['fps']}")
    cmd += ["-vf", ",".join(filtros)]
    crf = op.get("crf", "23")
    if ext == "webm":
        cmd += ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(int(crf) + 8), "-row-mt", "1",
                "-deadline", "good", "-cpu-used", "4"]
        aud = ["-c:a", "libopus", "-b:a", "128k"]
    else:
        cmd += ["-c:v", "libx264", "-crf", str(crf), "-preset", op.get("preset", "medium"),
                "-pix_fmt", "yuv420p"]
        aud = ["-c:a", "aac", "-b:a", "160k"]
        if ext in ("mp4", "mov", "m4v"):
            cmd += ["-movflags", "+faststart"]
        if ext == "avi":
            aud = ["-c:a", "libmp3lame", "-b:a", "192k"]
    if op.get("sem_audio"):
        cmd += ["-an"]
    else:
        cmd += aud
    prog.rodar(cmd + [destino], duracao=dur)
    return destino


def conv_gif(origens, destino, op, prog):
    corte, dur = corte_ffmpeg(op, ffprobe_duracao(origens[0]))
    fps, larg = op.get("fps_gif", "15"), op.get("largura_gif", "480")
    escala = f"scale={larg}:-1:flags=lanczos," if larg else ""
    filtro = (f"fps={fps},{escala}split[a][b];[a]palettegen=stats_mode=diff[p];"
              f"[b][p]paletteuse=dither=bayer:bayer_scale=4")
    prog.rodar(ffmpeg_base() + corte + ["-i", origens[0], "-filter_complex", filtro, "-loop",
                                        "0" if op.get("repetir", True) else "-1", destino], duracao=dur)
    return destino


def conv_quadro(origens, destino, op, prog):
    t = segundos(op.get("instante")) or 0
    dur = ffprobe_duracao(origens[0]) or 0
    if dur and t >= dur:
        prog.texto(f"instante {t:g}s passa do fim ({dur:.1f}s): usei o meio do vídeo")
        t = dur / 2
    prog.rodar(ffmpeg_base() + ["-ss", str(t), "-i", origens[0], "-frames:v", "1",
                                "-q:v", "2", destino])
    return destino


def op_video(remux_padrao=False):
    return [
        Opcao("altura", "Resolução", "escolha", "", RESOLUCOES),
        Opcao("crf", "Qualidade", "escolha", "23", QUALIDADES),
        Opcao("fps", "Quadros por segundo", "escolha", "", FPS),
        Opcao("preset", "Velocidade de codificação", "escolha", "medium", PRESETS),
        Opcao("inicio", "Cortar: início (ex. 0:30)", "texto", ""),
        Opcao("fim", "Cortar: fim (ex. 2:10)", "texto", ""),
        Opcao("sem_audio", "Remover o áudio", "bool", False),
        Opcao("copiar", "Copiar sem recodificar (rápido, ignora resolução/qualidade)", "bool",
              remux_padrao),
    ]


def alvos_video():
    gif_ops = [Opcao("fps_gif", "Quadros por segundo", "escolha", "15",
                     [("10", "10"), ("15", "15"), ("20", "20"), ("25", "25")]),
               Opcao("largura_gif", "Largura", "escolha", "480",
                     [("320", "320 px"), ("480", "480 px"), ("640", "640 px"), ("800", "800 px"), ("", "Original")]),
               Opcao("inicio", "Cortar: início", "texto", ""),
               Opcao("fim", "Cortar: fim", "texto", ""),
               Opcao("repetir", "Repetir em loop", "bool", True)]
    return [
        Alvo("mp4", "video", conv_video, op_video()),
        Alvo("mkv", "video", conv_video, op_video(True)),
        Alvo("webm", "video", conv_video, op_video()),
        Alvo("mov", "video", conv_video, op_video()),
        Alvo("avi", "video", conv_video, op_video()),
        Alvo("gif", "video", conv_gif, gif_ops, sub="animado"),
        Alvo("jpg", "video", conv_quadro, [Opcao("instante", "Instante do quadro (ex. 0:05)", "texto", "1")],
             rotulo="JPG", sub="1 quadro"),
    ] + [a for a in alvos_audio("video") if a.ext in ("mp3", "wav", "m4a")]


# ---------------------------------------------------------------- pdf


def paginas(spec, total):
    spec = (spec or "").strip()
    if not spec or spec.lower() in ("todas", "tudo", "*"):
        return list(range(total))
    out = []
    for parte in spec.split(","):
        parte = parte.strip()
        if not parte:
            continue
        try:
            if "-" in parte:
                a, b = parte.split("-", 1)
                out += range(int(a) - 1, min(int(b or total), total))
            else:
                out.append(int(parte) - 1)
        except ValueError:
            raise ErroConversao(f"Páginas '{spec}' inválidas.", "Use algo como: 1-3,5,8-")
    out = [p for p in out if 0 <= p < total]
    if not out:
        raise ErroConversao(f"Nenhuma página válida em '{spec}' (o PDF tem {total}).",
                            "Ajuste o intervalo de páginas no ⚙.")
    return out


def abrir_pdf(caminho):
    import fitz
    try:
        doc = fitz.open(caminho)
    except Exception as e:
        raise ErroConversao("Não consegui abrir o PDF (corrompido?).",
                            "Abra num leitor de PDF para conferir.", str(e))
    if doc.needs_pass:
        raise ErroConversao("PDF protegido por senha.", "Remova a senha do PDF antes de converter.")
    return doc


def arquivos_por_pagina(destino, ext, pgs):
    """Uma página = o próprio destino; várias = pasta `nome/` com pagina-001.ext..."""
    if len(pgs) == 1:
        return [destino]
    base = destino[: -len(ext) - 1]
    pasta = base
    n = 1
    while os.path.exists(pasta):
        pasta = f"{base} ({n})"
        n += 1
    os.makedirs(pasta)
    return [os.path.join(pasta, f"pagina-{p + 1:03d}.{ext}") for p in pgs]


def conv_pdf_svg(origens, destino, op, prog):
    doc = abrir_pdf(origens[0])
    pgs = paginas(op.get("paginas"), len(doc))
    alvos = arquivos_por_pagina(destino, "svg", pgs)
    for i, (p, d) in enumerate(zip(pgs, alvos)):
        prog.checar()
        prog.texto(f"página {p + 1} de {len(doc)}")
        with open(d, "w", encoding="utf-8") as f:
            f.write(doc[p].get_svg_image(text_as_path=bool(op.get("texto_curva", True))))
        prog.fracao((i + 1) / len(pgs))
    return alvos[0] if len(alvos) == 1 else os.path.dirname(alvos[0])


def conv_pdf_tiff(origens, destino, op, prog):
    """Um .tiff só com todas as páginas (multipágina), o formato de fax/arquivo."""
    import fitz
    from PIL import Image
    doc = abrir_pdf(origens[0])
    pgs = paginas(op.get("paginas"), len(doc))
    zoom = float(op.get("dpi", 150)) / 72
    ims = []
    for i, p in enumerate(pgs):
        prog.checar()
        prog.texto(f"página {p + 1} de {len(doc)}")
        pix = doc[p].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        ims.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        prog.fracao((i + 1) / (len(pgs) + 1))
    ims[0].save(destino, "TIFF", save_all=True, append_images=ims[1:], compression="tiff_lzw",
                dpi=(zoom * 72, zoom * 72))
    return destino


def conv_pdf_imagem(origens, destino, op, prog, fmt):
    import fitz
    doc = abrir_pdf(origens[0])
    pgs = paginas(op.get("paginas"), len(doc))
    zoom = float(op.get("dpi", 150)) / 72
    ext = destino.rsplit(".", 1)[1]
    if op.get("unir") and len(pgs) > 1:
        return pdf_imagem_unica(doc, pgs, zoom, destino, op, prog, fmt)
    alvos = arquivos_por_pagina(destino, ext, pgs)
    for i, (p, d) in enumerate(zip(pgs, alvos)):
        prog.checar()
        prog.texto(f"página {p + 1} de {len(doc)}")
        pix = doc[p].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        if fmt == "PNG":
            pix.save(d)
        else:
            from PIL import Image
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            kw = {"quality": int(op.get("qualidade", 90))} if fmt in ("JPEG", "WEBP") else {}
            im.save(d, fmt, **kw)
        prog.fracao((i + 1) / len(pgs))
    return alvos[0] if len(alvos) == 1 else os.path.dirname(alvos[0])


LIMITE_LADO = {"JPEG": 65500, "WEBP": 16383, "PNG": 300000}
LIMITE_PIXELS = 150e6   # ~450 MB em RGB; acima disso reduz o DPI pra não derrubar o PC


def pdf_imagem_unica(doc, pgs, zoom, destino, op, prog, fmt):
    """Todas as páginas emendadas numa imagem só (em coluna ou em linha)."""
    import fitz
    from PIL import Image
    vertical = op.get("direcao", "vertical") == "vertical"
    espaco = int(op.get("espaco", 0))
    rects = [doc[p].rect for p in pgs]

    def medidas(z):
        ws = [round(r.width * z) for r in rects]
        hs = [round(r.height * z) for r in rects]
        folga = espaco * (len(pgs) - 1)
        return (max(ws), sum(hs) + folga) if vertical else (sum(ws) + folga, max(hs))

    W, H = medidas(zoom)
    f = min(1.0, LIMITE_LADO.get(fmt, 65500) / max(W, H), math.sqrt(LIMITE_PIXELS / (W * H)))
    if f < 1:
        zoom *= f * 0.995
        W, H = medidas(zoom)
        prog.texto(f"imagem grande demais: baixei para {zoom * 72:.0f} DPI")
    base = Image.new("RGB", (W, H), COR_FUNDO.get(op.get("fundo"), (255, 255, 255)))
    pos = 0
    for i, p in enumerate(pgs):
        prog.checar()
        pix = doc[p].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if vertical:
            base.paste(im, ((W - im.width) // 2, pos))
            pos += im.height + espaco
        else:
            base.paste(im, (pos, (H - im.height) // 2))
            pos += im.width + espaco
        prog.fracao((i + 1) / (len(pgs) + 1))
    prog.texto(f"{len(pgs)} páginas → {W}×{H} px, gravando…")
    kw = {"quality": int(op.get("qualidade", 90))} if fmt in ("JPEG", "WEBP") else {"optimize": False}
    base.save(destino, fmt, **kw)
    return destino


def conv_pdf_texto(origens, destino, op, prog):
    doc = abrir_pdf(origens[0])
    pgs = paginas(op.get("paginas"), len(doc))
    modo = "html" if destino.endswith(".html") else "text"
    partes = []
    for i, p in enumerate(pgs):
        prog.checar()
        partes.append(doc[p].get_text(modo))
        prog.fracao((i + 1) / len(pgs))
    if modo == "html":
        corpo = "\n".join(partes)
        txt = f"<!doctype html><meta charset='utf-8'><title>{html.escape(separar_ext(origens[0])[0])}</title>\n{corpo}"
    else:
        txt = "\n\f\n".join(partes) if op.get("quebra_pagina") else "\n\n".join(partes)
        if not txt.strip():
            raise ErroConversao("O PDF não tem texto selecionável (é imagem escaneada).",
                                "Precisa de OCR. Instale com: sudo apt install ocrmypdf "
                                "e rode: ocrmypdf entrada.pdf saida.pdf")
    with open(destino, "w", encoding="utf-8") as f:
        f.write(txt)
    return destino


def conv_pdf_md(origens, destino, op, prog):
    doc = abrir_pdf(origens[0])
    pgs = paginas(op.get("paginas"), len(doc))
    linhas = []
    for p in pgs:
        prog.checar()
        for bloco in doc[p].get_text("dict")["blocks"]:
            for ln in bloco.get("lines", []):
                spans = ln["spans"]
                txt = "".join(s["text"] for s in spans).strip()
                if not txt:
                    continue
                tam = max(s["size"] for s in spans)
                negrito = all(s["flags"] & 16 for s in spans)
                if tam >= 18:
                    linhas.append(f"\n# {txt}\n")
                elif tam >= 14 or (negrito and len(txt) < 80):
                    linhas.append(f"\n## {txt}\n")
                else:
                    linhas.append(txt)
            linhas.append("")
    with open(destino, "w", encoding="utf-8") as f:
        f.write(re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip() + "\n")
    return destino


def conv_pdf_comprimir(origens, destino, op, prog):
    prog.texto("ghostscript comprimindo…")
    prog.rodar(["gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.6", f"-dPDFSETTINGS=/{op.get('nivel', 'ebook')}",
                "-dNOPAUSE", "-dQUIET", "-dBATCH", f"-sOutputFile={destino}", origens[0]], timeout=600)
    antes, depois = os.path.getsize(origens[0]), os.path.getsize(destino)
    prog.texto(f"{antes / 1e6:.1f} MB → {depois / 1e6:.1f} MB")
    return destino


def op_pdf_imagem(unir, qualidade):
    ops = [Opcao("dpi", "Resolução (DPI)", "numero", 150, minimo=36, maximo=600, passo=10),
           Opcao("paginas", "Páginas (vazio = todas; ex. 1-3,5)", "texto", ""),
           Opcao("unir", "Juntar todas as páginas numa imagem só", "bool", unir),
           Opcao("direcao", "Juntar em", "escolha", "vertical",
                 [("vertical", "Coluna (uma embaixo da outra)"), ("horizontal", "Linha (lado a lado)")]),
           Opcao("espaco", "Espaço entre páginas (px)", "numero", 20 if unir else 0, minimo=0, maximo=400),
           Opcao("fundo", "Cor do espaço", "escolha", "cinza" if unir else "branco", FUNDOS)]
    if qualidade:
        ops.append(Opcao("qualidade", "Qualidade", "numero", 90, minimo=1, maximo=100))
    return ops


def alvos_pdf():
    pgs = Opcao("paginas", "Páginas (vazio = todas; ex. 1-3,5)", "texto", "")
    png = lambda o, d, op, p: conv_pdf_imagem(o, d, op, p, "PNG")
    jpg = lambda o, d, op, p: conv_pdf_imagem(o, d, op, p, "JPEG")
    webp = lambda o, d, op, p: conv_pdf_imagem(o, d, op, p, "WEBP")
    return [
        Alvo("png", "pdf", png, op_pdf_imagem(False, False), sub="páginas"),
        Alvo("jpg", "pdf", jpg, op_pdf_imagem(False, True), sub="páginas"),
        Alvo("png", "pdf", png, op_pdf_imagem(True, False), sub="1 imagem"),
        Alvo("jpg", "pdf", jpg, op_pdf_imagem(True, True), sub="1 imagem"),
        Alvo("txt", "pdf", conv_pdf_texto, [pgs, Opcao("quebra_pagina", "Marcar quebra de página (\\f)", "bool", False)]),
        Alvo("md", "pdf", conv_pdf_md, [pgs], sub="aproximado"),
        Alvo("html", "pdf", conv_pdf_texto, [pgs], extra=True),
        Alvo("docx", "pdf", conv_office, [], sub="LibreOffice"),
        Alvo("pdf", "pdf", conv_pdf_comprimir, [Opcao("nivel", "Nível", "escolha", "ebook", [
            ("screen", "Máximo (72 dpi, tela)"), ("ebook", "Médio (150 dpi)"),
            ("printer", "Leve (300 dpi, impressão)")])], rotulo="PDF", sub="comprimir"),
        # extras: 2ª roda
        Alvo("webp", "pdf", webp, op_pdf_imagem(False, True), sub="páginas", extra=True),
        Alvo("webp", "pdf", webp, op_pdf_imagem(True, True), sub="1 imagem", extra=True),
        Alvo("svg", "pdf", conv_pdf_svg, [pgs, Opcao("texto_curva", "Texto como curvas (fiel, não editável)",
                                                     "bool", True)], sub="vetor", extra=True),
        Alvo("tiff", "pdf", conv_pdf_tiff, [Opcao("dpi", "Resolução (DPI)", "numero", 200, minimo=36, maximo=600,
                                                  passo=10), pgs], sub="multipágina", extra=True),
        Alvo("bmp", "pdf", lambda o, d, op, p: conv_pdf_imagem(o, d, op, p, "BMP"), op_pdf_imagem(False, False),
             sub="páginas", extra=True),
    ]


# ---------------------------------------------------------------- texto, markdown, html

TEXTO_IN = {"txt", "text", "log", "md", "markdown", "html", "htm", "rst"}

CSS_DOC = """
body { font-family: sans-serif; font-size: %(fonte)spt; line-height: 1.4; }
h1 { font-size: 1.8em; } h2 { font-size: 1.4em; } h3 { font-size: 1.15em; }
pre, code { font-family: monospace; font-size: 0.9em; background-color: #f2f2f2; }
blockquote { color: #555; margin-left: 12pt; }
table { border-collapse: collapse; } td, th { border: 1px solid #999; padding: 3pt; }
"""


def ler_texto(caminho):
    with open(caminho, "rb") as f:
        dados = f.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return dados.decode(enc).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    return dados.decode("utf-8", "replace")


def texto_para_html(txt):
    pars = [p for p in re.split(r"\n\s*\n", txt) if p.strip()]
    return "\n".join("<p>" + html.escape(p).replace("\n", "<br>") + "</p>" for p in pars)


def md_para_html(txt):
    import markdown
    return markdown.markdown(txt, extensions=["extra", "sane_lists", "toc"])


class _Html2Texto(HTMLParser):
    """HTML -> texto ou markdown simples (h1-h6, p, listas, links, ênfase, código)."""

    def __init__(self, md):
        super().__init__(convert_charrefs=True)
        self.md, self.out, self.href, self.pre, self.pular = md, [], [], 0, 0
        self.lista = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "head"):
            self.pular += 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("\n\n" + ("#" * int(tag[1]) + " " if self.md else ""))
        elif tag in ("p", "div", "section", "article", "table", "blockquote"):
            self.out.append("\n\n" + ("> " if tag == "blockquote" and self.md else ""))
        elif tag in ("br", "tr"):
            self.out.append("\n")
        elif tag in ("ul", "ol"):
            self.lista.append([tag, 0])
        elif tag == "li":
            n = self.lista[-1] if self.lista else ["ul", 0]
            n[1] += 1
            marca = f"{n[1]}. " if n[0] == "ol" else ("- " if self.md else "• ")
            self.out.append("\n" + "  " * max(0, len(self.lista) - 1) + marca)
        elif tag in ("strong", "b") and self.md:
            self.out.append("**")
        elif tag in ("em", "i") and self.md:
            self.out.append("*")
        elif tag == "code" and self.md and not self.pre:
            self.out.append("`")
        elif tag == "pre":
            self.pre += 1
            self.out.append("\n\n```\n" if self.md else "\n\n")
        elif tag == "a":
            self.href.append(a.get("href"))
            if self.md and a.get("href"):
                self.out.append("[")
        elif tag == "img" and self.md:
            self.out.append(f"![{a.get('alt', '')}]({a.get('src', '')})")
        elif tag in ("td", "th"):
            self.out.append(" | " if self.md else "\t")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.pular = max(0, self.pular - 1)
        elif tag in ("strong", "b") and self.md:
            self.out.append("**")
        elif tag in ("em", "i") and self.md:
            self.out.append("*")
        elif tag == "code" and self.md and not self.pre:
            self.out.append("`")
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
            self.out.append("\n```\n\n" if self.md else "\n\n")
        elif tag == "a":
            h = self.href.pop() if self.href else None
            if self.md and h:
                self.out.append(f"]({h})")
        elif tag in ("ul", "ol"):
            if self.lista:
                self.lista.pop()
            self.out.append("\n")

    def handle_data(self, data):
        if self.pular:
            return
        self.out.append(data if self.pre else re.sub(r"\s+", " ", data))

    def resultado(self):
        t = "".join(self.out)
        t = re.sub(r"[ \t]+\n", "\n", t)
        return re.sub(r"\n{3,}", "\n\n", t).strip() + "\n"


def html_para(txt, md):
    p = _Html2Texto(md)
    p.feed(txt)
    return p.resultado()


def como_html(origem):
    """Lê txt/md/html e devolve (corpo html, título)."""
    base, ext = separar_ext(origem)
    txt = ler_texto(origem)
    if ext in ("md", "markdown", "rst"):
        return md_para_html(txt), base
    if ext in ("html", "htm"):
        m = re.search(r"<body[^>]*>(.*)</body>", txt, re.S | re.I)
        return (m.group(1) if m else txt), base
    return texto_para_html(txt), base


def html_para_pdf(corpo, destino, op, prog):
    import fitz
    tam = {"a4": fitz.paper_rect("a4"), "carta": fitz.paper_rect("letter"),
           "a5": fitz.paper_rect("a5")}[op.get("pagina", "a4")]
    m = float(op.get("margem", 20)) * 72 / 25.4
    story = fitz.Story(html=corpo, user_css=CSS_DOC % {"fonte": op.get("fonte", 11)})
    escritor = fitz.DocumentWriter(destino)
    mais, n = True, 0
    while mais:
        prog.checar()
        disp = escritor.begin_page(tam)
        mais, _ = story.place(tam + (m, m, -m, -m))
        story.draw(disp)
        escritor.end_page()
        n += 1
        prog.texto(f"página {n}")
    escritor.close()
    return destino


def conv_texto(origens, destino, op, prog):
    src = origens[0]
    _, ext_in = separar_ext(src)
    ext = destino.rsplit(".", 1)[1]
    txt = ler_texto(src)
    eh_md = ext_in in ("md", "markdown", "rst")
    eh_html = ext_in in ("html", "htm")
    if ext == "pdf":
        corpo, _ = como_html(src)
        return html_para_pdf(corpo, destino, op, prog)
    if ext in ("docx", "odt", "rtf"):
        corpo, titulo = como_html(src)
        with tempfile.TemporaryDirectory(prefix="roda-") as tmp:
            h = os.path.join(tmp, separar_ext(destino)[0] + ".html")
            with open(h, "w", encoding="utf-8") as f:
                f.write(f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(titulo)}</title>"
                        f"</head><body>{corpo}</body></html>")
            return conv_office([h], destino, op, prog, filtro_in="HTML (StarWriter)")
    if ext == "html":
        corpo, titulo = como_html(src)
        saida = (f"<!doctype html>\n<html lang='pt-BR'><head><meta charset='utf-8'>\n"
                 f"<title>{html.escape(titulo)}</title>\n<style>{CSS_DOC % {'fonte': 12}}"
                 f"body{{max-width:46em;margin:2em auto;padding:0 1em}}</style></head>\n"
                 f"<body>\n{corpo}\n</body></html>\n")
    elif ext == "md":
        if eh_html:
            saida = html_para(txt, md=True)
        else:
            saida = txt if txt.endswith("\n") else txt + "\n"
            if op.get("titulo"):
                saida = f"# {separar_ext(src)[0]}\n\n" + saida
    elif ext == "txt":
        if eh_html:
            saida = html_para(txt, md=False)
        elif eh_md:
            saida = html_para(md_para_html(txt), md=False)
        else:
            saida = txt
    else:
        raise ErroConversao(f"Conversão de texto para .{ext} não implementada.")
    with open(destino, "w", encoding="utf-8") as f:
        f.write(saida)
    prog.fracao(1)
    return destino


def alvos_texto(ext_in):
    pdf_ops = [Opcao("pagina", "Tamanho da página", "escolha", "a4",
                     [("a4", "A4"), ("carta", "Carta"), ("a5", "A5")]),
               Opcao("fonte", "Tamanho da fonte (pt)", "numero", 11, minimo=6, maximo=32),
               Opcao("margem", "Margem (mm)", "numero", 20, minimo=0, maximo=60)]
    md_ops = [Opcao("titulo", "Pôr o nome do arquivo como título #", "bool", False)]
    todos = [Alvo("md", "texto", conv_texto, md_ops), Alvo("txt", "texto", conv_texto),
             Alvo("html", "texto", conv_texto), Alvo("pdf", "texto", conv_texto, pdf_ops),
             Alvo("docx", "texto", conv_texto, sub="Word"), Alvo("odt", "texto", conv_texto, sub="Writer")]
    mesma = {"markdown": "md", "htm": "html", "text": "txt", "log": "txt"}.get(ext_in, ext_in)
    return [a for a in todos if a.ext != mesma]


# ---------------------------------------------------------------- office (LibreOffice)

DOC_IN = {"docx", "doc", "odt", "rtf", "wpd", "pages"}
PLAN_IN = {"xlsx", "xls", "ods", "xlsm"}
APRES_IN = {"pptx", "ppt", "odp", "pps", "ppsx"}

FILTRO_SAIDA = {
    "pdf": "pdf", "docx": 'docx:"MS Word 2007 XML"', "odt": "odt", "rtf": "rtf",
    "txt": "txt:Text (encoded):UTF8", "html": "html", "xlsx": 'xlsx:"Calc MS Excel 2007 XML"',
    "ods": "ods", "csv": "csv:Text - txt - csv (StarCalc):44,34,76,1", "pptx": "pptx", "odp": "odp",
    "doc": 'doc:"MS Word 97"', "xls": 'xls:"MS Excel 97"', "png": "png",
}


def conv_office(origens, destino, op, prog, filtro_in=None):
    if not shutil.which("soffice"):
        raise ErroConversao("LibreOffice não está instalado.", "Instale com:\n  sudo apt install libreoffice")
    ext = destino.rsplit(".", 1)[1]
    filtro = FILTRO_SAIDA.get(ext, ext).replace('"', "")
    src = origens[0]
    if src.lower().endswith(".pdf"):
        filtro_in = "writer_pdf_import"
    with tempfile.TemporaryDirectory(prefix="roda-lo-") as tmp:
        perfil = f"file://{tmp}/perfil"   # perfil próprio: não briga com um LibreOffice aberto
        cmd = ["soffice", f"-env:UserInstallation={perfil}", "--headless", "--norestore"]
        if filtro_in:
            cmd.append(f"--infilter={filtro_in}")
        cmd += ["--convert-to", filtro, "--outdir", tmp, src]
        prog.texto("LibreOffice convertendo…")
        prog.fracao(0.3)
        prog.rodar(cmd, timeout=300)
        gerado = os.path.join(tmp, separar_ext(src)[0] + "." + ext)
        if not os.path.exists(gerado):
            outros = [f for f in os.listdir(tmp) if f != "perfil"]
            if len(outros) == 1:
                gerado = os.path.join(tmp, outros[0])
            else:
                raise ErroConversao("O LibreOffice não gerou o arquivo de saída.",
                                    "Esse tipo de documento talvez não converta para ." + ext +
                                    ". Tente PDF, ou abra no LibreOffice e use 'Salvar como'.")
        shutil.move(gerado, destino)
    return destino


def alvos_office(ext_in):
    if ext_in in DOC_IN:
        exts = ["pdf", "docx", "odt", "rtf", "txt", "html", "doc"]
    elif ext_in in PLAN_IN:
        exts = ["pdf", "xlsx", "ods", "csv", "html", "xls"]
    else:
        exts = ["pdf", "pptx", "odp", "png"]
    subs = {"png": "1º slide", "csv": "1ª aba", "doc": "Word 97", "xls": "Excel 97"}
    return [Alvo(e, "office", conv_office, sub=subs.get(e, "")) for e in exts if e != ext_in]


# ---------------------------------------------------------------- dados (json, yaml, csv)

DADOS_IN = {"json", "yaml", "yml", "csv", "tsv", "toml"}


def ler_dados(caminho):
    _, ext = separar_ext(caminho)
    txt = ler_texto(caminho)
    try:
        if ext == "json":
            return json.loads(txt)
        if ext in ("yaml", "yml"):
            import yaml
            return yaml.safe_load(txt)
        if ext == "toml":
            import tomllib
            return tomllib.loads(txt)
        delim = "\t" if ext == "tsv" else None
        if delim is None:
            try:
                delim = csv.Sniffer().sniff(txt[:4096], delimiters=",;\t|").delimiter
            except csv.Error:
                delim = ","
        return list(csv.DictReader(io.StringIO(txt), delimiter=delim))
    except ErroConversao:
        raise
    except Exception as e:
        raise ErroConversao(f"O .{ext} tem erro de sintaxe.",
                            "Abra no editor e corrija a linha indicada nos detalhes.", str(e))


def conv_dados(origens, destino, op, prog):
    dados = ler_dados(origens[0])
    ext = destino.rsplit(".", 1)[1]
    if ext in ("xlsx", "ods"):
        with tempfile.TemporaryDirectory(prefix="roda-") as tmp:
            c = os.path.join(tmp, separar_ext(destino)[0] + ".csv")
            escrever_csv(dados, c, ",")
            return conv_office([c], destino, op, prog, filtro_in="CSV:44,34,76")
    if ext == "json":
        saida = json.dumps(dados, ensure_ascii=False, indent=int(op.get("indent", 2)) or None) + "\n"
    elif ext in ("yaml", "yml"):
        import yaml
        saida = yaml.safe_dump(dados, allow_unicode=True, sort_keys=False)
    elif ext in ("csv", "tsv"):
        escrever_csv(dados, destino, "\t" if ext == "tsv" else op.get("delim", ","))
        return destino
    else:
        raise ErroConversao(f"Saída .{ext} não suportada para dados.")
    with open(destino, "w", encoding="utf-8") as f:
        f.write(saida)
    return destino


def escrever_csv(dados, destino, delim):
    if isinstance(dados, dict):
        # {"chave": [..]} com uma única lista vira a lista; senão, uma linha só
        listas = [v for v in dados.values() if isinstance(v, list)]
        dados = listas[0] if len(listas) == 1 else [dados]
    if not isinstance(dados, list) or not all(isinstance(x, dict) for x in dados):
        raise ErroConversao("Esses dados não são uma tabela (lista de objetos).",
                            "CSV/planilha só sai de uma lista de objetos, ex.: [{\"nome\":..}, ..]. "
                            "Use JSON ou YAML como saída.")
    colunas = []
    for linha in dados:
        for k in linha:
            if k not in colunas:
                colunas.append(k)
    with open(destino, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=colunas, delimiter=delim)
        w.writeheader()
        for linha in dados:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                        for k, v in linha.items()})


def alvos_dados(ext_in):
    exts = ["json", "yaml", "csv", "tsv", "xlsx", "ods"]
    mesma = {"yml": "yaml"}.get(ext_in, ext_in)
    ops = {"json": [Opcao("indent", "Indentação (0 = compacto)", "numero", 2, minimo=0, maximo=8)],
           "csv": [Opcao("delim", "Separador", "escolha", ",", [(",", "Vírgula"), (";", "Ponto e vírgula"),
                                                                  ("|", "Barra |")])]}
    return [Alvo(e, "dados", conv_dados, ops.get(e, []), sub="planilha" if e in ("xlsx", "ods") else "")
            for e in exts if e != mesma]


# ---------------------------------------------------------------- legenda

LEGENDA_IN = {"srt", "vtt", "ass", "ssa"}


def conv_legenda(origens, destino, op, prog):
    prog.rodar(ffmpeg_base() + ["-sub_charenc", op.get("encoding", "UTF-8"), "-i", origens[0], destino])
    return destino


def alvos_legenda(ext_in):
    ops = [Opcao("encoding", "Codificação da entrada", "escolha", "UTF-8",
                 [("UTF-8", "UTF-8"), ("CP1252", "Windows-1252 (legenda antiga BR)"), ("ISO-8859-1", "Latin-1")])]
    return [Alvo(e, "legenda", conv_legenda, ops) for e in ("srt", "vtt", "ass") if e != ext_in.replace("ssa", "ass")]


# ---------------------------------------------------------------- fontes (recursos)

FONTE_IN = {"ttf", "otf", "woff", "woff2"}


def conv_fonte(origens, destino, op, prog):
    from fontTools.ttLib import TTFont
    ext = destino.rsplit(".", 1)[1]
    try:
        f = TTFont(origens[0])
    except Exception as e:
        raise ErroConversao("Não consegui ler a fonte.", "Arquivo de fonte corrompido ou não suportado.", str(e))
    tem_cff = "CFF " in f or "CFF2" in f
    if ext == "ttf" and tem_cff:
        raise ErroConversao("Essa fonte é CFF (contornos PostScript); virar .ttf exige converter as curvas.",
                            "Use .otf como saída (mesmo conteúdo), ou woff/woff2 para web.")
    if ext == "otf" and not tem_cff:
        raise ErroConversao("Essa fonte é TrueType; .otf com contornos TrueType só muda o nome.",
                            "Use .ttf como saída, ou woff/woff2 para web.")
    f.flavor = ext if ext in ("woff", "woff2") else None
    f.save(destino)
    return destino


def alvos_fonte(ext_in):
    return [Alvo(e, "fonte", conv_fonte, sub="web" if e.startswith("woff") else "")
            for e in ("ttf", "otf", "woff", "woff2") if e != ext_in]


# ---------------------------------------------------------------- pacotes e pastas

PACOTE_IN = {"zip", "tar", "tar.gz", "tar.xz", "tar.bz2"}
MODO_TAR = {"tar": "w", "tar.gz": "w:gz", "tar.xz": "w:xz", "tar.bz2": "w:bz2"}


def _arquivos_de(origem):
    """[(caminho real, nome no pacote)] de uma pasta ou de um arquivo."""
    origem = origem.rstrip("/")
    raiz = os.path.basename(origem)
    if os.path.isfile(origem):
        return [(origem, raiz)]
    out = []
    for d, _, fs in os.walk(origem):
        for f in fs:
            p = os.path.join(d, f)
            out.append((p, os.path.join(raiz, os.path.relpath(p, origem))))
    return out


def empacotar(itens, destino, ext, prog):
    total = max(1, len(itens))
    if ext == "zip":
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for i, (p, nome) in enumerate(itens):
                prog.checar()
                z.write(p, nome)
                prog.fracao((i + 1) / total)
    else:
        with tarfile.open(destino, MODO_TAR[ext]) as t:
            for i, (p, nome) in enumerate(itens):
                prog.checar()
                t.add(p, nome, recursive=False)
                prog.fracao((i + 1) / total)
    return destino


def conv_pasta(origens, destino, op, prog):
    ext = separar_ext(destino)[1]
    itens = []
    for o in origens:
        itens += _arquivos_de(o)
    return empacotar(itens, destino, ext, prog)


def conv_pacote(origens, destino, op, prog):
    src = origens[0]
    ext = separar_ext(destino)[1]
    with tempfile.TemporaryDirectory(prefix="roda-") as tmp:
        prog.texto("extraindo…")
        try:
            if zipfile.is_zipfile(src):
                with zipfile.ZipFile(src) as z:
                    z.extractall(tmp)
            else:
                with tarfile.open(src) as t:
                    t.extractall(tmp, filter="data")
        except (zipfile.BadZipFile, tarfile.TarError, EOFError) as e:
            raise ErroConversao("Pacote corrompido ou protegido por senha.",
                                "Teste abrir no gerenciador de pacotes. Zip com senha não é suportado.", str(e))
        itens = []
        for d, _, fs in os.walk(tmp):
            for f in fs:
                p = os.path.join(d, f)
                itens.append((p, os.path.relpath(p, tmp)))
        prog.texto("empacotando…")
        return empacotar(itens, destino, ext, prog)


def alvos_pacote(ext_in, pasta=False):
    exts = ["zip", "tar.gz", "tar.xz", "tar.bz2", "tar"]
    func = conv_pasta if pasta else conv_pacote
    return [Alvo(e, "pacote", func, rotulo=e.upper(), sub="compactar" if pasta else "")
            for e in exts if e != ext_in]


# ---------------------------------------------------------------- juntar (vários arquivos, uma saída)
#
# Alvo(junta=True): recebe TODAS as origens e gera um arquivo só. A roda mostra esses alvos
# atrás da pétala "⧉ JUNTAR" quando há 2+ arquivos selecionados.

FUNDOS_MONT = FUNDOS + [("transparente", "Transparente")]


def _ordenar(origens, op):
    if op.get("ordem") == "nome":
        return sorted(origens, key=lambda c: os.path.basename(c).lower())
    return list(origens)  # ordem da seleção


def _imagens(origens, op):
    ims = []
    for o in _ordenar(origens, op):
        im = abrir_imagem(o)
        ims.append(im.convert("RGBA"))
    return ims


def _fundo_rgba(nome):
    if nome == "transparente":
        return (0, 0, 0, 0)
    return COR_FUNDO.get(nome, (255, 255, 255)) + (255,)


def _salvar_rgba(im, destino, fundo):
    ext = destino.rsplit(".", 1)[1].lower()
    if ext in ("jpg", "jpeg"):
        achatar(im, "branco" if fundo == "transparente" else fundo).save(destino, "JPEG", quality=92)
    else:
        im.save(destino, "PNG", optimize=True)
    return destino


def conv_montagem(origens, destino, op, prog):
    """Lado a lado / empilhado / grade, com mesma altura (ou largura) e espaço entre as peças."""
    from PIL import Image
    ims = _imagens(origens, op)
    n = len(ims)
    layout = op.get("layout", "horizontal")
    colunas = {"horizontal": n, "vertical": 1}.get(layout) or int(op.get("colunas") or 0) \
        or math.ceil(math.sqrt(n))
    colunas = max(1, min(colunas, n))
    linhas = math.ceil(n / colunas)
    lado = int(op.get("tamanho") or 0)
    mediana = lambda vs: sorted(vs)[len(vs) // 2]  # nem a menor (encolhe tudo) nem a maior (estica)
    if layout == "vertical":  # empilhado: todas com a mesma largura
        alvo_w = lado or mediana([im.width for im in ims])
        ims = [im.resize((alvo_w, max(1, round(im.height * alvo_w / im.width))), Image.LANCZOS)
               for im in ims]
    else:                     # lado a lado / grade: todas com a mesma altura
        alvo_h = lado or mediana([im.height for im in ims])
        ims = [im.resize((max(1, round(im.width * alvo_h / im.height)), alvo_h), Image.LANCZOS)
               for im in ims]
    esp = int(op.get("espaco") or 0)
    cel_w, cel_h = max(im.width for im in ims), max(im.height for im in ims)
    if layout == "horizontal":
        W = sum(im.width for im in ims) + esp * (n + 1)
        H = cel_h + 2 * esp
    elif layout == "vertical":
        W = cel_w + 2 * esp
        H = sum(im.height for im in ims) + esp * (n + 1)
    else:
        W = colunas * cel_w + esp * (colunas + 1)
        H = linhas * cel_h + esp * (linhas + 1)
    tela = Image.new("RGBA", (W, H), _fundo_rgba(op.get("fundo", "branco")))
    x = y = esp
    for i, im in enumerate(ims):
        prog.checar()
        if layout == "horizontal":
            tela.alpha_composite(im, (x, esp + (cel_h - im.height) // 2))
            x += im.width + esp
        elif layout == "vertical":
            tela.alpha_composite(im, (esp + (cel_w - im.width) // 2, y))
            y += im.height + esp
        else:
            c, l = i % colunas, i // colunas
            cx = esp + c * (cel_w + esp) + (cel_w - im.width) // 2
            cy = esp + l * (cel_h + esp) + (cel_h - im.height) // 2
            tela.alpha_composite(im, (cx, cy))
        prog.fracao((i + 1) / n)
    return _salvar_rgba(tela, destino, op.get("fundo", "branco"))


def conv_misturar(origens, destino, op, prog):
    """Funde as imagens no tamanho da primeira: média, clarear (screen), multiplicar ou diferença."""
    from PIL import Image, ImageChops
    ims = _imagens(origens, op)
    base = ims[0]
    ims = [base] + [im.resize(base.size, Image.LANCZOS) for im in ims[1:]]
    modo = op.get("modo", "media")
    if modo == "media":
        out = ims[0]
        for i, im in enumerate(ims[1:], start=2):
            out = Image.blend(out, im, 1.0 / i)  # média acumulada: todas pesam igual
            prog.fracao(i / len(ims))
    elif modo == "sobrepor":
        alfa = int(op.get("opacidade") or 50) / 100
        out = ims[0]
        for im in ims[1:]:
            out = Image.blend(out, im, alfa)
    else:
        f = {"clarear": ImageChops.screen, "multiplicar": ImageChops.multiply,
             "diferenca": ImageChops.difference}[modo]
        rgb = [im.convert("RGB") for im in ims]
        out = rgb[0]
        for im in rgb[1:]:
            out = f(out, im)
        out = out.convert("RGBA")
    return _salvar_rgba(out, destino, "branco")


def _res(op, ims_ou_none=None):
    r = op.get("resolucao", "1920x1080")
    w, h = (int(v) for v in r.split("x"))
    return w, h


def conv_slideshow(origens, destino, op, prog, audio=None):
    """Imagens viram vídeo: cada uma N s, encaixada na resolução (barras na cor do fundo), fade opcional."""
    imgs = [o for o in _ordenar(origens, op) if familia_de(o) in ("imagem", "svg")]
    if audio is None:
        auds = [o for o in origens if familia_de(o) == "audio"]
        audio = auds[0] if auds else None
    w, h = _res(op)
    fps = int(op.get("fps") or 30)
    fade = float(op.get("fade") or 0)
    if audio and op.get("ajustar_musica", True):
        total_audio = ffprobe_duracao(audio) or 0
        dur = max(0.5, total_audio / len(imgs)) if total_audio else float(op.get("duracao") or 3)
    else:
        dur = float(op.get("duracao") or 3)
    cor = {"preto": "black", "branco": "white", "cinza": "gray"}.get(op.get("fundo", "preto"), "black")
    tmp = tempfile.mkdtemp(prefix="roda-slide-")
    try:
        # normaliza tudo pra PNG (HEIC/AVIF/SVG que o ffmpeg não abre direto)
        pngs = []
        for i, o in enumerate(imgs):
            p = os.path.join(tmp, f"{i:04d}.png")
            if familia_de(o) == "svg":
                conv_svg([o], p, {}, prog, "PNG")
            else:
                abrir_imagem(o).convert("RGBA").save(p)
            pngs.append(p)
        cmd = ffmpeg_base()
        for p in pngs:
            cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur}", "-i", p]
        if audio:
            cmd += ["-i", audio]
        partes = []
        for i in range(len(pngs)):
            f = (f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                 f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={cor},setsar=1,format=yuv420p")
            if fade > 0:
                f += f",fade=t=in:st=0:d={fade},fade=t=out:st={max(0, dur - fade)}:d={fade}"
            partes.append(f + f"[v{i}]")
        partes.append("".join(f"[v{i}]" for i in range(len(pngs))) + f"concat=n={len(pngs)}:v=1:a=0[v]")
        cmd += ["-filter_complex", ";".join(partes), "-map", "[v]"]
        total = dur * len(pngs)
        if audio:
            cmd += ["-map", f"{len(pngs)}:a", "-c:a", "aac", "-b:a", "192k", "-t", f"{total}"]
        cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "medium", "-r", str(fps),
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", destino]
        prog.rodar(cmd, duracao=total)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return destino


def conv_gif_de_imagens(origens, destino, op, prog):
    from PIL import Image
    ims = _imagens(origens, op)
    larg = int(op.get("largura") or 800)
    base_w = min(larg, max(im.width for im in ims))
    base_h = max(1, round(ims[0].height * base_w / ims[0].width))
    quadros_ = []
    for im in ims:
        im.thumbnail((base_w, base_h), Image.LANCZOS)
        q = Image.new("RGBA", (base_w, base_h), _fundo_rgba(op.get("fundo", "branco")))
        q.alpha_composite(im, ((base_w - im.width) // 2, (base_h - im.height) // 2))
        quadros_.append(achatar(q, op.get("fundo", "branco")))
    quadros_[0].save(destino, "GIF", save_all=True, append_images=quadros_[1:],
                     duration=int(op.get("ms") or 800), loop=0, optimize=True)
    return destino


def conv_pdf_de_imagens(origens, destino, op, prog):
    pags = [achatar(im, "branco") for im in _imagens(origens, op)]
    pags[0].save(destino, "PDF", save_all=True, append_images=pags[1:],
                 resolution=float(op.get("dpi") or 150))
    return destino


def _tem_audio(c):
    try:
        return ffprobe_tem(c, "a")
    except ErroConversao:
        return False


def conv_unir_videos(origens, destino, op, prog):
    """Concatena re-codificando: todos na resolução/fps da escolha (barras pretas onde faltar)."""
    vids = _ordenar(origens, op)
    if op.get("resolucao", "primeiro") == "primeiro":
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", vids[0]],
                           capture_output=True, text=True, timeout=20)
        try:
            w, h = (int(v) for v in r.stdout.strip().split(",")[:2])
        except ValueError:
            w, h = 1920, 1080
    else:
        w, h = _res(op)
    w, h = w // 2 * 2, h // 2 * 2
    fps = int(op.get("fps") or 30)
    durs = [ffprobe_duracao(v) or 0 for v in vids]
    com_audio = not op.get("sem_audio") and any(_tem_audio(v) for v in vids)
    cmd = ffmpeg_base()
    for v in vids:
        cmd += ["-i", v]
    partes, pares = [], ""
    for i, v in enumerate(vids):
        partes.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                      f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{i}]")
        if com_audio:
            if _tem_audio(v):
                partes.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
            else:  # vídeo mudo: silêncio do mesmo tamanho pra concat não quebrar
                partes.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{durs[i] or 1}[a{i}]")
            pares += f"[v{i}][a{i}]"
        else:
            pares += f"[v{i}]"
    partes.append(pares + f"concat=n={len(vids)}:v=1:a={1 if com_audio else 0}" +
                  ("[v][a]" if com_audio else "[v]"))
    cmd += ["-filter_complex", ";".join(partes), "-map", "[v]"]
    if com_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-crf", str(op.get("crf", "23")), "-preset", "medium",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", destino]
    prog.rodar(cmd, duracao=sum(durs) or None)
    return destino


def conv_videos_lado_a_lado(origens, destino, op, prog):
    """hstack/vstack/grade 2x2: todos na mesma altura (ou largura); termina no mais curto."""
    vids = _ordenar(origens, op)
    n = len(vids)
    layout = op.get("layout", "horizontal")
    tam = int(op.get("tamanho") or 720) // 2 * 2
    cmd = ffmpeg_base()
    for v in vids:
        cmd += ["-i", v]
    partes = []
    for i in range(n):
        esc = f"scale=-2:{tam}" if layout != "vertical" else f"scale={tam}:-2"
        if layout == "grade":
            esc = f"scale={tam * 16 // 9 // 2 * 2}:{tam}:force_original_aspect_ratio=decrease," \
                  f"pad={tam * 16 // 9 // 2 * 2}:{tam}:(ow-iw)/2:(oh-ih)/2"
        partes.append(f"[{i}:v]{esc},setsar=1,format=yuv420p[v{i}]")
    entradas = "".join(f"[v{i}]" for i in range(n))
    if layout == "horizontal":
        partes.append(f"{entradas}hstack=inputs={n}:shortest=1[v]")
    elif layout == "vertical":
        partes.append(f"{entradas}vstack=inputs={n}:shortest=1[v]")
    else:
        col = math.ceil(math.sqrt(n))
        cw, ch = tam * 16 // 9 // 2 * 2, tam
        pos = "|".join(f"{(i % col) * cw}_{(i // col) * ch}" for i in range(n))
        partes.append(f"{entradas}xstack=inputs={n}:layout={pos}:fill=black:shortest=1[v]")
    cmd += ["-filter_complex", ";".join(partes), "-map", "[v]"]
    fonte = int(op.get("audio_de") or 1) - 1
    if not op.get("sem_audio") and 0 <= fonte < n and _tem_audio(vids[fonte]):
        cmd += ["-map", f"{fonte}:a", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-crf", "23", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-shortest", destino]
    durs = [d for d in (ffprobe_duracao(v) for v in vids) if d]
    prog.rodar(cmd, duracao=min(durs) if durs else None)
    return destino


def conv_audios(origens, destino, op, prog):
    """Unir (um depois do outro) ou misturar (tocando juntos)."""
    auds = _ordenar(origens, op)
    cmd = ffmpeg_base()
    for a in auds:
        cmd += ["-i", a]
    n = len(auds)
    norm = "".join(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo[a{i}];" for i in range(n))
    ent = "".join(f"[a{i}]" for i in range(n))
    durs = [ffprobe_duracao(a) or 0 for a in auds]
    if op.get("modo", "unir") == "misturar":
        filtro = norm + f"{ent}amix=inputs={n}:duration=longest:normalize=0[a]"
        dur = max(durs) or None
    else:
        filtro = norm + f"{ent}concat=n={n}:v=0:a=1[a]"
        dur = sum(durs) or None
    cmd += ["-filter_complex", filtro, "-map", "[a]"] + args_audio(destino.rsplit(".", 1)[1], op)
    prog.rodar(cmd + [destino], duracao=dur)
    return destino


def conv_unir_pdfs(origens, destino, op, prog):
    import fitz
    saida = fitz.open()
    ords = _ordenar(origens, op)
    for i, o in enumerate(ords):
        prog.checar()
        fam = familia_de(o)
        if fam == "pdf":
            with abrir_pdf(o) as doc:
                saida.insert_pdf(doc)
        elif fam == "imagem":  # imagem no meio dos PDFs vira página (em memória, sem arquivo temporário)
            buf = io.BytesIO()
            achatar(abrir_imagem(o), "branco").save(buf, "PDF", resolution=150.0)
            with fitz.open("pdf", buf.getvalue()) as doc:
                saida.insert_pdf(doc)
        prog.fracao((i + 1) / len(ords))
    saida.save(destino, garbage=3, deflate=True)
    saida.close()
    return destino


def conv_zip_selecao(origens, destino, op, prog):
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for i, o in enumerate(origens):
            prog.checar()
            if os.path.isdir(o):
                raiz = os.path.dirname(os.path.abspath(o.rstrip("/")))
                for d, _, fs in os.walk(o):
                    for f in fs:
                        c = os.path.join(d, f)
                        z.write(c, os.path.relpath(c, raiz))
            else:
                z.write(o, os.path.basename(o))
            prog.fracao((i + 1) / len(origens))
    return destino


ORDEM = Opcao("ordem", "Ordem", "escolha", "selecao", [("selecao", "Como selecionei"), ("nome", "Por nome")])
RESOLUCOES = [("1920x1080", "1920x1080 (16:9)"), ("1280x720", "1280x720 (16:9)"),
              ("1080x1920", "1080x1920 (vertical/Reels)"), ("1080x1080", "1080x1080 (quadrado)"),
              ("3840x2160", "3840x2160 (4K)")]


def op_montagem(layout):
    return [
        Opcao("layout", "Arranjo", "escolha", layout,
              [("horizontal", "Lado a lado"), ("vertical", "Empilhado"), ("grade", "Grade")]),
        Opcao("colunas", "Colunas da grade (0 = automático)", "numero", 0, minimo=0, maximo=20),
        Opcao("tamanho", "Altura de cada peça em px (0 = automático)", "numero", 0, minimo=0, maximo=8000,
              dica="empilhado: largura de cada peça"),
        Opcao("espaco", "Espaço entre as peças (px)", "numero", 0, minimo=0, maximo=400),
        Opcao("fundo", "Fundo", "escolha", "branco", FUNDOS_MONT),
        ORDEM,
    ]


def op_slideshow(audio=False):
    ops = [
        Opcao("duracao", "Segundos por imagem", "numero", 3, minimo=0.5, maximo=60, passo=0.5),
        Opcao("fade", "Fade em cada imagem (s, 0 = corte seco)", "numero", 0.5, minimo=0, maximo=5,
              passo=0.25),
        Opcao("resolucao", "Resolução", "escolha", "1920x1080", RESOLUCOES),
        Opcao("fps", "Quadros por segundo", "escolha", "30", [("24", "24"), ("30", "30"), ("60", "60")]),
        Opcao("fundo", "Cor das barras", "escolha", "preto", FUNDOS),
        ORDEM,
    ]
    if audio:
        ops.insert(0, Opcao("ajustar_musica", "Dividir a música entre as imagens", "bool", True,
                            dica="desmarcado: usa os segundos por imagem e corta a música"))
    return ops


def alvos_juntar(caminhos):
    """Alvos que juntam a seleção inteira num arquivo só (precisa de 2+ arquivos)."""
    if len(caminhos) < 2:
        return []
    fams = [familia_de(c) for c in caminhos]
    so = lambda *f: all(x in f for x in fams)
    J = lambda *a, **k: Alvo(*a, junta=True, **k)
    alvos = []
    if so("imagem", "svg") and any(f == "imagem" for f in fams):
        alvos += [
            J("png", "juntar", conv_montagem, op_montagem("horizontal"), rotulo="LADOS", sub="lado a lado"),
            J("png", "juntar", conv_montagem, op_montagem("vertical"), rotulo="EMPILHAR", sub="montagem"),
            J("png", "juntar", conv_montagem, op_montagem("grade"), rotulo="GRADE", sub="montagem"),
            J("png", "juntar", conv_misturar, [
                Opcao("modo", "Como misturar", "escolha", "media",
                      [("media", "Média (todas iguais)"), ("sobrepor", "Sobrepor com opacidade"),
                       ("clarear", "Clarear (screen)"), ("multiplicar", "Multiplicar"),
                       ("diferenca", "Diferença")]),
                Opcao("opacidade", "Opacidade da de cima (sobrepor, %)", "numero", 50, minimo=1, maximo=99),
                ORDEM], rotulo="MISTURAR", sub="fundir"),
            J("mp4", "juntar", conv_slideshow, op_slideshow(), rotulo="VÍDEO", sub="slideshow"),
            J("gif", "juntar", conv_gif_de_imagens, [
                Opcao("ms", "Tempo de cada quadro (ms)", "numero", 800, minimo=20, maximo=10000, passo=10),
                Opcao("largura", "Largura máxima (px)", "numero", 800, minimo=16, maximo=4000),
                Opcao("fundo", "Fundo", "escolha", "branco", FUNDOS), ORDEM], rotulo="GIF", sub="animado"),
            J("pdf", "juntar", conv_pdf_de_imagens, [
                Opcao("dpi", "DPI da página", "numero", 150, minimo=36, maximo=1200), ORDEM],
              rotulo="PDF", sub="uma por página"),
        ]
    n_aud = fams.count("audio")
    if n_aud == 1 and so("imagem", "audio"):
        alvos.append(J("mp4", "juntar", lambda o, d, op, p: conv_slideshow(o, d, op, p),
                       op_slideshow(audio=True), rotulo="VÍDEO", sub="com música"))
    if so("video"):
        alvos += [
            J("mp4", "juntar", conv_unir_videos, [
                Opcao("resolucao", "Resolução", "escolha", "primeiro",
                      [("primeiro", "A do primeiro vídeo")] + RESOLUCOES),
                Opcao("fps", "Quadros por segundo", "escolha", "30", [("24", "24"), ("30", "30"), ("60", "60")]),
                Opcao("crf", "Qualidade (CRF, menor = melhor)", "numero", 23, minimo=14, maximo=40),
                Opcao("sem_audio", "Sem áudio", "bool", False), ORDEM], rotulo="UNIR", sub="um depois do outro"),
            J("mp4", "juntar", conv_videos_lado_a_lado, [
                Opcao("layout", "Arranjo", "escolha", "horizontal",
                      [("horizontal", "Lado a lado"), ("vertical", "Empilhado"), ("grade", "Grade")]),
                Opcao("tamanho", "Altura de cada vídeo (px)", "escolha", "720",
                      [("480", "480"), ("720", "720"), ("1080", "1080")]),
                Opcao("audio_de", "Áudio do vídeo nº", "numero", 1, minimo=1, maximo=max(2, len(caminhos))),
                Opcao("sem_audio", "Sem áudio", "bool", False), ORDEM], rotulo="LADOS", sub="vídeos lado a lado"),
        ]
    if so("audio"):
        alvos += [
            J("mp3", "juntar", conv_audios, [Opcao("modo", "Modo", "escolha", "unir",
                [("unir", "Um depois do outro"), ("misturar", "Tocando juntos")])] + op_audio("mp3")[:1] + [ORDEM],
              rotulo="UNIR", sub="áudios"),
            J("mp3", "juntar", conv_audios, [Opcao("modo", "Modo", "escolha", "misturar",
                [("unir", "Um depois do outro"), ("misturar", "Tocando juntos")])] + op_audio("mp3")[:1] + [ORDEM],
              rotulo="MISTURAR", sub="áudios"),
        ]
    if so("pdf", "imagem") and "pdf" in fams:
        alvos.append(J("pdf", "juntar", conv_unir_pdfs, [ORDEM], rotulo="UNIR", sub="PDFs"))
    alvos.append(J("zip", "juntar", conv_zip_selecao, rotulo="ZIP", sub="tudo junto"))
    return alvos


def achar_alvo(caminhos, chave):
    """Alvo pela `chave` (familia:rotulo:sub), entre os de juntar e os do 1º arquivo."""
    for a in alvos_juntar(caminhos) + alvos_para(caminhos[0]):
        if a.chave == chave:
            return a
    return None


def destino_juntar(origens, alvo, pasta_saida=""):
    base, _ = separar_ext(origens[0])
    pasta = pasta_saida or os.path.dirname(os.path.abspath(origens[0].rstrip("/")))
    nome = f"{os.path.basename(base)} - {alvo.rotulo.lower()} {alvo.sub}".strip()
    return caminho_livre(pasta, nome, alvo.ext)


# ---------------------------------------------------------------- roteamento


def familia_de(caminho):
    if os.path.isdir(caminho):
        return "pasta"
    _, ext = separar_ext(caminho)
    for fam, conj in (("imagem", IMG_IN), ("audio", AUDIO_IN), ("video", VIDEO_IN), ("texto", TEXTO_IN),
                      ("office", DOC_IN | PLAN_IN | APRES_IN), ("dados", DADOS_IN),
                      ("legenda", LEGENDA_IN), ("fonte", FONTE_IN), ("pacote", PACOTE_IN)):
        if ext in conj:
            return fam
    if ext == "svg":
        return "svg"
    if ext == "pdf":
        return "pdf"
    try:  # sem extensão conhecida: tenta o tipo pelo conteúdo
        r = subprocess.run(["file", "-b", "--mime-type", caminho], capture_output=True, text=True, timeout=5)
        mime = r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if mime.startswith("image/"):
        return "imagem"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if mime == "application/pdf":
        return "pdf"
    if mime.startswith("text/"):
        return "texto"
    return None


def alvos_para(caminho):
    fam = familia_de(caminho)
    _, ext = separar_ext(caminho)
    ext = {"jpeg": "jpg", "jfif": "jpg", "tif": "tiff", "htm": "html", "yml": "yaml", "markdown": "md"}.get(ext, ext)
    if fam == "imagem":
        alvos = [a for a in alvos_imagem() if a.ext != ext]
        if ext in ("jpg", "png", "webp"):  # mesmo formato = recomprimir
            mesmo = next(a for a in alvos_imagem() if a.ext == ext)
            mesmo.rotulo, mesmo.sub = ext.upper(), "comprimir"
            alvos.append(mesmo)
        if ext in ("gif", "webp") and e_animada(caminho):
            alvos = ALVOS_ANIM + alvos
        return alvos
    if fam == "svg":
        return alvos_svg()
    if fam == "audio":
        return [a for a in alvos_audio() if a.ext != ext]
    if fam == "video":
        alvos = [a for a in alvos_video() if a.ext != ext or a.familia != "video"]
        if ext == "mp4":
            comp = Alvo("mp4", "video", conv_video, op_video(), rotulo="MP4", sub="comprimir")
            for o in comp.opcoes:
                if o.chave == "crf":
                    o.padrao = "28"
            alvos.append(comp)
        return alvos
    if fam == "pdf":
        return alvos_pdf()
    if fam == "texto":
        return alvos_texto(ext)
    if fam == "office":
        return alvos_office(ext)
    if fam == "dados":
        return alvos_dados(ext)
    if fam == "legenda":
        return alvos_legenda(ext)
    if fam == "fonte":
        return alvos_fonte(ext)
    if fam == "pacote":
        return alvos_pacote(ext)
    if fam == "pasta":
        return alvos_pacote("", pasta=True)
    return []


def converter(origens, alvo, op, destino, prog):
    """Roda a conversão; apaga o destino parcial se falhar. Devolve o caminho final."""
    for o in origens:
        if not os.path.exists(o):
            raise ErroConversao(f"Arquivo não existe mais: {o}", "Ele foi movido ou apagado. Aponte de novo.")
    pasta = os.path.dirname(destino) or "."
    if not os.access(pasta, os.W_OK):
        raise ErroConversao(f"Sem permissão de escrita em {pasta}.",
                            "Use o ⚙ (anel externo da roda) e escolha outra pasta de saída.")
    try:
        final = alvo.func(origens, destino, op, prog)
        if not os.path.exists(final) or (os.path.isfile(final) and os.path.getsize(final) == 0):
            raise ErroConversao("A ferramenta terminou sem erro, mas não gerou o arquivo.",
                                "Tente pelo ⚙ com outros ajustes (ex.: trecho de corte ou instante dentro "
                                "da duração do arquivo).")
        return final
    except (ErroConversao, Cancelado):
        _limpar(destino)
        raise
    except MemoryError:
        _limpar(destino)
        raise ErroConversao("Faltou memória para essa conversão.",
                            "Feche programas pesados ou reduza a resolução no ⚙.")
    except OSError as e:
        _limpar(destino)
        if e.errno == 28:
            raise ErroConversao("Disco cheio.", "Libere espaço ou escolha outra pasta no ⚙.", str(e))
        raise ErroConversao(f"Erro de arquivo: {e.strerror or e}", "Confira permissões e espaço em disco.", repr(e))
    except Exception as e:
        _limpar(destino)
        import traceback
        raise ErroConversao(f"Falha inesperada: {e}", "Tente pelo ⚙ com ajustes diferentes, ou outro formato. "
                            "Se repetir, os detalhes abaixo mostram onde quebrou.", traceback.format_exc())


def _limpar(destino):
    try:
        if os.path.isfile(destino):
            os.remove(destino)  # parcial gerado por nós mesmos nesta conversão
    except OSError:
        pass
