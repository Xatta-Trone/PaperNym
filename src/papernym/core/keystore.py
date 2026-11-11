"""API keys in the operating system's credential store instead of config.json.

Windows: Credential Manager. Linux: the Secret Service (GNOME Keyring, KWallet 5.97+ or
KeePassXC) over D-Bus. macOS: Keychain. All through the ``keyring`` package.

When no store is usable (a Linux server without a desktop session, or
``PAPERNYM_KEYRING=off``), keys stay in config.json, which is then made readable only by
the user (mode 600 on Linux). Environment variables always take precedence and are never
stored.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

log = logging.getLogger("papernym")

SECRET_KEYS = {"openalex_key": "OPENALEX_API_KEY", "s2_key": "S2_API_KEY"}
SERVICE = "PaperNym"
OFF_VALUES = ("0", "off", "no", "false", "file")
_MODULE_NAMES = {
    "keyring.backends.Windows": "Windows Credential Manager",
    "keyring.backends.SecretService": "the system keyring (Secret Service)",
    "keyring.backends.libsecret": "the system keyring (libsecret)",
    "keyring.backends.kwallet": "KWallet",
    "keyring.backends.macOS": "the macOS Keychain",
}
_probe_cache: dict[int, bool] = {}


class SecretStoreError(RuntimeError):
    """The credential store refused to save or read a key."""


def _backend():
    if os.environ.get("PAPERNYM_KEYRING", "").strip().lower() in OFF_VALUES:
        return None
    try:
        import keyring
        from keyring.backends import chainer, fail
    except ImportError:
        return None
    backend = keyring.get_keyring()
    if isinstance(backend, fail.Keyring):
        return None
    if isinstance(backend, chainer.ChainerBackend) and not backend.backends:
        return None
    if type(backend).__module__.startswith(("keyring.backends.null", "keyrings.alt")):
        return None  # a plain-text store is no better than config.json
    key = id(backend)
    if key not in _probe_cache:
        try:
            backend.get_password(SERVICE, "probe")
            _probe_cache[key] = True
        except Exception as exc:  # a locked or missing D-Bus session, for example
            log.info("system keyring unusable: %s", exc)
            _probe_cache[key] = False
    return backend if _probe_cache[key] else None


def _default_home() -> Path:
    from .config import settings_dir

    saved = os.environ.pop("PAPERNYM_HOME", None)
    try:
        return settings_dir()
    finally:
        if saved is not None:
            os.environ["PAPERNYM_HOME"] = saved


def service_name(home: str | Path) -> str:
    """``PaperNym`` for the normal settings folder; a separate name for any other folder."""
    here = os.path.normcase(os.path.abspath(Path(home).expanduser()))
    if here == os.path.normcase(os.path.abspath(_default_home())):
        return SERVICE
    return f"{SERVICE}-{hashlib.sha1(here.encode('utf-8')).hexdigest()[:12]}"


class SecretStore:
    def __init__(self, home: str | Path):
        self.home = Path(home)
        self.service = service_name(home)
        self.backend = _backend()

    def available(self) -> bool:
        return self.backend is not None

    def describe(self) -> str:
        if self.backend is None:
            return "config.json (no system credential store found)"
        module = type(self.backend).__module__
        return next((name for prefix, name in _MODULE_NAMES.items() if module.startswith(prefix)),
                    type(self.backend).__name__)

    def get(self, name: str) -> str:
        if self.backend is None:
            return ""
        try:
            return self.backend.get_password(self.service, name) or ""
        except Exception as exc:
            raise SecretStoreError(f"cannot read {name} from {self.describe()}: {exc}") from exc

    def set(self, name: str, value: str) -> None:
        """Store ``value``; an empty value removes the entry."""
        if self.backend is None:
            raise SecretStoreError("no system credential store is available")
        try:
            if value:
                self.backend.set_password(self.service, name, value)
            elif self.backend.get_password(self.service, name) is not None:
                self.backend.delete_password(self.service, name)
        except Exception as exc:
            raise SecretStoreError(f"cannot save {name} in {self.describe()}: {exc}") from exc


def reset_cache() -> None:
    _probe_cache.clear()
