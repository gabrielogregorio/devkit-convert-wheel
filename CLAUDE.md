# CLAUDE.md - Convert Wheel

Rules and context for any agent that touches this project. Read all of it before editing.
Python + system GTK3, no pip. Code, comments and docs are in English; the UI is English or
Brazilian Portuguese depending on the system language (`i18n.py`).

## What it is

Hold the wheel click of the mouse (default: button 2; the side buttons 8/9 also work) over a
file in Nautilus or on the desktop, and a GTA V style weapon wheel shows the possible formats.
Release on the inner ring = convert right away, same name, new extension, `name (1).ext` if it
already exists. Release on the outer ring (⚙) = settings dialog for that format. Release in the
center or more than `Wheel.OUTSIDE` (24 px) past the edge = cancel, nothing is marked. Quick tap =
the wheel stays open, pick with the left click, right click cancels. Every conversion opens a
popup in the top right corner: loading (bar) → success (closes at once, no buttons) or error +
"How to fix" + details.

Be direct with the user. The target is Ubuntu, **not Windows**.

## Target environment (checked on 2026-10-25)

- Ubuntu 24.04, GNOME, **X11**, DING extension (desktop icons, window class `Gjs`, title
  `Desktop Icons N`). Tested with two stacked monitors (1920x2160 root).
- Available: ffmpeg 6.1 (x264, vpx, aom, svtav1, opus, vorbis, lame), soffice, gs, pdftotext,
  PIL (webp yes, avif no), PyMuPDF (`fitz`), `markdown`, `yaml`, fontTools + brotli,
  libX11/libXtst/libXi, GdkPixbuf SVG/HEIF/WebP loaders.
- Not available: python3-gi-cairo, xdotool, xclip, ImageMagick, pandoc, python-xlib.

## Project rules

1. **No new dependency.** Need a package? Write the `sudo apt install` line and hand it over.
2. **No cairo** (`draw` breaks without python3-gi-cairo). The wheel is SVG → `GdkPixbuf.PixbufLoader`.
3. **Never leave the pointer frozen.** The button grab is `GrabModeSync`: every passive
   ButtonPress needs `XAllowEvents` (Replay outside the file manager, Async inside it).
   The wheel has a 45 s timeout and releases the grab on any exception.
4. **Outside Nautilus/DING the click is handed back** (`ReplayPointer`): the browser's "back"
   keeps working. Do not replace this with a plain async grab.
5. **Never overwrite a user file.** Output always goes through `free_path` (numbering).
   The only `os.remove` deletes the partial file the conversion itself created when it fails.
6. A failure becomes `ConversionError(reason, hint, details)`. Every new known failure gets a
   rule in `process_error` with a concrete hint.
7. **Every user-facing string is English inside `tr()`** with its pt-BR line in `i18n.PT_BR`.
   Petal `label`/`sub` use `tr_noop()`: they stay English in `Target` because `Target.key`
   names the remembered settings, and are translated when drawn. `./check.sh` fails on a
   missing entry or different `{placeholders}`. Logs are English and not translated.
8. Trash goes to `./trash/` (ignored by git), no `rm`.

## Architecture

| File / part | What it does |
|---|---|
| `converters.py` | engine without GTK: `Target`, `Option`, `targets_for(path)`, `convert()`, `ConversionError`, `Progress` (reads ffmpeg `-progress`, cancels with `killpg`) |
| families | image (PIL; AVIF through ffmpeg/libaom; HEIC read by GdkPixbuf), svg (fitz), audio/video (ffmpeg), pdf (fitz + gs to compress), text/md/html (markdown + fitz.Story for PDF), office (soffice with its own temporary profile), data json/yaml/csv/tsv/toml, subtitles srt/vtt/ass, fonts ttf/otf/woff/woff2, archives zip/tar.* and folder → archive |
| `i18n.py` | `LANG` from `CONVERT_WHEEL_LANG`/`LANGUAGE`/`LC_ALL`/`LC_MESSAGES`/`LANG`; `tr`, `tr_noop`, `decimal`, `PT_BR` |
| `convert_wheel.py` `X11` | libX11 through ctypes: `XGrabButton` on root, `XGrabPointer` while the wheel is open, `XQueryTree`+`XGetClassHint` to identify the window, XTest for the click/Ctrl+C |
| `Capture` | caches the clipboard text, sets a sentinel, fake Ctrl+C, reads `x-special/gnome-copied-files` (or text), restores the old text |
| `Wheel` | RGBA POPUP window; `zone(x, y)` → (index, `conv`/`cfg`); idle, re-renders only on change; animating, redraws at ~60 fps (frame ~10 ms) |
| extras | `Target(extra=True)` leaves the main wheel for a 2nd wheel behind the `+ MORE` petal (family `menu`, func `None`, ext `more`/`back`); release/click on it or rest 0.45 s on it to swap; `← BACK` returns |
| `TaskPopup` | one per conversion, stacked in the top right corner of the primary monitor |
| `AdjustDialog` | fields generated from the target `Option`s + name + folder + "remember settings" |
| `SettingsDialog` | button (with click detection), wheel size, fixed output folder |

Config: `~/.config/devkit-convert-wheel/config.json` (merged over `DEFAULTS`). Log:
`~/.cache/devkit-convert-wheel/convert-wheel.log`. Tray icons: `~/.cache/devkit-convert-wheel/icons/`.

## How to test after a change

