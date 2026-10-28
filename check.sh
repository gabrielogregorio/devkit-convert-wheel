#!/usr/bin/env bash
# Check without opening a window: compiles, checks the translations, renders the wheel to PNG
# and runs conversions on tiny samples.
# Usage: ./check.sh          (fast, no LibreOffice)
#        ./check.sh --office (adds 2 conversions through LibreOffice)
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
DIR="$(cd "$(dirname "$0")" && pwd)"
TMP="$DIR/tmp/check"
mkdir -p "$TMP"
echo "[1/4] compiling"
for f in i18n.py converters.py convert_wheel.py tools/screenshots.py; do
  python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$DIR/$f"
done
echo "[2/4] translations (every tr()/tr_noop() string has a pt-BR entry with the same {placeholders})"
python3 - "$DIR" <<'PY'
import ast, re, sys
sys.path.insert(0, sys.argv[1])
from i18n import PT_BR
used, missing, bad = set(), [], []
fields = lambda s: sorted(re.findall(r"\{(\w*)\}", s))
for name in ("converters.py", "convert_wheel.py"):
    for n in ast.walk(ast.parse(open(f"{sys.argv[1]}/{name}").read())):
        if (isinstance(n, ast.Call) and getattr(n.func, "id", None) in ("tr", "tr_noop") and n.args
                and isinstance(n.args[0], ast.Constant)):
            s = n.args[0].value
            used.add(s)
            if s not in PT_BR:
                missing.append(f"{name}: {s!r}")
            elif fields(s) != fields(PT_BR[s]):
                bad.append(f"{name}: {s!r}")
unused = sorted(set(PT_BR) - used)
for m in missing:
    print("  ✗  no pt-BR:", m)
for b in bad:
    print("  ✗  placeholders differ:", b)
for u in unused:
    print("  --  unused pt-BR entry:", repr(u))
print(f"  {len(used)} strings, {len(missing)} missing, {len(bad)} with different placeholders")
sys.exit(1 if missing or bad else 0)
PY
echo "[3/4] rendering the wheel and the animation -> $TMP/wheel.png, animation.png"
python3 - "$DIR" "$TMP" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
import convert_wheel as w, converters as c
import time
from PIL import Image
targets = c.targets_for("/x/photo.webp")
f = w.Wheel.__new__(w.Wheel)   # no window: drawing only
f.k, f.targets, f.files, f.msg, f.anim = 1.0, targets, [sys.argv[0]], "", None
f.S = 2 * (w.Wheel.R2 + w.Wheel.PAD)

def png(name):
    ld = GdkPixbuf.PixbufLoader.new_with_type("svg"); ld.write(f.svg().encode()); ld.close()
    ld.get_pixbuf().savev(f"{sys.argv[2]}/{name}.png", "png", [], [])
    return f"{sys.argv[2]}/{name}.png"

f.sel = (2, "conv"); png("wheel")
f.sel = (5, "cfg"); png("wheel-cfg")
# animation frames side by side: open (flower) and pick (petals fold into the chosen one)
frames = []
for kind, ts, extra in (("open", (0.02, 0.07, 0.13, 0.2, 0.42), {"delay": 0.14 / len(targets)}),
                        ("pick", (0.06, 0.13, 0.2, 0.27), {"i": 2})):
    for t in ts:
        f.sel = (2, "conv") if kind == "pick" else (None, None)
        f.anim = dict(kind=kind, t0=time.monotonic() - t, **extra)
        frames.append(Image.open(png("frame")).resize((262, 262)))
f.anim = None
sheet = Image.new("RGBA", (262 * len(frames), 262), (40, 44, 52, 255))
for j, q in enumerate(frames):
    sheet.alpha_composite(q.convert("RGBA"), (262 * j, 0))
sheet.save(sys.argv[2] + "/animation.png")
t = time.perf_counter()
for _ in range(20):
    ld = GdkPixbuf.PixbufLoader.new_with_type("svg"); ld.write(f.svg().encode()); ld.close(); ld.get_pixbuf()
print(f"  wheel frame: {(time.perf_counter() - t) / 20 * 1000:.1f} ms (the ~60 fps animation needs < 16)")
print(f"  {len(targets)} targets for webp: " + " ".join(a.label for a in targets))
PY
echo "[4/4] conversions on samples"
python3 - "$DIR" "$TMP" "${1:-}" <<'PY'
import os, sys, shutil, subprocess, json, time
sys.path.insert(0, sys.argv[1])
import converters as c
T = sys.argv[2]; office = sys.argv[3] == "--office"
A = os.path.join(T, "samples"); S = os.path.join(T, "outputs")
for d in (A, S):
    if os.path.isdir(d):
        shutil.rmtree(d)  # our own test folder, recreated on every run
    os.makedirs(d)
