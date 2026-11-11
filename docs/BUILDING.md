# Building and releasing PaperNym (Windows and Linux)

## One-time setup

```bat
cd /d F:\papernym
.venv\Scripts\activate
python -m pip install -e ".[gui,dev,build]"
winget install --id JRSoftware.InnoSetup -e --scope user
```

## Build locally

```bat
python scripts\build_windows.py
```

This runs PyInstaller, checks the result, then builds the installer if Inno Setup 6 is found.
Use `--no-installer` for the app folder only.

| Output | What it is |
|---|---|
| `dist\PaperNym\PaperNym.exe` | The tray app (accepts `--sandbox --show --debug`) |
| `dist\PaperNym\papernym-cli.exe` | The command line (the installer exposes it as `papernym`) |
| `dist\PaperNym\THIRD_PARTY_LICENSES.txt` | Licences of everything bundled |
| `dist\PaperNym-Setup-<version>.exe` | The installer |
| `dist\PaperNym-Setup-<version>.exe.sha256` | Its checksum |

Try the built app without touching your real settings:

```bat
dist\PaperNym\PaperNym.exe --sandbox --show --debug
```

For a built exe, the sandbox copies sample papers from `PAPERNYM_SAMPLES` or `.\sample_pdfs`.

PyInstaller runs with a clean `PATH` (this Python plus Windows). Without that, a `PATH` that
contains Anaconda or MSYS makes it bundle the wrong `icuuc.dll`, and Qt fails to start with
"DLL load failed while importing QtCore".

## What the installer does

- Installs for the current user only, into `%LOCALAPPDATA%\Programs\PaperNym`; no administrator rights.
- Adds a Start-menu shortcut, and a desktop shortcut if ticked.
- **Start PaperNym when I log in** (ticked by default): writes the `HKCU\...\Run` entry, plus
  a one-time marker the app reads on its next start, so the app's own setting matches.
- **The command line is always installed and registered** with the tray app (no checkbox):
  - `{app}\bin` goes on the user PATH. It holds `papernym.cmd`, a shim for
    `papernym-cli.exe`, so `papernym show` works in any *new* cmd or PowerShell window. The
    two exe names cannot differ only by case on Windows, hence the shim.
  - App Paths entries (`HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths`) for
    `PaperNym.exe` and `papernym-cli.exe`, so Windows finds both by name from Win+R, Start
    and `start papernym-cli`.
- The uninstaller stops the app and removes its files, the login entry, the PATH and App
  Paths entries and the shortcuts. It asks whether to remove settings, history and saved API keys (default No).
  PDFs are never touched.

## Release through GitHub

One tag push releases everything:

1. Bump `src/papernym/__init__.py` and add the version to `CHANGELOG.md`; commit and push.
2. Tag and push:

```bat
git tag -a v0.1.3 -m "PaperNym 0.1.3"
git push origin v0.1.3
```

Three workflows start from the tag:

- `windows-release.yml` builds the installer and attaches it to the GitHub Release.
- `linux-release.yml` builds the `.deb` and attaches it to the same release (see "Linux
  package" below).
- `pypi-release.yml` publishes the package to PyPI (see "Publishing to PyPI" below).

Whichever release workflow finishes first creates the GitHub Release; the other adds its
files to it.

Each checks that the tag equals `papernym.__version__` and runs the tests before it
publishes anything. A version number can be used only once on PyPI, so a failed release is
fixed with a new version, not by moving the tag.

`.github/workflows/windows-release.yml` in detail:

1. checks that the tag equals `papernym.__version__`;
2. runs the tests;
3. installs Inno Setup;
4. calls `scripts/build_windows.py --require-installer`;
5. uploads the installer as an artifact and attaches it, with its `.sha256`, to the GitHub Release.

You can also start it by hand from the Actions tab ("Run workflow"). With no tag, it only
builds the artifact.

Bump `src/papernym/__init__.py` before tagging. The app's update check reads the latest
release of `Xatta-Trone/papernym`.

## Linux package

`scripts/build_linux.py` builds the same one-folder app with PyInstaller (shared
`packaging/papernym.spec`), smoke-tests both programs, then packs a `.deb` with `dpkg-deb`:

| In the package | What it is |
|---|---|
| `/opt/papernym/` | The app folder (`PaperNym` tray app, `papernym-cli`, bundled Python and Qt) |
| `/usr/bin/papernym`, `/usr/bin/papernym-gui` | Links to the two programs |
| `/usr/share/applications/papernym.desktop` | App-menu entry |
| `/usr/share/icons/hicolor/*/apps/papernym.*` | Icons (SVG plus PNGs from 48 to 512 px) |

The package depends on the system libraries Qt's X11/Wayland plugins load (`libxcb-cursor0`,
`libegl1` and so on), so `apt install ./papernym_*.deb` pulls them in.

