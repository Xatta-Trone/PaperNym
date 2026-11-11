"""Nonblocking, OS-backed single-writer lock."""

from __future__ import annotations

import os
from pathlib import Path

from .config import settings_dir


class LockBusyError(RuntimeError):
    """Another PaperNym writer owns the settings folder."""


class WriterLock:
    def __init__(self, home: str | Path | None = None):
        self.path = settings_dir(home) / "lock"
        self._file = None

    def acquire(self):
        if self._file is not None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if stream.tell() == 0:
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise LockBusyError(f"PaperNym is already writing in {self.path.parent}") from exc
        self._file = stream
        return self

    def release(self):
        if self._file is None:
            return
        stream = self._file
        self._file = None
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()
