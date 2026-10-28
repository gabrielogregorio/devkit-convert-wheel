"""Tiny sample files for the e2e tests, written to tmp/check/samples (also used by tools/screenshots.py)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECK_DIR = ROOT / "tmp" / "check"
SAMPLES = CHECK_DIR / "samples"
OUTPUTS = CHECK_DIR / "outputs"


def build():
    for d in (SAMPLES, OUTPUTS):
        if d.is_dir():
            shutil.rmtree(d)  # our own test folder, recreated on every run
        d.mkdir(parents=True)
    a = str(SAMPLES)
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (64, 48), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((4, 4, 60, 44), fill=(220, 60, 40, 255))
    im.save(f"{a}/photo.webp")
    im.save(f"{a}/photo.png")
    frames = [Image.new("RGB", (40, 40), (i * 60, 80, 200)) for i in range(4)]
    frames[0].save(f"{a}/anim.gif", save_all=True, append_images=frames[1:], duration=100, loop=0)
    q = ["ffmpeg", "-v", "error", "-y"]
    subprocess.run(q + ["-f", "lavfi", "-i", "sine=f=440:d=1", f"{a}/sound.wav"], check=True)
    subprocess.run(q + ["-f", "lavfi", "-i", "testsrc=s=160x120:d=1:r=10", "-f", "lavfi", "-i", "sine=d=1",
                        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", f"{a}/video.mp4"], check=True)
    (SAMPLES / "note.txt").write_text("Title\n\nNon-ASCII text: ção, ã, é, ü, ñ.\nSecond line.\n", encoding="utf-8")
    (SAMPLES / "doc.md").write_text("# Doc\n\nSome **bold** and *italic* text.\n\n- one\n- two\n\n```\ncode\n```\n")
    (SAMPLES / "page.html").write_text("<html><body><h1>Hi</h1><p>A <a href='http://x'>link</a> and <b>bold</b>.</p>"
                                       "<ul><li>a</li><li>b</li></ul></body></html>")
    (SAMPLES / "data.json").write_text(json.dumps([{"name": "Ana", "age": 30}, {"name": "José", "age": 41,
                                                                                 "extra": [1, 2]}],
                                                  ensure_ascii=False), encoding="utf-8")
    (SAMPLES / "table.csv").write_text("a;b\n1;2\n3;4\n")
    (SAMPLES / "sub.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n\n")
    (SAMPLES / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
                                      '<circle cx="20" cy="20" r="18" fill="teal"/></svg>')
    (SAMPLES / "folder" / "sub").mkdir(parents=True)
    (SAMPLES / "folder" / "sub" / "a.txt").write_text("a")
    import fitz
    d = fitz.open()
    for i in range(2):
        d.new_page().insert_text((72, 72), f"Page {i + 1} with text", fontsize=14)
    d.save(f"{a}/doc.pdf")
    font = next((p for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                             "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf") if os.path.exists(p)), None)
    if font:
        shutil.copy(font, f"{a}/font.ttf")
    (SAMPLES / "fake.mp3").write_text("not audio")
