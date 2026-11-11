"""Build the Linux app: PyInstaller one-folder build, then a .deb package for Ubuntu/Debian.

    python scripts/build_linux.py                          # app folder + .deb
    python scripts/build_linux.py --no-deb                 # app folder only
    python scripts/build_linux.py --snapshot               # version 0.1.3+git<date>.<sha> (test builds)
    python scripts/build_linux.py --expected-version v0.2.0   # fail if __version__ differs (CI)

Output:
    dist/PaperNym/PaperNym                      windowed tray app (--sandbox --show --debug work)
    dist/PaperNym/papernym-cli                  command line
    dist/papernym_<version>_amd64.deb           package: /opt/papernym, /usr/bin/papernym(-gui),
                                                app-menu entry and icons
    dist/papernym_<version>_amd64.deb.sha256

Build on the oldest Ubuntu you want to support (CI uses 22.04): the bundled Python and Qt need
that glibc or newer. Install with: sudo apt install ./dist/papernym_<version>_amd64.deb

GitHub Actions calls this same script; the workflow has no build logic of its own.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_windows import BUILD, BUNDLED, DIST, ROOT, run, third_party_licenses, version  # noqa: E402

APP_DIR = DIST / "PaperNym"
PACKAGE = "papernym"
INSTALL_DIR = Path("/opt/papernym")
LINUX_BUNDLED = [name for name in BUNDLED if name != "pywin32-ctypes"] + [
    "SecretStorage", "jeepney", "cryptography", "cffi", "pycparser"]

# Shared libraries Qt's xcb (X11) platform plugin loads from the system, plus EGL/GL and
# D-Bus. apt installs them with the package; most desktops already have them.
DEPENDS = ["libc6 (>= 2.35)", "libegl1", "libgl1", "libfontconfig1", "libfreetype6", "libdbus-1-3",
           "libxkbcommon0", "libxkbcommon-x11-0", "libxcb-cursor0", "libxcb-icccm4", "libxcb-image0",
           "libxcb-keysyms1", "libxcb-randr0", "libxcb-render-util0", "libxcb-shape0", "libxcb-xfixes0",
           "libxcb-xinerama0", "libxcb-xkb1", "libx11-xcb1", "libwayland-client0", "libwayland-cursor0",
           "libwayland-egl1"]

DESKTOP = """[Desktop Entry]
Type=Application
Name=PaperNym
GenericName=Paper renamer
Comment=Rename research paper PDFs from their publication metadata
Exec=papernym-gui --show
Icon=papernym
Terminal=false
Categories=Office;Education;Utility;
Keywords=pdf;paper;rename;doi;arxiv;research;
StartupWMClass=PaperNym
"""


def git_snapshot() -> str:
    """+git<date>.<sha>: sorts after the release it builds on and before the next one."""
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                         text=True).stdout.strip() or "unknown"
    return f"+git{dt.date.today():%Y%m%d}.{sha}"


def smoke_test() -> None:
    """Both programs start from the built folder, with a temporary settings folder."""
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, PAPERNYM_HOME=home, PAPERNYM_KEYRING="off", NO_COLOR="1")
        out = subprocess.run([APP_DIR / "papernym-cli", "show"], env=env, capture_output=True,
                             text=True, timeout=120)
        print(out.stdout.strip())
        if out.returncode != 0 or "PaperNym" not in out.stdout:
            raise SystemExit(f"CLI smoke test failed: {out.returncode}\n{out.stderr}")
        # The tray app must load Qt and keep running; it is stopped after a few seconds.
        gui_env = dict(env, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
        try:
            gui = subprocess.run([APP_DIR / "PaperNym", "--sandbox"], env=gui_env, capture_output=True,
                                 text=True, timeout=10)
        except subprocess.TimeoutExpired:
            print("GUI smoke test: still running after 10 s (good)")
            return
        raise SystemExit(f"GUI smoke test failed: exited with {gui.returncode}\n{gui.stderr[-3000:]}")


def icons(root: Path) -> None:
    """hicolor icons: the SVG plus PNGs scaled from the 1024 px icon (with Qt, already bundled)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    source = QImage(str(ROOT / "src" / "papernym" / "gui" / "icons" / "papernym.png"))
    if source.isNull():
        raise SystemExit("cannot read the app icon")
    for size in (48, 64, 128, 256, 512):
        target = root / f"usr/share/icons/hicolor/{size}x{size}/apps/{PACKAGE}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(target))
    scalable = root / f"usr/share/icons/hicolor/scalable/apps/{PACKAGE}.svg"
    scalable.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "assets" / "papernym-icon.svg", scalable)