Build on Ubuntu 22.04 (the oldest supported release; newer glibc versions run older builds,
not the other way round):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[gui,dev,build]"
python scripts/build_linux.py --snapshot     # dist/papernym_<version>+git<date>.<sha>_amd64.deb
```

`--snapshot` marks test builds; release builds use `--expected-version vX.Y.Z` instead.
`.github/workflows/linux-release.yml` runs the tests, builds on `ubuntu-22.04`, installs the
`.deb`, runs both programs, removes it again, and then uploads the artifact (and attaches it
to the release for a tag). "Run workflow" without a tag gives a snapshot artifact to try.

## Code signing (not used for now)

Releases are unsigned. Users see SmartScreen's "Windows protected your PC" on the installer
and choose **More info > Run anyway**; the warning fades as a release gains downloads.
Microsoft Defender's behaviour detection can also flag a new unsigned exe that registers
itself at login: in the local trial, a copy installed under `%TEMP%` was blocked as
`Behavior:Win32/Persistence.A!ml`. If a release is flagged, report it as a false positive at
https://www.microsoft.com/wdsi/filesubmission.

To sign later: `scripts/build_windows.py` still signs both exes and the installer when
`SIGN_PFX` (a `.pfx`) and `SIGN_PASSWORD` are set and `signtool.exe` is available. The release
workflow does not pass a certificate. SignPath.io (free for open-source projects) and Azure
Trusted Signing are the low-cost routes.

## Publishing to PyPI

`.github/workflows/pypi-release.yml` runs the tests on Windows, builds the Python package
(sdist and wheel), runs `twine check --strict`, makes sure the sdist holds only `src/`,
`tests/` and the project files, installs the wheel in a clean environment and runs the CLI,
then uploads with **trusted publishing**: PyPI trusts this repository's workflow, so there
is no API token or password to store.

**On a `v*` tag push** it publishes to PyPI automatically, after checking that the tag
equals `papernym.__version__`. If the GitHub environment `pypi` has required reviewers, the
upload waits for your approval on the run page.

**By hand**, start it from **Actions → PyPI release → Run workflow** and pick a target:

| Target | Uploads to |
|---|---|
| `testpypi` (default) | https://test.pypi.org/project/papernym/ |
| `pypi` | https://pypi.org/project/papernym/ |
| `build-only` | nowhere; runs the checks only |

Each index accepts a version only once, so bump `src/papernym/__init__.py` before uploading
again.

### One-time setup (owner)

TestPyPI and PyPI are separate sites with separate accounts. For each one you use:

1. Create an account and turn on two-factor authentication:
   https://test.pypi.org/account/register/ (and https://pypi.org/account/register/).
2. Add a pending trusted publisher under **Account settings → Publishing**
   (https://test.pypi.org/manage/account/publishing/):

   | Field | Value |
   |---|---|
   | PyPI project name | `papernym` |
   | Owner | `Xatta-Trone` |
   | Repository name | `papernym` |
   | Workflow name | `pypi-release.yml` |
   | Environment name | `testpypi` (on PyPI: `pypi`) |

   The project is created on the first successful upload.
3. On GitHub, create the environments under **Settings → Environments**: `testpypi`, and
   later `pypi`. Adding yourself as a required reviewer on `pypi` makes every real upload
   wait for your approval.

### Try the TestPyPI upload

TestPyPI does not host most of PaperNym's dependencies, so take those from PyPI:

```bash
python -m venv try
try\Scripts\activate
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ "papernym[gui]"
papernym --version
papernym-gui --sandbox --show
```

### Build and check locally

```bash
uv build --out-dir dist/pypi
uvx twine check --strict dist/pypi/*
```
