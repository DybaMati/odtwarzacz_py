"""Silnik audio VLC + rozwiązywanie URL YouTube przez yt-dlp."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ytdlp_utils import get_audio_stream_url

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

    def load_url(self, url: str) -> tuple[bool, str | None]:
        """
        Ładuje media. Dla YouTube wyciąga strumień przez yt-dlp.
        Zwraca (sukces, komunikat_błędu).
        """
        if not self._player or not self._instance:
            return False, "Brak VLC"
        stream, err = get_audio_stream_url(url)
        if not stream:
            return False, err or "Nieznany błąd URL"
        self._media_path = stream
        media = self._instance.media_new(stream)
        self._player.set_media(media)
        return True, None

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
