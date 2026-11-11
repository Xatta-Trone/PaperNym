"""Build the Windows app: PyInstaller one-folder build, then the Inno Setup installer.

    python scripts/build_windows.py                 # exe + installer (installer if Inno Setup is found)
    python scripts/build_windows.py --no-installer  # exe only
    python scripts/build_windows.py --expected-version 0.2.0   # fail if __version__ differs (CI)

Output:
    dist/PaperNym/PaperNym.exe        windowed tray app (--sandbox --show --debug work)
    dist/PaperNym/papernym-cli.exe    console CLI
    dist/PaperNym-Setup-<version>.exe installer
    dist/PaperNym-Setup-<version>.exe.sha256

Optional signing: set SIGN_PFX (path to a .pfx) and SIGN_PASSWORD; signtool.exe must be on
PATH or in SIGNTOOL. Without them the build is unsigned (SmartScreen will warn).

GitHub Actions calls this same script; the workflow has no build logic of its own.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP_DIR = DIST / "PaperNym"
ISS = ROOT / "packaging" / "papernym.iss"

# Distributions bundled into the app (runtime dependencies and what they pull in).
BUNDLED = ["PySide6", "PySide6_Essentials", "shiboken6", "pypdfium2", "requests", "urllib3", "idna",
           "charset-normalizer", "certifi", "watchdog", "keyring", "jaraco.classes", "jaraco.context",
           "jaraco.functools", "more-itertools", "pywin32-ctypes", "importlib_metadata", "zipp",
           "backports.tarfile"]


def version() -> str:
    namespace: dict = {}
    exec((ROOT / "src" / "papernym" / "__init__.py").read_text(encoding="utf-8"), namespace)
    return namespace["__version__"]


def run(command: list[str], **kwargs) -> None:
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True, **kwargs)


def version_file(ver: str) -> Path:
    """Windows file properties (Details tab) for both executables."""
    parts = (ver.split(".") + ["0", "0", "0"])[:4]
    numbers = ", ".join(str(int(part)) for part in parts)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({numbers}), prodvers=({numbers}), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Xatta-Trone'),
      StringStruct('FileDescription', 'PaperNym - names research papers'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', 'PaperNym'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 Xatta-Trone. MIT License.'),
      StringStruct('OriginalFilename', 'PaperNym.exe'),
      StringStruct('ProductName', 'PaperNym'),
      StringStruct('ProductVersion', '{ver}')])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"""
    BUILD.mkdir(exist_ok=True)
    path = BUILD / "version_info.txt"
    path.write_text(text, encoding="utf-8")
    return path


def third_party_licenses(target: Path) -> None:
    """THIRD_PARTY_LICENSES.txt: name, version, licence and licence text of every bundled package."""
    lines = ["PaperNym bundles the following open-source software.",
             "PySide6 / Qt are used under the GNU LGPL v3; they are shipped as separate,",
             "replaceable DLLs in the _internal folder (one-folder build).",
             "Python itself is under the PSF License Agreement.", ""]
    for name in BUNDLED:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        meta = dist.metadata
        licence = meta.get("License-Expression") or meta.get("License") or ""
        if not licence or len(licence) > 80:
            classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
            licence = ", ".join(classifiers) or licence[:80] or "see the package"
        lines += ["=" * 78, f"{meta['Name']} {dist.version}", f"License: {licence}",
                  f"Home: {meta.get('Home-page') or meta.get('Project-URL', '')}", ""]
        for file in dist.files or []:
            if file.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")):
                try:
                    text = Path(dist.locate_file(file)).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                lines += [text.strip(), ""]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def clean_path() -> str:
    """PATH for PyInstaller: this Python and Windows only.

    PyInstaller resolves DLLs through PATH. A user PATH with Anaconda, MSYS or other Qt
    installs can make it bundle the wrong copy (for example Anaconda's icuuc.dll, which then
    shadows the one in System32 and stops Qt from loading).
    """
    system = os.environ.get("SystemRoot", r"C:\Windows")
    parts = [str(Path(sys.executable).parent), str(Path(sys.prefix) / "Scripts"), str(Path(sys.base_prefix)),
             os.path.join(system, "System32"), system, os.path.join(system, "System32", "Wbem")]
    return os.pathsep.join(dict.fromkeys(parts))


