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
- **Add the "papernym" command to PATH** (ticked by default): adds `{app}\bin`, which holds
  `papernym.cmd`, a shim for `papernym-cli.exe`. The two exe names cannot differ only by
  case on Windows, hence the shim.
- The uninstaller stops the app and removes its files, the login entry, the PATH entry and
  the shortcuts. It asks whether to remove settings, history and saved API keys (default No).
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

## Code signing (recommended before public release)

Unsigned builds trigger SmartScreen ("Windows protected your PC"). They can also trip
Microsoft Defender's behaviour detection: in the local trial, an unsigned `PaperNym.exe`
installed under `%TEMP%` that registered itself to start at login was blocked as
`Behavior:Win32/Persistence.A!ml`.

The build signs automatically when a certificate is provided:

- **Locally:** set `SIGN_PFX` (path to a `.pfx`) and `SIGN_PASSWORD`; `signtool.exe` comes from the Windows SDK.
- **In GitHub:** add the repository secrets `SIGN_PFX_BASE64` (the `.pfx`, base64-encoded) and `SIGN_PASSWORD`.

Low-cost options are Azure Trusted Signing, or SignPath.io, which is free for open-source
projects. You can also report a false positive to Microsoft at
https://www.microsoft.com/wdsi/filesubmission.
