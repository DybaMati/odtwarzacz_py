"""Ładowanie i zapis ustawień (JSON)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AppConfig:
    pin_hash_hex: str = ""  # SHA256 hex — jeśli puste, pierwsze wejście ustawia PIN
    ws_alarm_url: str = ""
    ws_player_url: str = ""

    query_ws_minutes: int = 15
    announcement_minutes_before: int = 10
    resume_minutes_after_start: int = 4

    fade_out_ms: int = 7000
    fade_in_ms: int = 14000
    pre_seance_duck_seconds: int = 30
    pre_seance_duck_ratio: float = 0.3

    yt_playlist: list[dict[str, str]] = field(
        default_factory=lambda: [{"title": "Przykład", "url": ""}]
    )

    announcement_teatr: str = ""
    announcement_finska: str = ""
    announcement_default: str = ""

    window_width: int = 750
    window_height: int = 600


def config_path() -> Path:
    return Path(__file__).resolve().parent / "config.json"


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return AppConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _dict_to_config(raw)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return AppConfig()


def save_config(cfg: AppConfig) -> None:
    path = config_path()
    path.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")


def _dict_to_config(d: dict[str, Any]) -> AppConfig:
    known = {f.name for f in AppConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in d.items() if k in known}
    return AppConfig(**filtered)
