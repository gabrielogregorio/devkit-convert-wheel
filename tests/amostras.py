"""Amostras minúsculas geradas na hora (PIL + ffmpeg lavfi). Nada versionado, nada pesado."""

import os
import shutil
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.dont_write_bytecode = True

TEM_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def pasta_temporaria():
    base = os.path.join(RAIZ, "tmp")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix="teste-", dir=base)


def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def gerar(pasta):
    """Devolve dict nome -> caminho. Imagens de tamanhos diferentes de propósito."""
    from PIL import Image
    a = {}
    a["vermelha.jpg"] = os.path.join(pasta, "vermelha.jpg")
    Image.new("RGB", (320, 200), (200, 40, 40)).save(a["vermelha.jpg"])
    a["verde.png"] = os.path.join(pasta, "verde.png")
    Image.new("RGB", (200, 300), (40, 160, 60)).save(a["verde.png"])
    a["azul_alfa.png"] = os.path.join(pasta, "azul_alfa.png")
    Image.new("RGBA", (256, 256), (40, 60, 200, 128)).save(a["azul_alfa.png"])
    a["logo.svg"] = os.path.join(pasta, "logo.svg")
    with open(a["logo.svg"], "w") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
                '<circle cx="32" cy="32" r="30" fill="teal"/></svg>')
    a["nota.txt"] = os.path.join(pasta, "nota.txt")
    with open(a["nota.txt"], "w") as f:
        f.write("oi\n")
    a["pasta"] = os.path.join(pasta, "pasta")
    os.makedirs(a["pasta"], exist_ok=True)
    with open(os.path.join(a["pasta"], "dentro.txt"), "w") as f:
        f.write("dentro\n")
    import fitz
    for nome, paginas in (("doc1.pdf", 2), ("doc2.pdf", 1)):
        doc = fitz.open()
        for _ in range(paginas):
            doc.new_page()
        a[nome] = os.path.join(pasta, nome)
        doc.save(a[nome])
        doc.close()
    if TEM_FFMPEG:
        a["v1.mp4"] = os.path.join(pasta, "v1.mp4")
        _ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=1",
            "-f", "lavfi", "-i", "sine=f=440:d=1", "-shortest", a["v1.mp4"])
        a["v2_mudo.mp4"] = os.path.join(pasta, "v2_mudo.mp4")
        _ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=1", a["v2_mudo.mp4"])
        a["s1.wav"] = os.path.join(pasta, "s1.wav")
        _ff("-f", "lavfi", "-i", "sine=f=330:d=1", a["s1.wav"])
        a["s2.mp3"] = os.path.join(pasta, "s2.mp3")
        _ff("-f", "lavfi", "-i", "sine=f=660:d=1.5", a["s2.mp3"])
    return a


def sonda(caminho, entradas):
    """ffprobe -> texto csv das entradas pedidas (ex.: 'format=duration')."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", entradas, "-of", "csv=p=0", caminho],
                       capture_output=True, text=True, timeout=20)
    return r.stdout.strip()


def faixas(caminho):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                        caminho], capture_output=True, text=True, timeout=20)
    return sorted(set(r.stdout.split()))
