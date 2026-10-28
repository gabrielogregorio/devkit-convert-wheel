"""Conversion engine of Convert Wheel.

No GTK here: everything runs in a worker thread and is testable without a screen (check.sh).
Each output format is a `Target`; `targets_for(path)` returns the ones that fit that file.
A failure becomes `ConversionError(reason, hint, details)`, which the progress popup shows
as an error + "how to fix".
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
import threading
import time
import traceback
import zipfile
from html.parser import HTMLParser

from i18n import HTML_LANG, tr, tr_noop

# ---------------------------------------------------------------- errors and progress


class ConversionError(Exception):
    def __init__(self, reason, hint="", details=""):
        super().__init__(reason)
        self.reason = reason
        self.hint = hint
        self.details = details


class Cancelled(Exception):
    pass


APT_PACKAGE = {  # executable -> apt package
    "ffmpeg": "ffmpeg", "ffprobe": "ffmpeg", "soffice": "libreoffice",
    "gs": "ghostscript", "pdftotext": "poppler-utils",
}


class Progress:
    """Bridge between the conversion (thread) and the popup. The popup swaps the callbacks."""

    def __init__(self, on_fraction=None, on_text=None):
        self.on_fraction = on_fraction or (lambda f: None)
        self.on_text = on_text or (lambda t: None)
        self.cancelled = False
        self._proc = None

    def fraction(self, f):
        self.on_fraction(max(0.0, min(1.0, f)))

    def text(self, t):
        self.on_text(t)

    def check(self):
        if self.cancelled:
            raise Cancelled()

    def cancel(self):
        self.cancelled = True
        p = self._proc
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass

    def run(self, cmd, duration=None, timeout=None):
        """Runs a process; when `duration` (s) is given, reads ffmpeg's -progress."""
        exe = cmd[0]
        if not shutil.which(exe):
            pkg = APT_PACKAGE.get(exe, exe)
            raise ConversionError(
                tr("Tool '{exe}' is not installed.").format(exe=exe),
                tr("Install it with:\n  sudo apt install {pkg}").format(pkg=pkg),
            )
        self.check()
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        self._proc = p
        err = []
        t = threading.Thread(target=lambda: err.extend(p.stderr), daemon=True)
        t.start()
        start = time.time()
        for line in p.stdout:
            if duration and line.startswith(b"out_time_us="):
                try:
                    us = int(line.split(b"=")[1])
                    self.fraction(us / 1e6 / duration)
                except ValueError:
                    pass
            if timeout and time.time() - start > timeout:
                self.cancel()
        p.wait()
        t.join(2)
        p.stdout.close()  # without this every conversion leaves 2 open descriptors in the wheel (long-lived process)
        p.stderr.close()
        self._proc = None
        self.check()
        output = b"".join(err).decode("utf-8", "replace")
        if p.returncode != 0:
            raise process_error(exe, output, p.returncode)
        return output


def process_error(exe, stderr, code):
    """Turns the error output into a cause and a hint on how to fix it."""
    s = stderr.lower()
    tail = "\n".join(stderr.strip().splitlines()[-25:])
    no_stream = (tr("The file does not have the requested track (e.g. video without audio)."),
                 tr("Pick a format that matches what the file contains."))
    odd = (tr("This codec does not accept an odd resolution."),
           tr("In ⚙, pick a resolution from the list (it is always even)."))
    rules = [
        ("no space left", tr("Disk full."), tr("Free up disk space or pick another output folder in ⚙.")),
        ("permission denied", tr("No permission to read or write."),
         tr("Pick another output folder in ⚙ (outer ring of the wheel) or check the file permissions.")),
        ("invalid data found", tr("The file does not look like valid media (corrupted or wrong extension)."),
         tr("Open the file in a player to confirm. If the extension is wrong, rename it to the right one.")),
        ("moov atom not found", tr("Incomplete video (interrupted download or recording)."),
         tr("Download/record it again. A truncated file has no index and cannot be converted.")),
        ("unknown encoder", tr("This ffmpeg lacks the required encoder."),
         tr("Try another output format or install the full ffmpeg: sudo apt install ffmpeg")),
        ("does not contain any stream", *no_stream),
        ("output file #0 does not contain", *no_stream),
        ("matches no streams", *no_stream),
        ("could not write header", tr("The output format does not accept the file's codecs."),
         tr("In ⚙, turn off 'copy without re-encoding' or pick mp4/mkv.")),
        ("password", tr("Password-protected PDF."), tr("Remove the PDF password before converting.")),
        ("height not divisible by 2", *odd),
        ("width not divisible by 2", *odd),
        ("source file could not be loaded", tr("LibreOffice could not open the document."),
         tr("Open it in LibreOffice to check the file is intact; if it is protected, remove the password.")),
    ]
    for key, reason, hint in rules:
        if key in s:
            return ConversionError(reason, hint, tail)
    return ConversionError(tr("'{exe}' exited with an error (code {code}).").format(exe=exe, code=code),
                           tr("See the technical details below. Try ⚙ (outer ring) with simpler settings, "
                              "or another output format."), tail)


# ---------------------------------------------------------------- options and targets


class Option:
    """One field of the settings dialog. kind: choice | number | text | bool."""

    def __init__(self, key, label, kind, default, choices=None, minimum=0, maximum=100,
                 step=1, hint=""):
        self.key, self.label, self.kind, self.default = key, label, kind, default
        self.choices = choices or []   # [(value, label)]
        self.minimum, self.maximum, self.step, self.hint = minimum, maximum, step, hint


class Target:
    """One output format. `label` and `sub` stay in English (they form `key`, which names
    the remembered settings); the UI shows them through tr()."""

    def __init__(self, ext, family, func, options=(), label=None, sub="", extra=False):
        self.ext = ext                    # output extension, without the dot
        self.family = family
        self.func = func                  # func(sources, destination, op, prog) -> final path
        self.options = list(options)
        self.label = label or ext.upper()
        self.sub = sub                    # small line under the label on the wheel
        self.extra = extra                # True = lives on the 2nd wheel, behind the "+ MORE" petal

    @property
    def key(self):
        return f"{self.family}:{self.label}:{self.sub}"

    def defaults(self, saved=None):
        op = {o.key: o.default for o in self.options}
        if saved:
            op.update({k: v for k, v in saved.items() if k in op})
        return op


def free_path(folder, base, ext):
    """`base.ext`; if it exists, `base (1).ext`, `base (2).ext`..."""
    suffix = f".{ext}" if ext else ""
    p = os.path.join(folder, base + suffix)
    n = 1
    while os.path.exists(p):
        p = os.path.join(folder, f"{base} ({n}){suffix}")
        n += 1
    return p


def shorten_middle(t, n):
    """'a-very-long-file-name.webp' -> 'a-very-lo…name.webp' (keeps the extension visible)."""
    if len(t) <= n:
        return t
    a = (n - 1) * 2 // 3
    return t[:a] + "…" + t[-(n - 1 - a):]


DOUBLE_EXT = ("tar.gz", "tar.xz", "tar.bz2", "tar.zst")


def split_ext(path):
    name = os.path.basename(path.rstrip("/"))
    low = name.lower()
    for d in DOUBLE_EXT:
        if low.endswith("." + d):
            return name[: -len(d) - 1], d
    for d, same in (("tgz", "tar.gz"), ("txz", "tar.xz")):
        if low.endswith("." + d):
            return name[: -len(d) - 1], same
    base, ext = os.path.splitext(name)
    return base, ext[1:].lower()


def default_destination(source, target, output_dir=""):
    base, _ = split_ext(source)
    folder = output_dir or os.path.dirname(os.path.abspath(source.rstrip("/")))
    return free_path(folder, base, target.ext)


