"""YouTube: pobieranie tytułu i adresu strumienia audio dla VLC (yt-dlp)."""

from __future__ import annotations

from typing import Any


def _youtube_like(url: str) -> bool:
    u = (url or "").lower().strip()
    return "youtube.com" in u or "youtu.be" in u


def fetch_title(url: str) -> tuple[str | None, str | None]:
    """Zwraca (tytuł, komunikat_błędu)."""
    if not url.strip():
        return None, "Pusty URL"
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        return None, "Brak pakietu yt-dlp (pip install yt-dlp)"

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "socket_timeout": 20,
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return None, str(e)

    if not info:
        return None, "Brak danych z yt-dlp"
    title = (info.get("title") or info.get("fulltitle") or "").strip()
    return (title or None), None


def _extract_playable_url(info: Any) -> str | None:
    if not info or not isinstance(info, dict):
        return None
    direct = info.get("url")
    if isinstance(direct, str) and direct.startswith("http"):
        return direct
    for fmt in info.get("requested_formats") or []:
        u = fmt.get("url")
        if isinstance(u, str) and u.startswith("http"):
            return u
    # ostatnia deska ratunku: przejrzyj listę formatów
    for fmt in info.get("formats") or []:
        u = fmt.get("url")
        if isinstance(u, str) and u.startswith("http"):
            return u
    return None


def get_audio_stream_url(url: str) -> tuple[str | None, str | None]:
    """
    Dla YouTube zwraca bezpośredni URL strumienia audio dla VLC.
    Dla innych http(s) zwraca ten sam URL.
    """
    url = (url or "").strip()
    if not url.startswith("http"):
        return None, "Nieprawidłowy URL"

    if not _youtube_like(url):
        return url, None

    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        return None, "Brak pakietu yt-dlp (pip install yt-dlp)"

    format_candidates = (
        "bestaudio/best",
        "bestaudio",
        "ba/bestaudio/best",
        "best",
        "18",
    )
    last_err: str | None = None
    base_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 35,
    }
    for fmt in format_candidates:
        opts = dict(base_opts)
        opts["format"] = fmt
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            last_err = str(e)
            continue
        picked = _extract_playable_url(info)
        if picked:
            return picked, None
        last_err = last_err or "Brak pola url w odpowiedzi yt-dlp"

    return None, (
        last_err
        or "Nie udało się wyciągnąć strumienia. Na Raspberry Pi zwykle pomoże: sudo apt install ffmpeg"
    )
