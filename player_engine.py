"""Silnik audio VLC — szkielet (pełna integracja yt-dlp w kolejnej iteracji)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

try:
    import vlc  # type: ignore
except ImportError:
    vlc = None  # uruchomienie bez VLC — tylko UI


class PlayerEngine:
    def __init__(self, on_position: Callable[[float], None] | None = None) -> None:
        self._instance = vlc.Instance("--no-video") if vlc else None
        self._player = self._instance.media_player_new() if self._instance else None
        self._on_position = on_position
        self._media_path: str | None = None

    def available(self) -> bool:
        return self._player is not None

    def load_file(self, path: str) -> None:
        if not self._player or not self._instance:
            return
        p = Path(path)
        if not p.is_file():
            return
        self._media_path = str(p)
        media = self._instance.media_new_path(self._media_path)
        self._player.set_media(media)

    def load_url(self, url: str) -> None:
        """Na razie bezpośredni URL; stream YT dodamy przez yt-dlp."""
        if not self._player or not self._instance:
            return
        self._media_path = url
        media = self._instance.media_new(url)
        self._player.set_media(media)

    def play(self) -> None:
        if self._player:
            self._player.play()

    def pause(self) -> None:
        if self._player:
            self._player.pause()

    def set_volume(self, percent: int) -> None:
        if self._player:
            self._player.audio_set_volume(max(0, min(100, percent)))

    def get_volume(self) -> int:
        if self._player:
            return int(self._player.audio_get_volume())
        return 50

    def get_position(self) -> float:
        """0.0–1.0"""
        if self._player:
            return float(self._player.get_position())
        return 0.0

    def set_position(self, ratio: float) -> None:
        if self._player:
            self._player.set_position(max(0.0, min(1.0, ratio)))