1. `./check.sh`: lint (ruff + shellcheck, skipped if missing), unit (`tests/unit`), e2e
   (`tests/e2e`: ~40 conversions on tiny samples in `tmp/check/`, wheel render, frame < 16 ms) and
   smoke (`tools/smoke.sh`: the real app in Xvfb + its own D-Bus + throwaway `HOME`). It must end
   with `OK`. One step only: `./check.sh unit|e2e|lint|smoke`; `--office` adds LibreOffice.
   Run with `CONVERT_WHEEL_LANG=en` too when UI strings change. Tests are stdlib `unittest`
   on `/usr/bin/python3` (the app needs the apt `gi`), never pytest/pip.
2. **Never start the app against the real desktop from a test**: a second process forwards its
   command line to the running instance and grabs the user's mouse. The smoke test only runs
   inside `tools/smoke.sh`.
3. Restart the real one: `tools/restart.sh` (own script, log in `tmp/app.log`; **do not** put
   `pgrep -f convert_wheel` inside a `bash -c`: it matches and kills its own shell, exit 144).
4. Screenshots: `python3 tools/screenshots.py` (after `./check.sh e2e`, which creates the samples).
5. The real trigger (physical button + Nautilus) **cannot** be tested by script: fake XTest
   events would click on the screen the user is working on. Ask the user to test it.

## CI/CD and releases

- `.github/workflows/`: `tests.yml` (unit + e2e in en and pt-BR, smoke), `check-quality.yml`
  (lint), `codeql-analysis.yml`, `auto-complete-fields.yml` (PR assign/labels/changelog/title,
  fails if `VERSION` is already tagged), `create-tag-and-release.yml` (merged PR → tag `v$VERSION`
  + release with tarball and SHA256SUMS). Shared apt setup in `.github/actions/setup-environment`.
- Release = bump `VERSION` in the PR and merge. No manual tags.
- PR text reaches the release through `env:` and a file, never `${{ }}` inside `run:` (script
  injection). Keep it that way.

## Known pitfalls

- `Progress.run` closes ffmpeg's `stdout`/`stderr` at the end: without it every conversion left
  2 open descriptors in the wheel, which stays on all day. Same for images: `conv_image` and
  `conv_image_ffmpeg` open the source in a `with` block (an animated GIF kept its file open).
- Scope decided on 2026-10-27: **only the wheel**. No Nautilus right-click menu and no joining
  several files into one (it was built and cancelled).
- **Fake Ctrl+C ONLY with focus on the file manager** (`X11.focused()` + `is_file_manager`), and
  only once. On 2026-10-25 an old version sent Ctrl+C to the focused window without checking
  (and a 2nd time at 350 ms): it landed on a terminal and **closed the user's running session**.
  Never loosen this.
- **Focus before Ctrl+C:** on the desktop (DING) the fake click sometimes does not take the focus
  (it stays on the terminal). `X11.focus(window)` does `XSetInputFocus` on the client found by
  `client_info()`.
- **Short animation** (open 0.15 s, pick 0.2 s, close 0.1 s): the user found 0.4 s too slow.
- **Never move the cursor.** The wheel opens centered on the mouse even near the edge (it gets
  cut off). The version that pushed the wheel to fit the monitor made the cursor jump (two
  stacked monitors: the seam is also an edge). There is no warp helper on purpose.
- **Xlib's internal queue freezes the mouse.** The passive grab is synchronous: until
  `XAllowEvents`, the pointer of the whole PC stands still. A call with a reply (XQueryPointer,
  XSync) can pull the ButtonPress into Xlib's queue without waking the `io_add_watch` fd; hence the
  20 ms drain (`GLib.timeout_add(20, self._read)`). That was the cause of "I press and it takes a
  while to react". Do not remove it.
- **Animation** (`Wheel._petal`/`_hub`): open = petals bloom in sequence while turning
  (ease-out-back); pick = the others turn to the chosen one along the shortest way and fade, it
  pulses; close = shrinks. The mouse grab is released at once: the animation never holds the
  pointer. Keep the frame < 16 ms (`check.sh` measures it and saves `animation.png`).
- **No notifications.** A toplevel that opens without focus makes GNOME show "is ready". That is
  why `TaskPopup` is a POPUP (override-redirect) and the dialogs open through `present()` (focus
  with the X server time). Do not turn the progress popup back into a TOPLEVEL.
- **Open fast.** The wheel only appears once the format is known (fallback "reading…" at
  300 ms). The capture does not wait for timers: the old text is cached through `owner-change`,
  Ctrl+C goes out 40 ms after the click and the answer arrives through the signal. The log records
  the time of each capture.
- PDF → "1 image" stitches the pages; above 150 MP or the format's max side (JPEG 65500) the DPI
  drops on its own so the PC does not go down.
- The fake Ctrl+C replaces the clipboard; only the previous **text** is restored.
- If another program already grabs the button (input-remapper, Solaar), `XGrabButton` gives
  BadAccess: the app warns and suggests another button.
- Wayland: none of this works (global grab and XTest are X11). It would need evdev/a portal.
- HiDPI scale ≠ 1 was not tested.

## Ideas not done (only if the user asks)

- Batch: hold with several files selected without losing the selection (today the fake click
  selects only the one under the cursor; batch works through the Nautilus script, one popup per
  file).
- OCR for scanned PDFs (the hint already points to `ocrmypdf`).
- Remove image background, upscale.

## Tray icon and on/off

- Own icon on the bar: 6-slice wheel with an arrow (SVG generated in
  `~/.cache/devkit-convert-wheel/icons/`), colored = enabled, gray = paused.
- **No "Quit" item**: the icon always stays on the bar; turning off = unchecking "Enabled"
  (`cfg["paused"]`). Autostart runs with `--off` (comes up paused).
