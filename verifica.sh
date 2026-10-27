#!/usr/bin/env bash
# Checagem sem abrir janela: compila, renderiza a roda em PNG e roda conversões em
# amostras minúsculas. Uso: ./verifica.sh          (rápido, sem LibreOffice)
#                           ./verifica.sh --office (inclui 2 conversões via LibreOffice)
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
DIR="$(cd "$(dirname "$0")" && pwd)"
TMP="$DIR/tmp/verifica"
mkdir -p "$TMP"
echo "[1/3] compilando"
for f in conversores.py roda_conversor.py; do
  python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$DIR/$f"
done
echo "[2/3] renderizando a roda e a animação -> $TMP/roda.png, animacao.png"
python3 - "$DIR" "$TMP" <<'PY'
import sys, types
sys.path.insert(0, sys.argv[1])
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
import roda_conversor as r, conversores as c
import time
from PIL import Image
alvos = c.alvos_para("/x/foto.webp")
f = r.Roda.__new__(r.Roda)   # sem janela: só o desenho
f.k, f.alvos, f.arquivos, f.msg, f.anim = 1.0, alvos, [sys.argv[0]], "", None
f.S = 2 * (r.Roda.R2 + r.Roda.PAD)

def png(nome):
    ld = GdkPixbuf.PixbufLoader.new_with_type("svg"); ld.write(f.svg().encode()); ld.close()
    ld.get_pixbuf().savev(f"{sys.argv[2]}/{nome}.png", "png", [], [])
    return f"{sys.argv[2]}/{nome}.png"

f.sel = (2, "conv"); png("roda")
f.sel = (5, "cfg"); png("roda-cfg")
# quadros da animação lado a lado: abrir (flor) e escolher (pétalas fecham na escolhida)
quadros = []
for tipo, ts, extra in (("abrir", (0.02, 0.07, 0.13, 0.2, 0.42), {"atraso": 0.14 / len(alvos)}),
                        ("escolher", (0.06, 0.13, 0.2, 0.27), {"i": 2})):
    for t in ts:
        f.sel = (2, "conv") if tipo == "escolher" else (None, None)
        f.anim = dict(tipo=tipo, t0=time.monotonic() - t, **extra)
        quadros.append(Image.open(png("quadro")).resize((262, 262)))
f.anim = None
folha = Image.new("RGBA", (262 * len(quadros), 262), (40, 44, 52, 255))
for j, q in enumerate(quadros):
    folha.alpha_composite(q.convert("RGBA"), (262 * j, 0))
folha.save(sys.argv[2] + "/animacao.png")
t = time.perf_counter()
for _ in range(20):
    ld = GdkPixbuf.PixbufLoader.new_with_type("svg"); ld.write(f.svg().encode()); ld.close(); ld.get_pixbuf()
print(f"  quadro da roda: {(time.perf_counter() - t) / 20 * 1000:.1f} ms (animação a ~60 fps precisa < 16)")
print(f"  {len(alvos)} alvos para webp: " + " ".join(a.rotulo for a in alvos))
PY
echo "[3/3] conversões em amostras"
python3 - "$DIR" "$TMP" "${1:-}" <<'PY'
import os, sys, shutil, subprocess, json, zipfile, time
sys.path.insert(0, sys.argv[1])
import conversores as c
T = sys.argv[2]; office = sys.argv[3] == "--office"
A = os.path.join(T, "amostras"); S = os.path.join(T, "saidas")
for d in (A, S):
    if os.path.isdir(d):
        shutil.rmtree(d)  # pasta de teste nossa, recriada a cada rodada
    os.makedirs(d)