def folder_size_kb(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink()) // 1024 + 1


def build_deb(deb_version: str) -> Path:
    root = BUILD / "deb"
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(APP_DIR, root / INSTALL_DIR.relative_to("/"), symlinks=True)
    bin_dir = root / "usr/bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "papernym").symlink_to(INSTALL_DIR / "papernym-cli")
    (bin_dir / "papernym-gui").symlink_to(INSTALL_DIR / "PaperNym")
    apps = root / "usr/share/applications"
    apps.mkdir(parents=True)
    (apps / f"{PACKAGE}.desktop").write_text(DESKTOP, encoding="utf-8")
    icons(root)
    doc = root / f"usr/share/doc/{PACKAGE}"
    doc.mkdir(parents=True)
    shutil.copy2(ROOT / "LICENSE", doc / "copyright")

    control = root / "DEBIAN"
    control.mkdir()
    (control / "control").write_text("\n".join([
        f"Package: {PACKAGE}",
        f"Version: {deb_version}",
        "Section: utils",
        "Priority: optional",
        "Architecture: amd64",
        "Maintainer: PaperNym maintainers <papernym@users.noreply.github.com>",
        f"Installed-Size: {folder_size_kb(root)}",
        "Depends: " + ", ".join(DEPENDS),
        "Recommends: gnome-shell-extension-appindicator | plasma-workspace",
        "Homepage: https://github.com/Xatta-Trone/papernym",
        "Description: rename research paper PDFs from their publication metadata",
        " PaperNym watches your folders (such as Downloads) and renames academic PDFs from",
        " their DOI or arXiv metadata, for example 2025_Smith_Deep_learning_for_....pdf.",
        " It verifies every match against the PDF's own text, can undo any rename, and",
        " includes a tray app (papernym-gui) and a command line (papernym).",
    ]) + "\n", encoding="utf-8")
    for path in root.rglob("*"):  # dpkg wants sane permissions regardless of the umask
        if path.is_symlink():
            continue
        if path.is_dir() or os.access(path, os.X_OK):
            path.chmod(0o755)
        else:
            path.chmod(0o644)

    deb = DIST / f"{PACKAGE}_{deb_version}_amd64.deb"
    deb.unlink(missing_ok=True)
    run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", root, deb])
    run(["dpkg-deb", "--info", deb])
    return deb


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-deb", action="store_true", help="build the app folder only")
    parser.add_argument("--snapshot", action="store_true",
                        help="add +git<date>.<sha> to the package version (test builds)")
    parser.add_argument("--expected-version", help="fail unless the package version equals this")
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        raise SystemExit("build_linux.py runs on Linux only")
    ver = version()
    if args.expected_version and args.expected_version.lstrip("v") != ver:
        raise SystemExit(f"version mismatch: tag {args.expected_version}, package {ver}")
    deb_version = ver + (git_snapshot() if args.snapshot else "")
    print(f"Building PaperNym {deb_version}", flush=True)

    shutil.rmtree(APP_DIR, ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", DIST,
         "--workpath", BUILD / "pyinstaller", ROOT / "packaging" / "papernym.spec"], cwd=ROOT)
    for name in ("PaperNym", "papernym-cli"):
        if not (APP_DIR / name).is_file():
            raise SystemExit(f"missing {APP_DIR / name}")
    shutil.copy2(ROOT / "LICENSE", APP_DIR / "LICENSE.txt")
    third_party_licenses(APP_DIR / "THIRD_PARTY_LICENSES.txt", LINUX_BUNDLED)
    smoke_test()
    print(f"App folder: {APP_DIR}")
    if args.no_deb:
        return 0
    if shutil.which("dpkg-deb") is None:
        raise SystemExit("dpkg-deb not found (it comes with dpkg on Debian and Ubuntu)")
    deb = build_deb(deb_version)
    digest = hashlib.sha256(deb.read_bytes()).hexdigest()
    (DIST / f"{deb.name}.sha256").write_text(f"{digest}  {deb.name}\n", encoding="ascii")
    print(f"Package: {deb}\nSHA256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