from PIL import Image, ImageDraw
im = Image.new("RGBA", (64, 48), (0, 0, 0, 0)); ImageDraw.Draw(im).ellipse((4, 4, 60, 44), fill=(220, 60, 40, 255))
im.save(f"{A}/photo.webp"); im.save(f"{A}/photo.png")
fr = [Image.new("RGB", (40, 40), (i * 60, 80, 200)) for i in range(4)]
fr[0].save(f"{A}/anim.gif", save_all=True, append_images=fr[1:], duration=100, loop=0)
q = ["ffmpeg", "-v", "error", "-y"]
subprocess.run(q + ["-f", "lavfi", "-i", "sine=f=440:d=1", f"{A}/sound.wav"], check=True)
subprocess.run(q + ["-f", "lavfi", "-i", "testsrc=s=160x120:d=1:r=10", "-f", "lavfi", "-i", "sine=d=1",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", f"{A}/video.mp4"], check=True)
open(f"{A}/note.txt", "w").write("Title\n\nNon-ASCII text: ção, ã, é, ü, ñ.\nSecond line.\n")
open(f"{A}/doc.md", "w").write("# Doc\n\nSome **bold** and *italic* text.\n\n- one\n- two\n\n```\ncode\n```\n")
open(f"{A}/page.html", "w").write("<html><body><h1>Hi</h1><p>A <a href='http://x'>link</a> and <b>bold</b>.</p>"
                                  "<ul><li>a</li><li>b</li></ul></body></html>")
json.dump([{"name": "Ana", "age": 30}, {"name": "José", "age": 41, "extra": [1, 2]}],
          open(f"{A}/data.json", "w"), ensure_ascii=False)
open(f"{A}/table.csv", "w").write("a;b\n1;2\n3;4\n")
open(f"{A}/sub.srt", "w").write("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n")
open(f"{A}/logo.svg", "w").write('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
                                  '<circle cx="20" cy="20" r="18" fill="teal"/></svg>')
os.makedirs(f"{A}/folder/sub"); open(f"{A}/folder/sub/a.txt", "w").write("a")
import fitz
d = fitz.open(); [d.new_page().insert_text((72, 72), f"Page {i + 1} with text", fontsize=14) for i in range(2)]
d.save(f"{A}/doc.pdf")
font = next((p for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                         "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf") if os.path.exists(p)), None)
if font:
    shutil.copy(font, f"{A}/font.ttf")

cases = [("photo.webp", "png", ""), ("photo.webp", "jpg", ""), ("photo.webp", "pdf", ""),
         ("photo.webp", "ico", "icon"), ("photo.webp", "avif", ""), ("photo.png", "png", "compress"),
         ("anim.gif", "mp4", "animation"), ("anim.gif", "webp", ""), ("sound.wav", "mp3", ""),
         ("sound.wav", "opus", ""), ("video.mp4", "webm", ""), ("video.mp4", "gif", "animated"),
         ("video.mp4", "mp3", "audio"), ("video.mp4", "jpg", "1 frame"), ("video.mp4", "mkv", ""),
         ("note.txt", "md", ""), ("note.txt", "pdf", ""), ("doc.md", "html", ""), ("doc.md", "pdf", ""),
         ("doc.md", "txt", ""), ("page.html", "md", ""), ("page.html", "txt", ""), ("data.json", "yaml", ""),
         ("data.json", "csv", ""), ("table.csv", "json", ""), ("sub.srt", "vtt", ""), ("logo.svg", "png", ""),
         ("doc.pdf", "png", "pages"), ("doc.pdf", "png", "1 image"), ("doc.pdf", "jpg", "1 image"),
         ("doc.pdf", "webp", "pages"), ("doc.pdf", "webp", "1 image"), ("doc.pdf", "svg", "vector"),
         ("doc.pdf", "tiff", "multipage"), ("doc.pdf", "txt", ""), ("doc.pdf", "md", "approximate"),
         ("doc.pdf", "pdf", "compress"), ("folder", "zip", "pack"), ("font.ttf", "woff2", "web")]
if office:
    cases += [("doc.md", "docx", "Word"), ("data.json", "xlsx", "spreadsheet")]
failures = 0
for name, ext, sub in cases:
    src = f"{A}/{name}"
    if not os.path.exists(src):
        print(f"  --  {name} (sample missing)")
        continue
    target = next((a for a in c.targets_for(src) if a.ext == ext and a.sub == sub), None)
    if not target:
        print(f"  ✗  {name} -> {ext}: target not offered"); failures += 1; continue
    dest = c.default_destination(src, target, S)
    t = time.time()
    try:
        out = c.convert([src], target, target.defaults(), dest, c.Progress())
        size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(out) for f in fs) \
            if os.path.isdir(out) else os.path.getsize(out)
        ok = size > 0
        print(f"  {'✓' if ok else '✗'}  {name} -> {os.path.basename(out)} ({size} B, {time.time() - t:.1f}s)")
        failures += not ok
    except c.ConversionError as e:
        print(f"  ✗  {name} -> {ext}: {e.reason}\n     {e.details[-300:]}"); failures += 1
# a repeated name gets a number
a = next(x for x in c.targets_for(f"{A}/photo.webp") if x.ext == "png")
p1 = c.default_destination(f"{A}/photo.webp", a, S); print("  numbering:", os.path.basename(p1))
failures += not (os.path.exists(f"{S}/photo.png") and p1.endswith(").png") and not os.path.exists(p1))
# friendly error: a file that is not media
open(f"{A}/fake.mp3", "w").write("not audio")
try:
    al = next(x for x in c.targets_for(f"{A}/fake.mp3") if x.ext == "wav")
    c.convert([f"{A}/fake.mp3"], al, al.defaults(), f"{S}/fake.wav", c.Progress())
    print("  ✗  the fake file converted?"); failures += 1
except c.ConversionError as e:
    print(f"  ✓  friendly error: {e.reason} | {e.hint[:60]}")
print("OK" if not failures else f"FAILED: {failures}")
sys.exit(1 if failures else 0)
PY
