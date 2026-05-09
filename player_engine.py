"""Silnik audio VLC + rozwiązywanie URL YouTube przez yt-dlp."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ytdlp_utils import get_audio_stream_url

try:
    import vlc  # type: ignore
except ImportError:
    vlc = None  # uruchomienie bez VLC — tylko UI


def vlc_setup_hint() -> str:
    return (
        "VLC dla Pythona: sudo apt install vlc libvlc-dev && "
        "w venv: pip install python-vlc  (ten sam venv co python main.py)"
    )


class PlayerEngine:
    def __init__(self, on_position: Callable[[float], None] | None = None) -> None:
        self._on_position = on_position
        self._media_path: str | None = None
        self._instance = None
        self._player = None
        self._init_error: str | None = None

        if vlc is None:
            self._init_error = "Brak modułu python-vlc. " + vlc_setup_hint()
            return
        try:
            self._instance = vlc.Instance("--no-video", "--intf", "dummy")
            if self._instance is None:
                self._instance = vlc.Instance("--no-video")
            if self._instance is None:
                self._init_error = "vlc.Instance() zwróciło None. " + vlc_setup_hint()
                return
            self._player = self._instance.media_player_new()
            if self._player is None:
                self._init_error = "Nie utworzono odtwarzacza VLC. " + vlc_setup_hint()
        except Exception as e:
            try:
                self._instance = vlc.Instance("--no-video")
                self._player = self._instance.media_player_new() if self._instance else None
                if self._player:
                    self._init_error = None
                else:
                    raise RuntimeError("brak playera") from e
            except Exception as e2:
                self._instance = None
                self._player = None
                self._init_error = f"VLC: {e2}. " + vlc_setup_hint()

    def init_error(self) -> str | None:
        return self._init_error

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

    def load_stream_url(self, stream_url: str) -> tuple[bool, str | None]:
        """Ustawia media z gotowego URL strumienia (wywołać z wątku głównego GUI)."""
        if not self._player or not self._instance:
            return False, self._init_error or "Brak VLC"
        try:
            self._media_path = stream_url
            media = self._instance.media_new(stream_url)
            self._player.set_media(media)
            return True, None
        except Exception as e:
            return False, str(e)

    def load_url(self, url: str) -> tuple[bool, str | None]:
        """
        Ładuje media. Dla YouTube wyciąga strumień przez yt-dlp.
        Może długo trwać — do GUI użyj load_stream_url po get_audio_stream_url w wątku.
        """
        if not self._player or not self._instance:
            return False, self._init_error or "Brak VLC"
        stream, err = get_audio_stream_url(url)
        if not stream:
            return False, err or "Nieznany błąd URL"
        return self.load_stream_url(stream)

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
