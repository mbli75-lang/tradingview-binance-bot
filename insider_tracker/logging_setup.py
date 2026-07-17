"""Loggning till fil + konsol. Fel kan vidarebefordras till Telegram (steg 4)."""
from __future__ import annotations

import logging
from pathlib import Path

from insider_tracker.config import load_config

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    cfg = load_config()
    log_cfg = cfg.get("logging", {}) or {}
    level = getattr(logging, str(log_cfg.get("level", "INFO")).upper(), logging.INFO)
    log_file = log_cfg.get("file", "logs/insider_tracker.log")

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    root = logging.getLogger()
    root.setLevel(level)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    _configured = True