from PIL import Image, ImageDraw
im = Image.new("RGBA", (64, 48), (0, 0, 0, 0)); ImageDraw.Draw(im).ellipse((4, 4, 60, 44), fill=(220, 60, 40, 255))
im.save(f"{A}/foto.webp"); im.save(f"{A}/foto.png")
fr = [Image.new("RGB", (40, 40), (i * 60, 80, 200)) for i in range(4)]
fr[0].save(f"{A}/anim.gif", save_all=True, append_images=fr[1:], duration=100, loop=0)
q = ["ffmpeg", "-v", "error", "-y"]
subprocess.run(q + ["-f", "lavfi", "-i", "sine=f=440:d=1", f"{A}/som.wav"], check=True)
subprocess.run(q + ["-f", "lavfi", "-i", "testsrc=s=160x120:d=1:r=10", "-f", "lavfi", "-i", "sine=d=1",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", f"{A}/video.mp4"], check=True)
open(f"{A}/nota.txt", "w").write("Título\n\nOlá, conversão com acentuação: ção, ã, é.\nSegunda linha.\n")
open(f"{A}/doc.md", "w").write("# Doc\n\nTexto **forte** e *itálico*.\n\n- um\n- dois\n\n```\ncódigo\n```\n")
open(f"{A}/pag.html", "w").write("<html><body><h1>Oi</h1><p>Um <a href='http://x'>link</a> e <b>negrito</b>.</p>"
                                 "<ul><li>a</li><li>b</li></ul></body></html>")
json.dump([{"nome": "Ana", "idade": 30}, {"nome": "Zé", "idade": 41, "extra": [1, 2]}],
          open(f"{A}/dados.json", "w"), ensure_ascii=False)
open(f"{A}/tabela.csv", "w").write("a;b\n1;2\n3;4\n")
open(f"{A}/leg.srt", "w").write("1\n00:00:01,000 --> 00:00:02,000\nOlá\n\n")
open(f"{A}/logo.svg", "w").write('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
                                  '<circle cx="20" cy="20" r="18" fill="teal"/></svg>')
os.makedirs(f"{A}/pasta/sub"); open(f"{A}/pasta/sub/a.txt", "w").write("a")
import fitz
d = fitz.open(); [d.new_page().insert_text((72, 72), f"Página {i + 1} com texto", fontsize=14) for i in range(2)]
d.save(f"{A}/doc.pdf")
fonte = next((p for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                          "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf") if os.path.exists(p)), None)
if fonte:
    shutil.copy(fonte, f"{A}/fonte.ttf")

casos = [("foto.webp", "png", ""), ("foto.webp", "jpg", ""), ("foto.webp", "pdf", ""), ("foto.webp", "ico", "ícone"),
         ("foto.webp", "avif", ""), ("foto.png", "png", "comprimir"), ("anim.gif", "mp4", "animação"),
         ("anim.gif", "webp", ""), ("som.wav", "mp3", ""), ("som.wav", "opus", ""),
         ("video.mp4", "webm", ""), ("video.mp4", "gif", "animado"), ("video.mp4", "mp3", "áudio"),
         ("video.mp4", "jpg", "1 quadro"), ("video.mp4", "mkv", ""), ("nota.txt", "md", ""),
         ("nota.txt", "pdf", ""), ("doc.md", "html", ""), ("doc.md", "pdf", ""), ("doc.md", "txt", ""),
         ("pag.html", "md", ""), ("pag.html", "txt", ""), ("dados.json", "yaml", ""), ("dados.json", "csv", ""),
         ("tabela.csv", "json", ""), ("leg.srt", "vtt", ""), ("logo.svg", "png", ""), ("doc.pdf", "png", "páginas"), ("doc.pdf", "png", "1 imagem"), ("doc.pdf", "jpg", "1 imagem"), ("doc.pdf", "webp", "páginas"), ("doc.pdf", "webp", "1 imagem"),
         ("doc.pdf", "svg", "vetor"), ("doc.pdf", "tiff", "multipágina"),
         ("doc.pdf", "txt", ""), ("doc.pdf", "md", "aproximado"), ("doc.pdf", "pdf", "comprimir"),
         ("pasta", "zip", "compactar"), ("fonte.ttf", "woff2", "web")]
if office:
    casos += [("doc.md", "docx", "Word"), ("dados.json", "xlsx", "planilha")]
falhas = 0
for arq, ext, sub in casos:
    src = f"{A}/{arq}"
    if not os.path.exists(src):
        print(f"  --  {arq} (amostra ausente)")
        continue
    alvo = next((a for a in c.alvos_para(src) if a.ext == ext and a.sub == sub), None)
    if not alvo:
        print(f"  ✗  {arq} -> {ext}: alvo não oferecido"); falhas += 1; continue
    dest = c.destino_padrao(src, alvo, S)
    t = time.time()
    try:
        out = c.converter([src], alvo, alvo.padroes(), dest, c.Progresso())
        tam = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(out) for f in fs) \
            if os.path.isdir(out) else os.path.getsize(out)
        ok = tam > 0
        print(f"  {'✓' if ok else '✗'}  {arq} -> {os.path.basename(out)} ({tam} B, {time.time() - t:.1f}s)")
        falhas += not ok
    except c.ErroConversao as e:
        print(f"  ✗  {arq} -> {ext}: {e.motivo}\n     {e.detalhes[-300:]}"); falhas += 1
# nome repetido ganha incremento
a = next(x for x in c.alvos_para(f"{A}/foto.webp") if x.ext == "png")
p1 = c.destino_padrao(f"{A}/foto.webp", a, S); print("  incremento:", os.path.basename(p1))
falhas += not (os.path.exists(f"{S}/foto.png") and p1.endswith(").png") and not os.path.exists(p1))
# erro amigável: arquivo que não é mídia
open(f"{A}/falso.mp3", "w").write("não sou áudio")
try:
    al = next(x for x in c.alvos_para(f"{A}/falso.mp3") if x.ext == "wav")
    c.converter([f"{A}/falso.mp3"], al, al.padroes(), f"{S}/falso.wav", c.Progresso())
    print("  ✗  arquivo falso converteu?"); falhas += 1
except c.ErroConversao as e:
    print(f"  ✓  erro amigável: {e.motivo} | {e.sugestao[:60]}")
print("OK" if not falhas else f"FALHOU: {falhas}")
sys.exit(1 if falhas else 0)
PY
