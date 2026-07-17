"""Konfiguration: läser config.yaml och tillåter override via miljövariabler."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"


def _load_dotenv(path: Path) -> None:
    """Minimal .env-inläsare (utan externt beroende).

    Sätter endast variabler som inte redan finns i miljön (riktiga env-variabler
    vinner). Hoppar över kommentarer och tomma rader. Stödjer valfritt 'export '-
    prefix och enkla/dubbla citattecken kring värdet.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(REPO_ROOT / ".env")


class Config:
    """Tunn wrapper kring den inlästa YAML-dicten med lite bekvämlighet."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    @property
    def database_url(self) -> str:
        # Miljövariabeln vinner alltid (så byte till Supabase = ingen kodändring).
        return os.getenv("DATABASE_URL") or self._data["database"]["url"]

    @property
    def data(self) -> dict[str, Any]:
        return self._data


@lru_cache(maxsize=None)
def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(cfg_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return Config(data)
