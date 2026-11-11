"""Rotating log file in the settings folder (logs/papernym.log, 5 x 1 MB)."""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

log = logging.getLogger("papernym")


def log_path(home: Path) -> Path:
    return Path(home) / "logs" / "papernym.log"


def setup_file_log(home: Path, level: int = logging.INFO) -> None:
    """Send the ``papernym`` logger to the settings folder's log; rebinds if the folder changes."""
    target = os.path.abspath(log_path(home))
    for handler in list(log.handlers):
        if getattr(handler, "_papernym", False):
            if handler.baseFilename == target:
                return
            log.removeHandler(handler)
            handler.close()
    try:
        log_path(home).parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(target, maxBytes=1_000_000, backupCount=4,
                                                       encoding="utf-8")
    except OSError:
        return
    handler._papernym = True
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(min(level, log.level or level))
    log.propagate = False