# ---------------------------------------------------------------- media helpers


def ffprobe_duration(path):
    if not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", path],
                           capture_output=True, text=True, timeout=20)
        return float(r.stdout.strip())
    except (ValueError, subprocess.SubprocessError):
        return None


def ffprobe_has(path, kind):
    """kind 'a' or 'v': does the file have a track of that kind?"""
    if not shutil.which("ffprobe"):
        return True
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", kind, "-show_entries",
                        "stream=index", "-of", "csv=p=0", path],
                       capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise ConversionError(tr("The file does not look like valid media (corrupted or wrong extension)."),
                              tr("Open the file in a player to confirm. If the extension is wrong, "
                                 "rename it to the right one."), r.stderr.strip()[-1500:])
    return bool(r.stdout.strip())


def seconds(txt):
    """'90', '1:30', '00:01:30.5' -> seconds. Empty -> None."""
    txt = (txt or "").strip().replace(",", ".")
    if not txt:
        return None
    try:
        parts = [float(p) for p in txt.split(":")]
    except ValueError:
        raise ConversionError(tr("Invalid time '{txt}'.").format(txt=txt),
                              tr("Use seconds (90), mm:ss (1:30) or hh:mm:ss.")) from None
    s = 0.0
    for p in parts:
        s = s * 60 + p
    return s


def ffmpeg_trim(op, dur):
    """-ss/-to arguments and the effective duration for the progress bar."""
    start, end = seconds(op.get("start")), seconds(op.get("end"))
    args = []
    if start:
        args += ["-ss", f"{start}"]
    if end:
        args += ["-to", f"{end}"]
    effective = dur
    if dur:
        effective = (end or dur) - (start or 0)
    return args, (effective if effective and effective > 0 else None)


def ffmpeg_base():
    return ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats"]


# ---------------------------------------------------------------- image

IMG_IN = {"png", "jpg", "jpeg", "jfif", "webp", "bmp", "gif", "tif", "tiff", "ico", "tga",
          "ppm", "pgm", "pbm", "heic", "heif", "avif", "psd", "pcx"}
BACKGROUNDS = [("white", tr("White")), ("black", tr("Black")), ("gray", tr("Gray"))]
BACKGROUND_RGB = {"white": (255, 255, 255), "black": (0, 0, 0), "gray": (128, 128, 128)}


def open_image(path):
    """PIL; if it fails (HEIC/AVIF), tries GdkPixbuf, which has a heif loader."""
    from PIL import Image
    try:
        im = Image.open(path)
        im.load()
        return im
    except Exception as e:
        first = e
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        pb = GdkPixbuf.Pixbuf.new_from_file(path)
        mode = "RGBA" if pb.get_has_alpha() else "RGB"
        return Image.frombuffer(mode, (pb.get_width(), pb.get_height()), pb.get_pixels(),
                                "raw", mode, pb.get_rowstride(), 1).copy()
    except Exception:
        pass
    raise ConversionError(tr("Could not open the image (corrupted or unsupported format)."),
                          tr("Open it in the image viewer to check. HEIC/AVIF need the GdkPixbuf "
                             "loader (sudo apt install heif-gdk-pixbuf)."), str(first))


def resize(im, op):
    from PIL import Image
    w, h = int(op.get("width") or 0), int(op.get("height") or 0)
    pct = int(op.get("scale") or 100)
    if pct != 100 and not (w or h):
        w = max(1, im.width * pct // 100)
    if not (w or h):
        return im
    if w and not h:
        h = max(1, round(im.height * w / im.width))
    elif h and not w:
        w = max(1, round(im.width * h / im.height))
    return im.resize((w, h), Image.LANCZOS)


def flatten(im, background):
    from PIL import Image
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        base = Image.new("RGB", im.size, BACKGROUND_RGB.get(background, (255, 255, 255)))
        base.paste(im, mask=im.getchannel("A"))
        return base
    return im.convert("RGB")


def frames(im):
    from PIL import ImageSequence
    return [f.copy() for f in ImageSequence.Iterator(im)]


def conv_image(sources, destination, op, prog, fmt):
    with open_image(sources[0]) as source:   # closes the file: the wheel runs all day long
        return _save_image(source, destination, op, prog, fmt)


def _save_image(im, destination, op, prog, fmt):
    from PIL import Image, ImageOps
    animated = getattr(im, "n_frames", 1) > 1
    exif = im.info.get("exif") if op.get("keep_exif") else None
    prog.fraction(0.2)
    if animated and fmt in ("GIF", "WEBP"):
        fs = [resize(f.convert("RGBA"), op) for f in frames(im)]
        dur = im.info.get("duration", 100)
        extra = {"quality": int(op.get("quality", 85))} if fmt == "WEBP" else {"disposal": 2}
        fs[0].save(destination, fmt, save_all=True, append_images=fs[1:], duration=dur,
                   loop=im.info.get("loop", 0), **extra)
        return destination
    im = ImageOps.exif_transpose(im) if op.get("auto_rotate", True) else im
    im = resize(im, op)
    prog.fraction(0.6)
    kw = {}
    if exif:
        kw["exif"] = exif
    q = int(op.get("quality", 90))
    if fmt == "JPEG":
        im = flatten(im, op.get("background"))
        kw.update(quality=q, optimize=True, progressive=bool(op.get("progressive", True)))
    elif fmt == "WEBP":
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA")
        kw.update(quality=q, lossless=bool(op.get("lossless")), method=5)
    elif fmt == "PNG":
        if im.mode not in ("RGB", "RGBA", "L", "LA", "P", "I", "1"):
            im = im.convert("RGBA")
        kw.update(optimize=True, compress_level=int(op.get("compression", 9)))
    elif fmt == "BMP":
        im = flatten(im, op.get("background"))
    elif fmt == "TIFF":
        kw.update(compression=op.get("tiff_compression", "tiff_lzw"))
    elif fmt == "GIF":
        im = im.convert("RGBA") if im.mode != "P" else im
    elif fmt == "ICO":
        sizes = [int(x) for x in str(op.get("sizes", "16,32,48,64,128,256")).split(",") if x.strip()]
        im = im.convert("RGBA")
        side = max(im.size)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
        im = square
        kw.update(sizes=[(s, s) for s in sizes])
    elif fmt == "PDF":
        im = flatten(im, op.get("background"))
        kw.update(resolution=float(op.get("dpi", 150)))
    im.save(destination, fmt, **kw)
    return destination


def conv_image_ffmpeg(sources, destination, op, prog, codec_args):
    """AVIF and the like: PIL cannot write it here, ffmpeg (libaom) does."""
    with open_image(sources[0]) as source:
        im = resize(source, op)
        im = im.copy() if im is source else im   # the source is closed when the block ends
    with tempfile.TemporaryDirectory(prefix="convert-wheel-") as tmp:
        png = os.path.join(tmp, "in.png")
        (im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im).save(png)
        crf = str(int(63 - int(op.get("quality", 70)) * 0.6))
        prog.run(ffmpeg_base() + ["-i", png] + codec_args(crf) + [destination])
    return destination


def conv_anim_video(sources, destination, op, prog):
    """Animated GIF/WebP -> mp4/webm."""
    v = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if destination.endswith(".webm"):
        v = ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "32"]
    scale = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    prog.run(ffmpeg_base() + ["-i", sources[0], "-vf", scale] + v + ["-an", destination],
             duration=ffprobe_duration(sources[0]))
    return destination