def find_iscc() -> Path | None:
    candidates = [os.environ.get("ISCC"), shutil.which("ISCC"), shutil.which("iscc")]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            candidates.append(os.path.join(base, "Inno Setup 6", "ISCC.exe"))
    return next((Path(c) for c in candidates if c and Path(c).is_file()), None)


def sign(paths: list[Path]) -> None:
    pfx, password = os.environ.get("SIGN_PFX"), os.environ.get("SIGN_PASSWORD")
    if not pfx:
        print("note: SIGN_PFX not set; the build is unsigned", flush=True)
        return
    tool = os.environ.get("SIGNTOOL") or shutil.which("signtool") or "signtool"
    for path in paths:
        run([tool, "sign", "/fd", "SHA256", "/tr", "http://timestamp.digicert.com", "/td", "SHA256",
             "/f", pfx, "/p", password or "", path])


def smoke_test() -> None:
    """The built CLI starts and reads settings from a temporary folder (never the real one)."""
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, PAPERNYM_HOME=home, PAPERNYM_KEYRING="off", NO_COLOR="1")
        out = subprocess.run([APP_DIR / "papernym-cli.exe", "show"], env=env, capture_output=True,
                             text=True, timeout=120)
        print(out.stdout.strip())
        if out.returncode != 0 or "PaperNym" not in out.stdout:
            raise SystemExit(f"smoke test failed: {out.returncode}\n{out.stderr}")
        out = subprocess.run([APP_DIR / "papernym-cli.exe", "--version"], env=env, capture_output=True,
                             text=True, timeout=60)
        print(out.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-installer", action="store_true", help="build the exe folder only")
    parser.add_argument("--require-installer", action="store_true",
                        help="fail if Inno Setup is missing (used by CI)")
    parser.add_argument("--expected-version", help="fail unless the package version equals this")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("build_windows.py runs on Windows only")
    ver = version()
    if args.expected_version and args.expected_version.lstrip("v") != ver:
        raise SystemExit(f"version mismatch: tag {args.expected_version}, package {ver}")
    print(f"Building PaperNym {ver}", flush=True)

    shutil.rmtree(APP_DIR, ignore_errors=True)
    env = dict(os.environ, PAPERNYM_VERSION_FILE=str(version_file(ver)), PATH=clean_path())
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", DIST,
         "--workpath", BUILD / "pyinstaller", ROOT / "packaging" / "papernym.spec"], env=env, cwd=ROOT)
    for name in ("PaperNym.exe", "papernym-cli.exe"):
        if not (APP_DIR / name).is_file():
            raise SystemExit(f"missing {APP_DIR / name}")
    shutil.copy2(ROOT / "LICENSE", APP_DIR / "LICENSE.txt")
    third_party_licenses(APP_DIR / "THIRD_PARTY_LICENSES.txt")
    smoke_test()
    sign([APP_DIR / "PaperNym.exe", APP_DIR / "papernym-cli.exe"])
    print(f"App folder: {APP_DIR}")

    if args.no_installer:
        return 0
    iscc = find_iscc()
    if iscc is None:
        message = "Inno Setup 6 (ISCC.exe) not found; skipped the installer"
        if args.require_installer:
            raise SystemExit(message)
        print("note: " + message)
        return 0
    run([iscc, f"/DAppVersion={ver}", f"/DSourceDir={APP_DIR}", f"/DOutputDir={DIST}",
         f"/DRootDir={ROOT}", ISS])
    installer = DIST / f"PaperNym-Setup-{ver}.exe"
    sign([installer])
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    (DIST / f"{installer.name}.sha256").write_text(f"{digest}  {installer.name}\n", encoding="ascii")
    print(f"Installer: {installer}\nSHA256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
