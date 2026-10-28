<div align="center">

# Convert Wheel

**Hold the mouse wheel button over a file and pick the output format on a weapon-wheel style menu.**

![Python](https://img.shields.io/badge/Python-3.12-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![GTK](https://img.shields.io/badge/GTK-3-4A86CF?style=for-the-badge&logo=gtk&logoColor=white)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04-E95420?style=for-the-badge&logo=ubuntu&logoColor=white)
![GNOME](https://img.shields.io/badge/GNOME-X11-4A86CF?style=for-the-badge&logo=gnome&logoColor=white)
![FFmpeg](https://img.shields.io/badge/FFmpeg-007808?style=for-the-badge&logo=ffmpeg&logoColor=white)
![LibreOffice](https://img.shields.io/badge/LibreOffice-18A303?style=for-the-badge&logo=libreoffice&logoColor=white)
![Offline](https://img.shields.io/badge/100%25-local%20%26%20offline-555555?style=for-the-badge)
![Languages](https://img.shields.io/badge/UI-en%20%7C%20pt--BR-555555?style=for-the-badge)
![License](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)

</div>

## About

Hold the **mouse wheel click** (middle button) over a file in Nautilus or on the desktop.
A wheel with the formats that file can become shows up around the cursor.

| Where you release | What happens |
|---|---|
| Inner ring (the format) | converts right away, same name, same folder; if the name is taken it becomes `name (1).ext` |
| Outer ring (⚙) | opens the format settings (quality, resolution, trim, pages, name, folder) |
| Center, or far from the wheel | cancels, nothing is marked; a click outside just closes it |

- **Quick tap** on the button keeps the wheel open: left click picks, right click cancels.
- The golden **+ MORE** petal opens a second wheel with extra formats: release/click on it or rest the
  mouse on it. **← BACK** returns.
- Every conversion shows a popup in the top right corner with a progress bar. It disappears when the
  conversion ends. On error it stays open with the cause, **How to fix**, technical details,
  **Copy error** and **Adjust and retry**.
- **Language:** the interface follows the system language. A `pt*` locale shows Brazilian Portuguese,
  anything else shows English. Force one with `CONVERT_WHEEL_LANG=en` or `CONVERT_WHEEL_LANG=pt_BR`.

## Set up on a new PC

Built and tested on Ubuntu 24.04 + GNOME + Nautilus. It uses the system Python, no pip.

1. **X11 session** (Xorg). On Ubuntu 24.04: login screen → gear in the corner → "Ubuntu on Xorg".
   On Wayland the window does not stay on top and the mouse is not captured.
2. **Packages** (the core and the converters):
   ```bash
   sudo apt install python3 python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 \
                    libx11-6 libxtst6 libxi6 file \
                    ffmpeg ghostscript poppler-utils libreoffice \
                    python3-pil python3-fitz python3-markdown python3-yaml python3-fonttools python3-brotli \
                    heif-gdk-pixbuf librsvg2-common webp-pixbuf-loader
   ```
   A tool is missing? Only its formats disappear from the wheel (e.g. without `libreoffice`, no Office).
3. **Clone and install:**
   ```bash
   git clone <repo-url> devkit-convert-wheel
   cd devkit-convert-wheel
   ./install.sh     # app menu entry + start at login (comes up off) + Nautilus > Scripts
   ./check.sh       # must end with OK (./check.sh --office also tests LibreOffice)
   ```
4. **Turn it on:** wheel icon on the top bar → **Enabled**. Then hold the **middle button** over a
   file in Nautilus or on the desktop. To use another button: icon → Settings…

**Outside the repository:**

| Path | What |
|---|---|
| `~/.config/convert-wheel/config.json` | button, wheel size, output folder, remembered settings |
| `~/.cache/convert-wheel/` | log (`convert-wheel.log`) and tray icons |
| `~/.local/share/applications/convert-wheel.desktop` | app menu entry |
| `~/.config/autostart/convert-wheel.desktop` | start at login, with `--off` |
| `~/.local/share/nautilus/scripts/Convert (wheel)` | Nautilus script (`Converter (roda)` on a pt-BR system) |

Moved the folder? Run `./install.sh` again.

## Available scripts

```bash
# Run
./convert_wheel.py                 # turns the wheel on (icon on the top bar)
./convert_wheel.py --off           # icon only, as at login
./convert_wheel.py photo.webp      # opens the wheel for that file
./convert_wheel.py --config        # settings window
tools/restart.sh                   # restarts in the background (log in tmp/app.log)

# Install / remove
./install.sh
./install.sh --no-autostart
./install.sh --remove              # moves the entries to trash/, keeps the config

# Test (no window: renders the wheel and converts tiny samples)
./check.sh
./check.sh --office                # adds conversions through LibreOffice
python3 tools/screenshots.py       # screenshots of the task popup and the settings dialog
CONVERT_WHEEL_LANG=en ./check.sh   # same check with the English interface
```

## What it converts

| Input | Outputs |
|---|---|
| **Image** (png jpg webp avif gif bmp tiff ico heic…) | png, jpg, webp, gif, ico, pdf; extras: avif, bmp, tiff; same format = compress; animated gif/webp → mp4/webm |
| **SVG** | png, jpg, webp, ico, pdf |
| **Audio** | mp3, wav, ogg, flac, m4a, opus (bitrate, sample rate, mono, trim, volume, normalize) |
| **Video** | mp4, mkv, webm, mov, avi, gif, jpg (1 frame), mp3/wav/m4a (audio only); mp4 → compressed mp4 |
| **PDF** | png/jpg per page or all in one image ("1 image"), txt, md, docx, compressed PDF; extras: webp (pages or 1 image), svg (vector), multipage tiff, bmp, html |
| **Text** | txt ↔ md ↔ html, plus pdf, docx, odt |
| **Office** | docx/odt/rtf, xlsx/ods/csv, pptx/odp → pdf and between each other (LibreOffice) |
| **Data** | json ↔ yaml ↔ csv ↔ tsv, toml → json, plus xlsx/ods |
| **Subtitles** | srt ↔ vtt ↔ ass |
| **Fonts** | ttf/otf ↔ woff/woff2 |
| **Archive / folder** | zip ↔ tar.gz/tar.xz/tar.bz2; folder → zip/tar |

## Usage

Top bar icon (colored = enabled, gray = off): **Enabled**, Convert file…, Settings… (pick the
button), Open log. There is no "Quit": the icon always stays on the bar and at login the wheel comes
up off. Outside the wheel: Nautilus → right click → Scripts → Convert (wheel).

## Project layout

| File | Role |
|---|---|
| `convert_wheel.py` | the app: X11 button grab, clipboard capture, the wheel (SVG), popups, tray |
| `converters.py` | conversion engine without GTK: targets per file type, `convert()`, friendly errors |
| `i18n.py` | language detection and the pt-BR catalog (English is the source text) |
| `install.sh` | menu entry, autostart and Nautilus script |
| `check.sh` | headless check: compile, translations, wheel render, ~40 sample conversions |
| `tools/` | `restart.sh` and `screenshots.py` |

Adding a user-facing string: write it in English inside `tr("…")` (or `tr_noop("…")` for petal
labels) and add the pt-BR line to `PT_BR` in `i18n.py`. `./check.sh` fails if it is missing.

## Limitations

- X11 only: the global button grab and XTest do not exist on Wayland.
- The fake Ctrl+C replaces the clipboard for a moment; only **text** that was there before is restored.
- If another program already grabs the button (input-remapper, Solaar), the app warns you and
  suggests another button.
- HiDPI scale other than 1 was not tested.

## License

[MIT](LICENSE). Use, copy, modify and distribute freely; the software is provided "as is", without
warranty of any kind.