def image_options(quality=True, background=False, extra=()):
    ops = [Option("width", tr("Width (px, 0 = original)"), "number", 0, maximum=20000, step=10),
           Option("height", tr("Height (px, 0 = proportional)"), "number", 0, maximum=20000, step=10),
           Option("scale", tr("Scale (%) when width/height = 0"), "number", 100, minimum=1, maximum=800)]
    if quality:
        ops.append(Option("quality", tr("Quality (1-100)"), "number", 90, minimum=1, maximum=100))
    if background:
        ops.append(Option("background", tr("Background instead of transparency"), "choice", "white",
                          BACKGROUNDS))
    ops.append(Option("keep_exif", tr("Keep EXIF metadata (camera, GPS)"), "bool", False))
    return ops + list(extra)


def image_targets():
    def pil(fmt):
        return lambda o, d, op, p: conv_image(o, d, op, p, fmt)
    avif = lambda o, d, op, p: conv_image_ffmpeg(
        o, d, op, p, lambda crf: ["-c:v", "libaom-av1", "-still-picture", "1", "-crf", crf, "-b:v", "0"])
    return [
        Target("png", "image", pil("PNG"), image_options(False, extra=[
            Option("compression", tr("PNG compression (0-9)"), "number", 9, minimum=0, maximum=9)])),
        Target("jpg", "image", pil("JPEG"), image_options(True, True, [
            Option("progressive", tr("Progressive JPEG"), "bool", True)])),
        Target("webp", "image", pil("WEBP"), image_options(True, extra=[
            Option("lossless", tr("Lossless"), "bool", False)])),
        Target("avif", "image", avif, image_options(True), extra=True),
        Target("gif", "image", pil("GIF"), image_options(False)),
        Target("bmp", "image", pil("BMP"), image_options(False, True), extra=True),
        Target("tiff", "image", pil("TIFF"), image_options(False, extra=[
            Option("tiff_compression", tr("Compression"), "choice", "tiff_lzw",
                   [("tiff_lzw", "LZW"), ("tiff_deflate", "Deflate"), ("raw", tr("None"))])]), extra=True),
        Target("ico", "image", pil("ICO"), [
            Option("sizes", tr("Sizes (px, comma separated)"), "text", "16,32,48,64,128,256")],
               sub=tr_noop("icon")),
        Target("pdf", "image", pil("PDF"), image_options(False, True, [
            Option("dpi", tr("Page DPI"), "number", 150, minimum=36, maximum=1200)])),
    ]


ANIM_TARGETS = [
    Target("mp4", "image", conv_anim_video, sub=tr_noop("animation")),
    Target("webm", "image", conv_anim_video, sub=tr_noop("animation")),
]


def is_animated(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return getattr(im, "n_frames", 1) > 1
    except Exception:
        return False


# ---------------------------------------------------------------- svg


def conv_svg(sources, destination, op, prog, fmt):
    import fitz
    doc = fitz.open(sources[0])
    if fmt == "PDF":
        pdf = fitz.open("pdf", doc.convert_to_pdf())
        pdf.save(destination)
        return destination
    page = doc[0]
    width = int(op.get("width") or 0)
    zoom = width / page.rect.width if width else float(op.get("scale", 100)) / 100
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=fmt != "JPEG")
    from PIL import Image
    im = Image.open(io.BytesIO(pix.tobytes("png")))
    with tempfile.TemporaryDirectory(prefix="convert-wheel-") as tmp:
        png = os.path.join(tmp, "svg.png")
        im.save(png)
        op2 = dict(op, width=0, height=0, scale=100)
        return conv_image([png], destination, op2, prog, fmt)


def svg_targets():
    def f(fmt):
        return lambda o, d, op, p: conv_svg(o, d, op, p, fmt)
    size = [Option("width", tr("Width (px, 0 = use the scale)"), "number", 1024, maximum=20000, step=16),
            Option("scale", tr("Scale (%)"), "number", 100, minimum=10, maximum=2000)]
    return [Target("png", "svg", f("PNG"), size),
            Target("jpg", "svg", f("JPEG"), size + [
                Option("quality", tr("Quality"), "number", 92, minimum=1, maximum=100),
                Option("background", tr("Background"), "choice", "white", BACKGROUNDS)]),
            Target("webp", "svg", f("WEBP"), size + [
                Option("quality", tr("Quality"), "number", 90, minimum=1, maximum=100)]),
            Target("ico", "svg", f("ICO"), [
                Option("width", tr("Base resolution (px)"), "number", 256, maximum=1024),
                Option("sizes", tr("Sizes"), "text", "16,32,48,64,128,256")]),
            Target("pdf", "svg", f("PDF"))]


# ---------------------------------------------------------------- audio

AUDIO_IN = {"mp3", "wav", "ogg", "oga", "flac", "m4a", "aac", "opus", "wma", "aiff", "aif",
            "amr", "ac3", "mka", "wv", "ape", "mp2"}
SAMPLE_RATES = [("", tr("Original")), ("22050", tr("22.05 kHz")), ("44100", tr("44.1 kHz")), ("48000", "48 kHz")]
CHANNELS = [("", tr("Original")), ("1", tr("Mono")), ("2", tr("Stereo"))]
BITRATES = [("96k", "96 kbps"), ("128k", "128 kbps"), ("160k", "160 kbps"), ("192k", "192 kbps"),
            ("256k", "256 kbps"), ("320k", "320 kbps")]

AUDIO_CODEC = {
    "mp3": ["-c:a", "libmp3lame"], "ogg": ["-c:a", "libvorbis"], "opus": ["-c:a", "libopus"],
    "m4a": ["-c:a", "aac"], "aac": ["-c:a", "aac"], "flac": ["-c:a", "flac"], "wav": ["-c:a", "pcm_s16le"],
}


def audio_args(ext, op):
    a = list(AUDIO_CODEC[ext])
    if ext not in ("flac", "wav") and op.get("bitrate"):
        a += ["-b:a", op["bitrate"]]
    if op.get("rate"):
        a += ["-ar", op["rate"]]
    if op.get("channels"):
        a += ["-ac", op["channels"]]
    filters = []
    if op.get("normalize"):
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    vol = float(op.get("volume", 100) or 100)
    if vol != 100:
        filters.append(f"volume={vol / 100:.2f}")
    if filters:
        a += ["-af", ",".join(filters)]
    return a


def conv_audio(sources, destination, op, prog):
    ext = destination.rsplit(".", 1)[1]
    if not ffprobe_has(sources[0], "a"):
        raise ConversionError(tr("This file has no audio track."),
                              tr("Check that the video has sound. Without audio there is nothing to extract."))
    trim, dur = ffmpeg_trim(op, ffprobe_duration(sources[0]))
    prog.run(ffmpeg_base() + ["-i", sources[0]] + trim + ["-vn", "-map_metadata", "0"]
             + audio_args(ext, op) + [destination], duration=dur)
    return destination


def audio_options(ext):
    ops = []
    if ext not in ("flac", "wav"):
        ops.append(Option("bitrate", tr("Quality (bitrate)"), "choice",
                          "192k" if ext != "opus" else "128k", BITRATES))
    return ops + [
        Option("rate", tr("Sample rate"), "choice", "", SAMPLE_RATES),
        Option("channels", tr("Channels"), "choice", "", CHANNELS),
        Option("start", tr("Trim: start (e.g. 0:30)"), "text", ""),
        Option("end", tr("Trim: end (e.g. 2:10)"), "text", ""),
        Option("volume", tr("Volume (%)"), "number", 100, minimum=10, maximum=400, step=5),
        Option("normalize", tr("Normalize loudness (loudnorm -16 LUFS)"), "bool", False),
    ]


def audio_targets(family="audio"):
    return [Target(e, family, conv_audio, audio_options(e), sub=tr_noop("audio") if family == "video" else "")
            for e in ("mp3", "wav", "ogg", "flac", "m4a", "opus")]


