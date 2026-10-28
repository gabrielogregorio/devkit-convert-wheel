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

[![Tests](https://github.com/gabrielogregorio/devkit-convert-wheel/actions/workflows/tests.yml/badge.svg)](https://github.com/gabrielogregorio/devkit-convert-wheel/actions/workflows/tests.yml)
[![Lint](https://github.com/gabrielogregorio/devkit-convert-wheel/actions/workflows/check-quality.yml/badge.svg)](https://github.com/gabrielogregorio/devkit-convert-wheel/actions/workflows/check-quality.yml)
[![CodeQL](https://github.com/gabrielogregorio/devkit-convert-wheel/actions/workflows/codeql-analysis.yml/badge.svg)](https://github.com/gabrielogregorio/devkit-convert-wheel/actions/workflows/codeql-analysis.yml)
[![Release](https://img.shields.io/github/v/release/gabrielogregorio/devkit-convert-wheel)](https://github.com/gabrielogregorio/devkit-convert-wheel/releases)

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
| `~/.config/devkit-convert-wheel/config.json` | button, wheel size, output folder, remembered settings |
| `~/.cache/devkit-convert-wheel/` | log (`convert-wheel.log`) and tray icons |
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

# Test (never touches the running desktop)
./check.sh                         # lint + unit + e2e + smoke, ends with OK
./check.sh unit                    # or: lint | e2e | smoke
./check.sh e2e --office            # e2e also converts through LibreOffice
CONVERT_WHEEL_LANG=en ./check.sh   # same checks with the English interface
python3 tools/screenshots.py       # screenshots of the task popup and the settings dialog
./convert_wheel.py --version
```

## Tests

| Kind | Where | What it covers |
|---|---|---|
| **Lint** | `ruff.toml`, ShellCheck | Python style, import order, bug patterns; warnings in every `.sh` |
| **Unit** | `tests/unit/` | language detection and the pt-BR catalog, file names and numbering, time and page parsing, error rules, targets per file type (unique settings keys, valid defaults), wheel zones and SVG, clipboard paths |
| **E2E** | `tests/e2e/test_conversions.py`, `test_render.py` | ~40 real conversions on tiny samples, numbering, friendly error on a fake file, wheel render through GdkPixbuf and frame time (< 16 ms) |
| **Smoke** | `tests/e2e/test_app.py` via `tools/smoke.sh` | starts the real app in Xvfb with its own D-Bus session and a throwaway `HOME`: comes up off, writes config and tray icons, a 2nd launch hands over to the 1st |

Tests use only the standard library (`unittest`) and the apt packages above. Lint needs `ruff` and
`shellcheck` (`pipx install ruff`, `sudo apt install shellcheck`); the smoke test needs
`sudo apt install xvfb dbus`. `./check.sh` skips what is not installed and says so.
The real trigger (holding the button over a file in Nautilus) is not automated on purpose: fake
input would click on the screen you are using.

## CI/CD

GitHub Actions, in `.github/`:

| Workflow | When | What |
|---|---|---|
| `tests.yml` | push/PR to `main`, manual | unit in English **and** pt-BR, e2e in English, smoke test in Xvfb, wheel renders as artifacts; manual run can add LibreOffice |
| `check-quality.yml` | push/PR to `main` | ruff, ShellCheck, `.sh` files executable in git, actions pinned to a hash, workflow YAML |
| `codeql-analysis.yml` | push/PR, weekly | CodeQL for Python and for the workflows |
| `auto-complete-fields.yml` | PR opened/updated | assigns the author, labels by commit words and touched files, lists the commits in the PR body (`[...autoGenerate]`), titles it `Release vX.Y.Z - …`, fails if that version was already released |
| `create-tag-and-release.yml` | PR merged into `main` | creates the tag `vX.Y.Z` from `VERSION` and a GitHub release with the PR text, generated notes, the source tarball and `SHA256SUMS` (a `-rc.1` style version becomes a pre-release) |

`setup-environment` (composite action) installs the system Python + GTK3 stack from apt, plus the
converters or Xvfb when a job needs them.

**Pinned versions.** Every third-party action is pinned to the full commit hash of its release tag,
with the version as a comment, so a moved or hijacked tag cannot change what runs:

| Action | Version | Commit |
|---|---|---|
| `actions/checkout` | v6.1.0 | `d23441a48e516b6c34aea4fa41551a30e30af803` |
| `actions/upload-artifact` | v6.0.0 | `b7c566a772e6b6bfb58ed0dc250532a479d7789f` |
| `actions/github-script` | v8.0.0 | `ed597411d8f924073f98dfc5c65a23a2325f34cd` |
| `github/codeql-action` (init, analyze) | v4.39.1 | `9b3254085494b55a0f7c4c2b3d2d52cc712ce370` |

The rest is pinned too: runners on `ubuntu-24.04` (not `ubuntu-latest`) and `ruff==0.17.3`.
`check-quality.yml` fails if a `uses:` is not a 40-character hash (local `./` actions excepted).
Dependabot opens a monthly PR that bumps the hash and the comment together. To pin one by hand:

```bash
git ls-remote --tags https://github.com/actions/checkout.git 'v6.1.0^{}' 'v6.1.0'   # the ^{} line is the commit
```

### Releasing

1. In the PR, bump `VERSION` (semver: `1.1.0`, or `1.1.0-rc.1` for a pre-release).
2. Merge into `main`. The tag and the release are created on their own.

What the release is built from:

| Part | Source |
|---|---|
| Tag | `v` + `VERSION` at the merge commit, pointing at that commit |
| Title | `Convert Wheel vX.Y.Z` |
| Notes | the PR title (without the `Release vX.Y.Z - ` prefix), then the PR body with the commit list that `auto-complete-fields.yml` filled in (the `[...autoGenerate]` marker is removed), then GitHub's generated notes (merged PRs, contributors, "Full Changelog" link to the previous tag) |
| Files | `devkit-convert-wheel-X.Y.Z.tar.gz` (`git archive` of the merge commit: only tracked files) and `SHA256SUMS` |
| Type | a version with `-` (e.g. `1.1.0-rc.1`) is a pre-release; any other becomes "latest" |

If the tag already exists (the PR did not bump `VERSION`), nothing is released and the run leaves a
warning. The PR check `VERSION is new` catches that before the merge.

Issues use forms (`bug_report.yml`, `feature_request.yml`); PRs start from `pull_request_template.md`.

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
| `check.sh` | runs lint, unit, e2e and smoke, the same steps as the CI |
| `tests/` | `unit/` and `e2e/` (`unittest`, no pip) |
| `tools/` | `restart.sh`, `smoke.sh`, `screenshots.py` |
| `VERSION` | current version; the release workflow tags from it |
| `.github/` | workflows, setup action, issue forms, PR template, Dependabot |

Adding a user-facing string: write it in English inside `tr("…")` (or `tr_noop("…")` for petal
labels) and add the pt-BR line to `PT_BR` in `i18n.py`. The unit tests fail if it is missing,
if the `{placeholders}` differ or if a pt-BR line is no longer used.

## Limitations

- X11 only: the global button grab and XTest do not exist on Wayland.
- The fake Ctrl+C replaces the clipboard for a moment; only **text** that was there before is restored.
- If another program already grabs the button (input-remapper, Solaar), the app warns you and
  suggests another button.
- HiDPI scale other than 1 was not tested.

## License

[MIT](LICENSE). Use, copy, modify and distribute freely; the software is provided "as is", without
warranty of any kind.
