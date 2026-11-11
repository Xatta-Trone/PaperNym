# Building and releasing PaperNym for Windows

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

```bat
git tag v0.1.0
git push origin v0.1.0
```

`.github/workflows/windows-release.yml` then:

1. checks that the tag equals `papernym.__version__`;
2. runs the tests;
3. installs Inno Setup;
4. calls `scripts/build_windows.py --require-installer`;
5. uploads the installer as an artifact and attaches it, with its `.sha256`, to the GitHub Release.

You can also start it by hand from the Actions tab ("Run workflow"). With no tag, it only
builds the artifact.

Bump `src/papernym/__init__.py` before tagging. The app's update check reads the latest
release of `Xatta-Trone/papernym`.

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