# ---------------------------------------------------------------- video

VIDEO_IN = {"mp4", "mkv", "webm", "avi", "mov", "wmv", "flv", "m4v", "mpg", "mpeg", "3gp",
            "ts", "mts", "m2ts", "ogv", "vob"}
RESOLUTIONS = [("", tr("Original")), ("2160", "4K (2160p)"), ("1440", "1440p"), ("1080", "1080p"),
               ("720", "720p"), ("480", "480p"), ("360", "360p")]
QUALITIES = [("18", tr("High (large file)")), ("23", tr("Medium")), ("28", tr("Low")), ("33", tr("Minimum"))]
FPS = [("", tr("Original")), ("60", "60"), ("30", "30"), ("24", "24"), ("15", "15")]
PRESETS = [("veryfast", tr("Fast")), ("medium", tr("Balanced")), ("slow", tr("Slow (smaller file)"))]


def conv_video(sources, destination, op, prog):
    ext = destination.rsplit(".", 1)[1]
    src = sources[0]
    trim, dur = ffmpeg_trim(op, ffprobe_duration(src))
    cmd = ffmpeg_base() + ["-i", src] + trim
    if op.get("copy"):
        cmd += ["-map", "0", "-c", "copy"]
        if op.get("no_audio"):
            cmd += ["-an"]
        prog.run(cmd + [destination], duration=dur)
        return destination
    filters = []
    if op.get("resolution"):
        filters.append(f"scale=-2:{op['resolution']}")
    else:
        filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    if op.get("fps"):
        filters.append(f"fps={op['fps']}")
    cmd += ["-vf", ",".join(filters)]
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
    if op.get("no_audio"):
        cmd += ["-an"]
    else:
        cmd += aud
    prog.run(cmd + [destination], duration=dur)
    return destination


def conv_gif(sources, destination, op, prog):
    trim, dur = ffmpeg_trim(op, ffprobe_duration(sources[0]))
    fps, width = op.get("gif_fps", "15"), op.get("gif_width", "480")
    scale = f"scale={width}:-1:flags=lanczos," if width else ""
    graph = (f"fps={fps},{scale}split[a][b];[a]palettegen=stats_mode=diff[p];"
             f"[b][p]paletteuse=dither=bayer:bayer_scale=4")
    prog.run(ffmpeg_base() + trim + ["-i", sources[0], "-filter_complex", graph, "-loop",
                                     "0" if op.get("loop", True) else "-1", destination], duration=dur)
    return destination


def conv_frame(sources, destination, op, prog):
    t = seconds(op.get("at")) or 0
    dur = ffprobe_duration(sources[0]) or 0
    if dur and t >= dur:
        prog.text(tr("{t}s is past the end ({dur}s): used the middle of the video")
                  .format(t=f"{t:g}", dur=f"{dur:.1f}"))
        t = dur / 2
    prog.run(ffmpeg_base() + ["-ss", str(t), "-i", sources[0], "-frames:v", "1",
                              "-q:v", "2", destination])
    return destination


def video_options(remux_default=False):
    return [
        Option("resolution", tr("Resolution"), "choice", "", RESOLUTIONS),
        Option("crf", tr("Quality"), "choice", "23", QUALITIES),
        Option("fps", tr("Frames per second"), "choice", "", FPS),
        Option("preset", tr("Encoding speed"), "choice", "medium", PRESETS),
        Option("start", tr("Trim: start (e.g. 0:30)"), "text", ""),
        Option("end", tr("Trim: end (e.g. 2:10)"), "text", ""),
        Option("no_audio", tr("Remove the audio"), "bool", False),
        Option("copy", tr("Copy without re-encoding (fast, ignores resolution/quality)"), "bool",
               remux_default),
    ]


def video_targets():
    gif_ops = [Option("gif_fps", tr("Frames per second"), "choice", "15",
                      [("10", "10"), ("15", "15"), ("20", "20"), ("25", "25")]),
               Option("gif_width", tr("Width"), "choice", "480",
                      [("320", "320 px"), ("480", "480 px"), ("640", "640 px"), ("800", "800 px"),
                       ("", tr("Original"))]),
               Option("start", tr("Trim: start"), "text", ""),
               Option("end", tr("Trim: end"), "text", ""),
               Option("loop", tr("Loop forever"), "bool", True)]
    return [
        Target("mp4", "video", conv_video, video_options()),
        Target("mkv", "video", conv_video, video_options(True)),
        Target("webm", "video", conv_video, video_options()),
        Target("mov", "video", conv_video, video_options()),
        Target("avi", "video", conv_video, video_options()),
        Target("gif", "video", conv_gif, gif_ops, sub=tr_noop("animated")),
        Target("jpg", "video", conv_frame, [Option("at", tr("Frame time (e.g. 0:05)"), "text", "1")],
               label="JPG", sub=tr_noop("1 frame")),
    ] + [a for a in audio_targets("video") if a.ext in ("mp3", "wav", "m4a")]


# ---------------------------------------------------------------- pdf


def pages(spec, total):
    spec = (spec or "").strip()
    if not spec or spec.lower() in ("all", "todas", "tudo", "*"):
        return list(range(total))
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                out += range(int(a) - 1, min(int(b or total), total))
            else:
                out.append(int(part) - 1)
        except ValueError:
            raise ConversionError(tr("Invalid pages '{spec}'.").format(spec=spec),
                                  tr("Use something like: 1-3,5,8-")) from None
    out = [p for p in out if 0 <= p < total]
    if not out:
        raise ConversionError(tr("No valid page in '{spec}' (the PDF has {total}).").format(spec=spec, total=total),
                              tr("Adjust the page range in ⚙."))
    return out


def open_pdf(path):
    import fitz
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise ConversionError(tr("Could not open the PDF (corrupted?)."),
                              tr("Open it in a PDF reader to check."), str(e)) from e
    if doc.needs_pass:
        raise ConversionError(tr("Password-protected PDF."), tr("Remove the PDF password before converting."))
    return doc


def page_text(p, total):
    return tr("page {n} of {total}").format(n=p + 1, total=total)


def files_per_page(destination, ext, pgs):
    """One page = the destination itself; several = folder `name/` with page-001.ext..."""
    if len(pgs) == 1:
        return [destination]
    base = destination[: -len(ext) - 1]
    folder = base
    n = 1
    while os.path.exists(folder):
        folder = f"{base} ({n})"
        n += 1
    os.makedirs(folder)
    return [os.path.join(folder, f"page-{p + 1:03d}.{ext}") for p in pgs]


def conv_pdf_svg(sources, destination, op, prog):
    doc = open_pdf(sources[0])
    pgs = pages(op.get("pages"), len(doc))
    outputs = files_per_page(destination, "svg", pgs)
    for i, (p, d) in enumerate(zip(pgs, outputs, strict=True)):
        prog.check()
        prog.text(page_text(p, len(doc)))
        with open(d, "w", encoding="utf-8") as f:
            f.write(doc[p].get_svg_image(text_as_path=bool(op.get("text_as_curves", True))))
        prog.fraction((i + 1) / len(pgs))
    return outputs[0] if len(outputs) == 1 else os.path.dirname(outputs[0])


def conv_pdf_tiff(sources, destination, op, prog):
    """A single .tiff with every page (multipage), the fax/archive format."""
    import fitz
    from PIL import Image
    doc = open_pdf(sources[0])
    pgs = pages(op.get("pages"), len(doc))
    zoom = float(op.get("dpi", 150)) / 72
    ims = []
    for i, p in enumerate(pgs):
        prog.check()
        prog.text(page_text(p, len(doc)))
        pix = doc[p].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        ims.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        prog.fraction((i + 1) / (len(pgs) + 1))
    ims[0].save(destination, "TIFF", save_all=True, append_images=ims[1:], compression="tiff_lzw",
                dpi=(zoom * 72, zoom * 72))
    return destination


