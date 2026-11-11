import subprocess
import sys

import pytest

from papernym.core.lock import LockBusyError, WriterLock


def test_only_one_writer_and_release(tmp_path):
    with WriterLock(tmp_path) as first:
        assert first.path == tmp_path / "lock"
        with pytest.raises(LockBusyError):
            WriterLock(tmp_path).acquire()
        code = ("from papernym.core.lock import WriterLock,LockBusyError; "
                f"lock=WriterLock({str(tmp_path)!r}); "
                "\ntry: lock.acquire()\nexcept LockBusyError: raise SystemExit(7)\n"
                "raise SystemExit(0)")
        child = subprocess.run([sys.executable, "-c", code], check=False, capture_output=True)
        assert child.returncode == 7
    with WriterLock(tmp_path):
        pass


def test_explicit_release_is_idempotent(tmp_path):
    lock = WriterLock(tmp_path)
    lock.acquire()
    lock.acquire()
    lock.release()
    lock.release()
    with WriterLock(tmp_path):
        pass