def conv_pdf_image(sources, destination, op, prog, fmt):
    import fitz
    doc = open_pdf(sources[0])
    pgs = pages(op.get("pages"), len(doc))
    zoom = float(op.get("dpi", 150)) / 72
    ext = destination.rsplit(".", 1)[1]
    if op.get("join") and len(pgs) > 1:
        return pdf_single_image(doc, pgs, zoom, destination, op, prog, fmt)
    outputs = files_per_page(destination, ext, pgs)
    for i, (p, d) in enumerate(zip(pgs, outputs, strict=True)):
        prog.check()
        prog.text(page_text(p, len(doc)))
        pix = doc[p].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        if fmt == "PNG":
            pix.save(d)
        else:
            from PIL import Image
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            kw = {"quality": int(op.get("quality", 90))} if fmt in ("JPEG", "WEBP") else {}
            im.save(d, fmt, **kw)
        prog.fraction((i + 1) / len(pgs))
    return outputs[0] if len(outputs) == 1 else os.path.dirname(outputs[0])


MAX_SIDE = {"JPEG": 65500, "WEBP": 16383, "PNG": 300000}
MAX_PIXELS = 150e6   # ~450 MB in RGB; above that the DPI drops so the PC does not go down


def pdf_single_image(doc, pgs, zoom, destination, op, prog, fmt):
    """Every page stitched into one image (in a column or in a row)."""
    import fitz
    from PIL import Image
    vertical = op.get("direction", "vertical") == "vertical"
    gap = int(op.get("gap", 0))
    rects = [doc[p].rect for p in pgs]

    def measure(z):
        ws = [round(r.width * z) for r in rects]
        hs = [round(r.height * z) for r in rects]
        spacing = gap * (len(pgs) - 1)
        return (max(ws), sum(hs) + spacing) if vertical else (sum(ws) + spacing, max(hs))

    W, H = measure(zoom)
    f = min(1.0, MAX_SIDE.get(fmt, 65500) / max(W, H), math.sqrt(MAX_PIXELS / (W * H)))
    if f < 1:
        zoom *= f * 0.995
        W, H = measure(zoom)
        prog.text(tr("image too large: lowered to {dpi} DPI").format(dpi=f"{zoom * 72:.0f}"))
    base = Image.new("RGB", (W, H), BACKGROUND_RGB.get(op.get("background"), (255, 255, 255)))
    pos = 0
    for i, p in enumerate(pgs):
        prog.check()
        pix = doc[p].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if vertical:
            base.paste(im, ((W - im.width) // 2, pos))
            pos += im.height + gap
        else:
            base.paste(im, (pos, (H - im.height) // 2))
            pos += im.width + gap
        prog.fraction((i + 1) / (len(pgs) + 1))
    prog.text(tr("{n} pages → {w}×{h} px, saving…").format(n=len(pgs), w=W, h=H))
    kw = {"quality": int(op.get("quality", 90))} if fmt in ("JPEG", "WEBP") else {"optimize": False}
    base.save(destination, fmt, **kw)
    return destination


def conv_pdf_text(sources, destination, op, prog):
    doc = open_pdf(sources[0])
    pgs = pages(op.get("pages"), len(doc))
    mode = "html" if destination.endswith(".html") else "text"
    parts = []
    for i, p in enumerate(pgs):
        prog.check()
        parts.append(doc[p].get_text(mode))
        prog.fraction((i + 1) / len(pgs))
    if mode == "html":
        body = "\n".join(parts)
        txt = f"<!doctype html><meta charset='utf-8'><title>{html.escape(split_ext(sources[0])[0])}</title>\n{body}"
    else:
        txt = "\n\f\n".join(parts) if op.get("page_breaks") else "\n\n".join(parts)
        if not txt.strip():
            raise ConversionError(tr("The PDF has no selectable text (it is a scanned image)."),
                                  tr("It needs OCR. Install it with: sudo apt install ocrmypdf "
                                     "and run: ocrmypdf input.pdf output.pdf"))
    with open(destination, "w", encoding="utf-8") as f:
        f.write(txt)
    return destination


def conv_pdf_md(sources, destination, op, prog):
    doc = open_pdf(sources[0])
    pgs = pages(op.get("pages"), len(doc))
    lines = []
    for p in pgs:
        prog.check()
        for block in doc[p].get_text("dict")["blocks"]:
            for ln in block.get("lines", []):
                spans = ln["spans"]
                txt = "".join(s["text"] for s in spans).strip()
                if not txt:
                    continue
                size = max(s["size"] for s in spans)
                bold = all(s["flags"] & 16 for s in spans)
                if size >= 18:
                    lines.append(f"\n# {txt}\n")
                elif size >= 14 or (bold and len(txt) < 80):
                    lines.append(f"\n## {txt}\n")
                else:
                    lines.append(txt)
            lines.append("")
    with open(destination, "w", encoding="utf-8") as f:
        f.write(re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n")
    return destination


def conv_pdf_compress(sources, destination, op, prog):
    prog.text(tr("ghostscript compressing…"))
    prog.run(["gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.6", f"-dPDFSETTINGS=/{op.get('level', 'ebook')}",
              "-dNOPAUSE", "-dQUIET", "-dBATCH", f"-sOutputFile={destination}", sources[0]], timeout=600)
    before, after = os.path.getsize(sources[0]), os.path.getsize(destination)
    prog.text(f"{before / 1e6:.1f} MB → {after / 1e6:.1f} MB")
    return destination


def pdf_image_options(join, quality):
    ops = [Option("dpi", tr("Resolution (DPI)"), "number", 150, minimum=36, maximum=600, step=10),
           Option("pages", tr("Pages (empty = all; e.g. 1-3,5)"), "text", ""),
           Option("join", tr("Join every page into a single image"), "bool", join),
           Option("direction", tr("Join as"), "choice", "vertical",
                  [("vertical", tr("Column (one below the other)")), ("horizontal", tr("Row (side by side)"))]),
           Option("gap", tr("Space between pages (px)"), "number", 20 if join else 0, minimum=0, maximum=400),
           Option("background", tr("Space color"), "choice", "gray" if join else "white", BACKGROUNDS)]
    if quality:
        ops.append(Option("quality", tr("Quality"), "number", 90, minimum=1, maximum=100))
    return ops


def pdf_targets():
    pgs = Option("pages", tr("Pages (empty = all; e.g. 1-3,5)"), "text", "")
    png = lambda o, d, op, p: conv_pdf_image(o, d, op, p, "PNG")
    jpg = lambda o, d, op, p: conv_pdf_image(o, d, op, p, "JPEG")
    webp = lambda o, d, op, p: conv_pdf_image(o, d, op, p, "WEBP")
    return [
        Target("png", "pdf", png, pdf_image_options(False, False), sub=tr_noop("pages")),
        Target("jpg", "pdf", jpg, pdf_image_options(False, True), sub=tr_noop("pages")),
        Target("png", "pdf", png, pdf_image_options(True, False), sub=tr_noop("1 image")),
        Target("jpg", "pdf", jpg, pdf_image_options(True, True), sub=tr_noop("1 image")),
        Target("txt", "pdf", conv_pdf_text, [pgs, Option("page_breaks", tr("Mark page breaks (\\f)"), "bool", False)]),
        Target("md", "pdf", conv_pdf_md, [pgs], sub=tr_noop("approximate")),
        Target("html", "pdf", conv_pdf_text, [pgs], extra=True),
        Target("docx", "pdf", conv_office, [], sub="LibreOffice"),
        Target("pdf", "pdf", conv_pdf_compress, [Option("level", tr("Level"), "choice", "ebook", [
            ("screen", tr("Maximum (72 dpi, screen)")), ("ebook", tr("Medium (150 dpi)")),
            ("printer", tr("Light (300 dpi, print)"))])], label="PDF", sub=tr_noop("compress")),
        # extras: 2nd wheel
        Target("webp", "pdf", webp, pdf_image_options(False, True), sub=tr_noop("pages"), extra=True),
        Target("webp", "pdf", webp, pdf_image_options(True, True), sub=tr_noop("1 image"), extra=True),
        Target("svg", "pdf", conv_pdf_svg, [pgs, Option("text_as_curves", tr("Text as curves (faithful, not editable)"),
                                                        "bool", True)], sub=tr_noop("vector"), extra=True),
        Target("tiff", "pdf", conv_pdf_tiff, [Option("dpi", tr("Resolution (DPI)"), "number", 200, minimum=36,
                                                     maximum=600, step=10), pgs],
               sub=tr_noop("multipage"), extra=True),
        Target("bmp", "pdf", lambda o, d, op, p: conv_pdf_image(o, d, op, p, "BMP"), pdf_image_options(False, False),
               sub=tr_noop("pages"), extra=True),
    ]


# ---------------------------------------------------------------- text, markdown, html

TEXT_IN = {"txt", "text", "log", "md", "markdown", "html", "htm", "rst"}

DOC_CSS = """
body { font-family: sans-serif; font-size: %(font)spt; line-height: 1.4; }
h1 { font-size: 1.8em; } h2 { font-size: 1.4em; } h3 { font-size: 1.15em; }
pre, code { font-family: monospace; font-size: 0.9em; background-color: #f2f2f2; }
blockquote { color: #555; margin-left: 12pt; }
table { border-collapse: collapse; } td, th { border: 1px solid #999; padding: 3pt; }
"""


def read_text(path):
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def text_to_html(txt):
    pars = [p for p in re.split(r"\n\s*\n", txt) if p.strip()]
    return "\n".join("<p>" + html.escape(p).replace("\n", "<br>") + "</p>" for p in pars)


def md_to_html(txt):
    import markdown
    return markdown.markdown(txt, extensions=["extra", "sane_lists", "toc"])


class _HtmlToText(HTMLParser):
    """HTML -> plain text or simple markdown (h1-h6, p, lists, links, emphasis, code)."""

    def __init__(self, md):
        super().__init__(convert_charrefs=True)
        self.md, self.out, self.href, self.pre, self.skip = md, [], [], 0, 0
        self.lists = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("\n\n" + ("#" * int(tag[1]) + " " if self.md else ""))
        elif tag in ("p", "div", "section", "article", "table", "blockquote"):
            self.out.append("\n\n" + ("> " if tag == "blockquote" and self.md else ""))
        elif tag in ("br", "tr"):
            self.out.append("\n")
        elif tag in ("ul", "ol"):
            self.lists.append([tag, 0])
        elif tag == "li":
            n = self.lists[-1] if self.lists else ["ul", 0]
            n[1] += 1
            mark = f"{n[1]}. " if n[0] == "ol" else ("- " if self.md else "• ")
            self.out.append("\n" + "  " * max(0, len(self.lists) - 1) + mark)
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
            self.skip = max(0, self.skip - 1)
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
            if self.lists:
                self.lists.pop()
            self.out.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        self.out.append(data if self.pre else re.sub(r"\s+", " ", data))

    def result(self):
        t = "".join(self.out)
        t = re.sub(r"[ \t]+\n", "\n", t)
        return re.sub(r"\n{3,}", "\n\n", t).strip() + "\n"


def html_to(txt, md):
    p = _HtmlToText(md)
    p.feed(txt)
    return p.result()


def as_html(source):
    """Reads txt/md/html and returns (html body, title)."""
    base, ext = split_ext(source)
    txt = read_text(source)
    if ext in ("md", "markdown", "rst"):
        return md_to_html(txt), base
    if ext in ("html", "htm"):
        m = re.search(r"<body[^>]*>(.*)</body>", txt, re.S | re.I)
        return (m.group(1) if m else txt), base
    return text_to_html(txt), base


def html_to_pdf(body, destination, op, prog):
    import fitz
    size = {"a4": fitz.paper_rect("a4"), "letter": fitz.paper_rect("letter"),
            "a5": fitz.paper_rect("a5")}[op.get("page", "a4")]
    m = float(op.get("margin", 20)) * 72 / 25.4
    story = fitz.Story(html=body, user_css=DOC_CSS % {"font": op.get("font_size", 11)})
    writer = fitz.DocumentWriter(destination)
    more, n = True, 0
    while more:
        prog.check()
        dev = writer.begin_page(size)
        more, _ = story.place(size + (m, m, -m, -m))
        story.draw(dev)
        writer.end_page()
        n += 1
        prog.text(tr("page {n}").format(n=n))
    writer.close()
    return destination


def conv_text(sources, destination, op, prog):
    src = sources[0]
    _, ext_in = split_ext(src)
    ext = destination.rsplit(".", 1)[1]
    txt = read_text(src)
    is_md = ext_in in ("md", "markdown", "rst")
    is_html = ext_in in ("html", "htm")
    if ext == "pdf":
        body, _ = as_html(src)
        return html_to_pdf(body, destination, op, prog)
    if ext in ("docx", "odt", "rtf"):
        body, title = as_html(src)
        with tempfile.TemporaryDirectory(prefix="convert-wheel-") as tmp:
            h = os.path.join(tmp, split_ext(destination)[0] + ".html")
            with open(h, "w", encoding="utf-8") as f:
                f.write(f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
                        f"</head><body>{body}</body></html>")
            return conv_office([h], destination, op, prog, in_filter="HTML (StarWriter)")
    if ext == "html":
        body, title = as_html(src)
        output = (f"<!doctype html>\n<html lang='{HTML_LANG}'><head><meta charset='utf-8'>\n"
                  f"<title>{html.escape(title)}</title>\n<style>{DOC_CSS % {'font': 12}}"
                  f"body{{max-width:46em;margin:2em auto;padding:0 1em}}</style></head>\n"
                  f"<body>\n{body}\n</body></html>\n")
    elif ext == "md":
        if is_html:
            output = html_to(txt, md=True)
        else:
            output = txt if txt.endswith("\n") else txt + "\n"
            if op.get("title"):
                output = f"# {split_ext(src)[0]}\n\n" + output
    elif ext == "txt":
        if is_html:
            output = html_to(txt, md=False)
        elif is_md:
            output = html_to(md_to_html(txt), md=False)
        else:
            output = txt
    else:
        raise ConversionError(tr("Text to .{ext} is not implemented.").format(ext=ext))
    with open(destination, "w", encoding="utf-8") as f:
        f.write(output)
    prog.fraction(1)
    return destination


def text_targets(ext_in):
    pdf_ops = [Option("page", tr("Page size"), "choice", "a4",
                      [("a4", "A4"), ("letter", tr("Letter")), ("a5", "A5")]),
               Option("font_size", tr("Font size (pt)"), "number", 11, minimum=6, maximum=32),
               Option("margin", tr("Margin (mm)"), "number", 20, minimum=0, maximum=60)]
    md_ops = [Option("title", tr("Use the file name as # title"), "bool", False)]
    every = [Target("md", "text", conv_text, md_ops), Target("txt", "text", conv_text),
             Target("html", "text", conv_text), Target("pdf", "text", conv_text, pdf_ops),
             Target("docx", "text", conv_text, sub="Word"), Target("odt", "text", conv_text, sub="Writer")]
    same = {"markdown": "md", "htm": "html", "text": "txt", "log": "txt"}.get(ext_in, ext_in)
    return [a for a in every if a.ext != same]


# ---------------------------------------------------------------- office (LibreOffice)

DOC_IN = {"docx", "doc", "odt", "rtf", "wpd", "pages"}
SHEET_IN = {"xlsx", "xls", "ods", "xlsm"}
SLIDES_IN = {"pptx", "ppt", "odp", "pps", "ppsx"}

OUTPUT_FILTER = {
    "pdf": "pdf", "docx": 'docx:"MS Word 2007 XML"', "odt": "odt", "rtf": "rtf",
    "txt": "txt:Text (encoded):UTF8", "html": "html", "xlsx": 'xlsx:"Calc MS Excel 2007 XML"',
    "ods": "ods", "csv": "csv:Text - txt - csv (StarCalc):44,34,76,1", "pptx": "pptx", "odp": "odp",
    "doc": 'doc:"MS Word 97"', "xls": 'xls:"MS Excel 97"', "png": "png",
}


def conv_office(sources, destination, op, prog, in_filter=None):
    if not shutil.which("soffice"):
        raise ConversionError(tr("LibreOffice is not installed."),
                              tr("Install it with:\n  sudo apt install {pkg}").format(pkg="libreoffice"))
    ext = destination.rsplit(".", 1)[1]
    out_filter = OUTPUT_FILTER.get(ext, ext).replace('"', "")
    src = sources[0]
    if src.lower().endswith(".pdf"):
        in_filter = "writer_pdf_import"
    with tempfile.TemporaryDirectory(prefix="convert-wheel-lo-") as tmp:
        profile = f"file://{tmp}/profile"   # own profile: does not clash with an open LibreOffice
        cmd = ["soffice", f"-env:UserInstallation={profile}", "--headless", "--norestore"]
        if in_filter:
            cmd.append(f"--infilter={in_filter}")
        cmd += ["--convert-to", out_filter, "--outdir", tmp, src]
        prog.text(tr("LibreOffice converting…"))
        prog.fraction(0.3)
        prog.run(cmd, timeout=300)
        produced = os.path.join(tmp, split_ext(src)[0] + "." + ext)
        if not os.path.exists(produced):
            others = [f for f in os.listdir(tmp) if f != "profile"]
            if len(others) == 1:
                produced = os.path.join(tmp, others[0])
            else:
                raise ConversionError(tr("LibreOffice did not produce the output file."),
                                      tr("This kind of document may not convert to .{ext}. Try PDF, or open "
                                         "it in LibreOffice and use 'Save as'.").format(ext=ext))
        shutil.move(produced, destination)
    return destination


def office_targets(ext_in):
    if ext_in in DOC_IN:
        exts = ["pdf", "docx", "odt", "rtf", "txt", "html", "doc"]
    elif ext_in in SHEET_IN:
        exts = ["pdf", "xlsx", "ods", "csv", "html", "xls"]
    else:
        exts = ["pdf", "pptx", "odp", "png"]
    subs = {"png": tr_noop("1st slide"), "csv": tr_noop("1st sheet"), "doc": "Word 97", "xls": "Excel 97"}
    return [Target(e, "office", conv_office, sub=subs.get(e, "")) for e in exts if e != ext_in]


# ---------------------------------------------------------------- data (json, yaml, csv)

DATA_IN = {"json", "yaml", "yml", "csv", "tsv", "toml"}


def read_data(path):
    _, ext = split_ext(path)
    txt = read_text(path)
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
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError(tr("The .{ext} has a syntax error.").format(ext=ext),
                              tr("Open it in an editor and fix the line shown in the details."), str(e)) from e


def conv_data(sources, destination, op, prog):
    data = read_data(sources[0])
    ext = destination.rsplit(".", 1)[1]
    if ext in ("xlsx", "ods"):
        with tempfile.TemporaryDirectory(prefix="convert-wheel-") as tmp:
            c = os.path.join(tmp, split_ext(destination)[0] + ".csv")
            write_csv(data, c, ",")
            return conv_office([c], destination, op, prog, in_filter="CSV:44,34,76")
    if ext == "json":
        output = json.dumps(data, ensure_ascii=False, indent=int(op.get("indent", 2)) or None) + "\n"
    elif ext in ("yaml", "yml"):
        import yaml
        output = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    elif ext in ("csv", "tsv"):
        write_csv(data, destination, "\t" if ext == "tsv" else op.get("delim", ","))
        return destination
    else:
        raise ConversionError(tr("Output .{ext} is not supported for data.").format(ext=ext))
    with open(destination, "w", encoding="utf-8") as f:
        f.write(output)
    return destination


def write_csv(data, destination, delim):
    if isinstance(data, dict):
        # {"key": [..]} with a single list becomes that list; otherwise, a single row
        lists = [v for v in data.values() if isinstance(v, list)]
        data = lists[0] if len(lists) == 1 else [data]
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise ConversionError(tr("This data is not a table (list of objects)."),
                              tr("CSV/spreadsheet only comes out of a list of objects, e.g. [{\"name\":..}, ..]. "
                                 "Use JSON or YAML as output."))
    columns = []
    for row in data:
        for k in row:
            if k not in columns:
                columns.append(k)
    with open(destination, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, delimiter=delim)
        w.writeheader()
        for row in data:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                        for k, v in row.items()})


def data_targets(ext_in):
    exts = ["json", "yaml", "csv", "tsv", "xlsx", "ods"]
    same = {"yml": "yaml"}.get(ext_in, ext_in)
    ops = {"json": [Option("indent", tr("Indentation (0 = compact)"), "number", 2, minimum=0, maximum=8)],
           "csv": [Option("delim", tr("Separator"), "choice", ",", [(",", tr("Comma")), (";", tr("Semicolon")),
                                                                     ("|", tr("Pipe |"))])]}
    return [Target(e, "data", conv_data, ops.get(e, []), sub=tr_noop("spreadsheet") if e in ("xlsx", "ods") else "")
            for e in exts if e != same]


# ---------------------------------------------------------------- subtitles

SUBTITLE_IN = {"srt", "vtt", "ass", "ssa"}


def conv_subtitle(sources, destination, op, prog):
    prog.run(ffmpeg_base() + ["-sub_charenc", op.get("encoding", "UTF-8"), "-i", sources[0], destination])
    return destination


def subtitle_targets(ext_in):
    ops = [Option("encoding", tr("Input encoding"), "choice", "UTF-8",
                  [("UTF-8", "UTF-8"), ("CP1252", tr("Windows-1252 (old Western subtitles)")),
                   ("ISO-8859-1", "Latin-1")])]
    return [Target(e, "subtitle", conv_subtitle, ops) for e in ("srt", "vtt", "ass")
            if e != ext_in.replace("ssa", "ass")]


# ---------------------------------------------------------------- fonts

FONT_IN = {"ttf", "otf", "woff", "woff2"}


def conv_font(sources, destination, op, prog):
    from fontTools.ttLib import TTFont
    ext = destination.rsplit(".", 1)[1]
    try:
        f = TTFont(sources[0])
    except Exception as e:
        raise ConversionError(tr("Could not read the font."), tr("Corrupted or unsupported font file."), str(e)) from e
    has_cff = "CFF " in f or "CFF2" in f
    if ext == "ttf" and has_cff:
        raise ConversionError(tr("This font is CFF (PostScript outlines); turning it into .ttf means converting "
                                 "the curves."),
                              tr("Use .otf as output (same content), or woff/woff2 for the web."))
    if ext == "otf" and not has_cff:
        raise ConversionError(tr("This font is TrueType; an .otf with TrueType outlines only changes the name."),
                              tr("Use .ttf as output, or woff/woff2 for the web."))
    f.flavor = ext if ext in ("woff", "woff2") else None
    f.save(destination)
    return destination


def font_targets(ext_in):
    return [Target(e, "font", conv_font, sub=tr_noop("web") if e.startswith("woff") else "")
            for e in ("ttf", "otf", "woff", "woff2") if e != ext_in]


# ---------------------------------------------------------------- archives and folders

ARCHIVE_IN = {"zip", "tar", "tar.gz", "tar.xz", "tar.bz2"}
TAR_MODE = {"tar": "w", "tar.gz": "w:gz", "tar.xz": "w:xz", "tar.bz2": "w:bz2"}


def _files_of(source):
    """[(real path, name inside the archive)] of a folder or a file."""
    source = source.rstrip("/")
    root = os.path.basename(source)
    if os.path.isfile(source):
        return [(source, root)]
    out = []
    for d, _, fs in os.walk(source):
        for f in fs:
            p = os.path.join(d, f)
            out.append((p, os.path.join(root, os.path.relpath(p, source))))
    return out


def pack(items, destination, ext, prog):
    total = max(1, len(items))
    if ext == "zip":
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for i, (p, name) in enumerate(items):
                prog.check()
                z.write(p, name)
                prog.fraction((i + 1) / total)
    else:
        with tarfile.open(destination, TAR_MODE[ext]) as t:
            for i, (p, name) in enumerate(items):
                prog.check()
                t.add(p, name, recursive=False)
                prog.fraction((i + 1) / total)
    return destination


def conv_folder(sources, destination, op, prog):
    ext = split_ext(destination)[1]
    items = []
    for s in sources:
        items += _files_of(s)
    return pack(items, destination, ext, prog)


def conv_archive(sources, destination, op, prog):
    src = sources[0]
    ext = split_ext(destination)[1]
    with tempfile.TemporaryDirectory(prefix="convert-wheel-") as tmp:
        prog.text(tr("extracting…"))
        try:
            if zipfile.is_zipfile(src):
                with zipfile.ZipFile(src) as z:
                    z.extractall(tmp)
            else:
                with tarfile.open(src) as t:
                    t.extractall(tmp, filter="data")
        except (zipfile.BadZipFile, tarfile.TarError, EOFError) as e:
            raise ConversionError(tr("Corrupted or password-protected archive."),
                                  tr("Try opening it in the archive manager. Password-protected zip is not "
                                     "supported."), str(e)) from e
        items = []
        for d, _, fs in os.walk(tmp):
            for f in fs:
                p = os.path.join(d, f)
                items.append((p, os.path.relpath(p, tmp)))
        prog.text(tr("packing…"))
        return pack(items, destination, ext, prog)


def archive_targets(ext_in, folder=False):
    exts = ["zip", "tar.gz", "tar.xz", "tar.bz2", "tar"]
    func = conv_folder if folder else conv_archive
    return [Target(e, "archive", func, label=e.upper(), sub=tr_noop("pack") if folder else "")
            for e in exts if e != ext_in]


# ---------------------------------------------------------------- routing


def family_of(path):
    if os.path.isdir(path):
        return "folder"
    _, ext = split_ext(path)
    for fam, exts in (("image", IMG_IN), ("audio", AUDIO_IN), ("video", VIDEO_IN), ("text", TEXT_IN),
                      ("office", DOC_IN | SHEET_IN | SLIDES_IN), ("data", DATA_IN),
                      ("subtitle", SUBTITLE_IN), ("font", FONT_IN), ("archive", ARCHIVE_IN)):
        if ext in exts:
            return fam
    if ext == "svg":
        return "svg"
    if ext == "pdf":
        return "pdf"
    try:  # no known extension: guess the type from the content
        r = subprocess.run(["file", "-b", "--mime-type", path], capture_output=True, text=True, timeout=5)
        mime = r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if mime == "application/pdf":
        return "pdf"
    if mime.startswith("text/"):
        return "text"
    return None


def targets_for(path):
    fam = family_of(path)
    _, ext = split_ext(path)
    ext = {"jpeg": "jpg", "jfif": "jpg", "tif": "tiff", "htm": "html", "yml": "yaml", "markdown": "md"}.get(ext, ext)
    if fam == "image":
        targets = [a for a in image_targets() if a.ext != ext]
        if ext in ("jpg", "png", "webp"):  # same format = recompress
            same = next(a for a in image_targets() if a.ext == ext)
            same.label, same.sub = ext.upper(), tr_noop("compress")
            targets.append(same)
        if ext in ("gif", "webp") and is_animated(path):
            targets = ANIM_TARGETS + targets
        return targets
    if fam == "svg":
        return svg_targets()
    if fam == "audio":
        return [a for a in audio_targets() if a.ext != ext]
    if fam == "video":
        targets = [a for a in video_targets() if a.ext != ext or a.family != "video"]
        if ext == "mp4":
            comp = Target("mp4", "video", conv_video, video_options(), label="MP4", sub=tr_noop("compress"))
            for o in comp.options:
                if o.key == "crf":
                    o.default = "28"
            targets.append(comp)
        return targets
    if fam == "pdf":
        return pdf_targets()
    if fam == "text":
        return text_targets(ext)
    if fam == "office":
        return office_targets(ext)
    if fam == "data":
        return data_targets(ext)
    if fam == "subtitle":
        return subtitle_targets(ext)
    if fam == "font":
        return font_targets(ext)
    if fam == "archive":
        return archive_targets(ext)
    if fam == "folder":
        return archive_targets("", folder=True)
    return []


def convert(sources, target, op, destination, prog):
    """Runs the conversion; removes the partial destination on failure. Returns the final path."""
    for s in sources:
        if not os.path.exists(s):
            raise ConversionError(tr("File no longer exists: {path}").format(path=s),
                                  tr("It was moved or deleted. Point to it again."))
    folder = os.path.dirname(destination) or "."
    if not os.access(folder, os.W_OK):
        raise ConversionError(tr("No write permission in {folder}.").format(folder=folder),
                              tr("Use ⚙ (outer ring of the wheel) and pick another output folder."))
    try:
        final = target.func(sources, destination, op, prog)
        if not os.path.exists(final) or (os.path.isfile(final) and os.path.getsize(final) == 0):
            raise ConversionError(tr("The tool finished without error but did not produce the file."),
                                  tr("Try ⚙ with other settings (e.g. a trim range or frame time within "
                                     "the file's duration)."))
        return final
    except (ConversionError, Cancelled):
        _cleanup(destination)
        raise
    except MemoryError:
        _cleanup(destination)
        raise ConversionError(tr("Not enough memory for this conversion."),
                              tr("Close heavy programs or lower the resolution in ⚙.")) from None
    except OSError as e:
        _cleanup(destination)
        if e.errno == 28:
            raise ConversionError(tr("Disk full."), tr("Free up space or pick another folder in ⚙."), str(e)) from e
        raise ConversionError(tr("File error: {error}").format(error=e.strerror or e),
                              tr("Check permissions and disk space."), repr(e)) from e
    except Exception as e:
        _cleanup(destination)
        raise ConversionError(tr("Unexpected failure: {error}").format(error=e),
                              tr("Try ⚙ with different settings, or another format. If it happens again, "
                                 "the details below show where it broke."), traceback.format_exc()) from e


def _cleanup(destination):
    try:
        if os.path.isfile(destination):
            os.remove(destination)  # partial file we produced ourselves in this conversion
    except OSError:
        pass
