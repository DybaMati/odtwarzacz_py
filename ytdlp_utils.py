"""YouTube: tytuł i URL strumienia — moduł yt_dlp lub program yt-dlp z PATH (apt)."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

INSTALL_YT_DLP_MSG = (
    "Brak yt-dlp dla tego Pythona i brak programu „yt-dlp” w systemie.\n\n"
    "Opcja A — w folderze projektu (venv):\n"
    "  cd ~/Desktop/odtwarzacz_py\n"
    "  python3 -m venv .venv\n"
    "  source .venv/bin/activate\n"
    "  pip install --upgrade pip yt-dlp\n"
    "  python main.py\n\n"
    "Opcja B — pakiet systemowy (bez pip):\n"
    "  sudo apt update\n"
    "  sudo apt install -y yt-dlp ffmpeg\n\n"
    "Uruchamiaj aplikację tak samo jak instalowałeś pakiet (ten sam venv)."
)


def _which_ytdlp_cli() -> str | None:
    return shutil.which("yt-dlp")


def _youtube_like(url: str) -> bool:
    u = (url or "").lower().strip()
    return "youtube.com" in u or "youtu.be" in u


def _title_via_cli_print(cli: str, page_url: str) -> str | None:
    """Szybka ścieżka — bez pełnego JSON (zwykle znacznie krócej)."""
    try:
        r = subprocess.run(
            [cli, "--no-warnings", "--no-playlist", "--skip-download", "--print", "%(title)s", page_url],
            capture_output=True,
            text=True,
            timeout=11,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    for line in (r.stdout or "").strip().splitlines():
        t = line.strip()
        if t:
            return t
    return None


def _title_via_cli_json(cli: str, page_url: str) -> tuple[str | None, str | None]:
    try:
        r = subprocess.run(
            [cli, "--dump-json", "--no-playlist", "--skip-download", "--no-warnings", page_url],
            capture_output=True,
            text=True,
            timeout=18,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return None, str(e)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip() or f"kod {r.returncode}"
        return None, err
    try:
        info = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None, "Zła odpowiedź JSON od yt-dlp"
    title = (info.get("title") or info.get("fulltitle") or "").strip()
    return (title or None), None


def _stream_via_cli(cli: str, page_url: str) -> tuple[str | None, str | None]:
    last_stderr = ""
    for fmt in ("bestaudio/best", "bestaudio", "best", "18"):
        try:
            r = subprocess.run(
                [cli, "--no-warnings", "--no-playlist", "--get-url", "-f", fmt, page_url],
                capture_output=True,
                text=True,
                timeout=35,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            return None, str(e)
        last_stderr = (r.stderr or "").strip()
        if r.returncode != 0:
            continue
        for ln in (r.stdout or "").strip().splitlines():
            ln = ln.strip()
            if ln.startswith("http"):
                return ln, None
    return None, last_stderr or "yt-dlp --get-url nie zwrócił adresu (zainstaluj ffmpeg?)"


def fetch_title(url: str) -> tuple[str | None, str | None]:
    """Zwraca (tytuł, komunikat_błędu)."""
    if not url.strip():
        return None, "Pusty URL"

    cli = _which_ytdlp_cli()
    if cli:
        fast = _title_via_cli_print(cli, url)
        if fast:
            return fast, None

    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        YoutubeDL = None  # type: ignore

    if YoutubeDL is not None:
        fast_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "extract_flat": True,
            "socket_timeout": 10,
        }
        try:
            with YoutubeDL(fast_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info:
                title = (info.get("title") or info.get("fulltitle") or "").strip()
                if title:
                    return title, None
        except Exception:
            pass

        slow_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "extract_flat": False,
            "socket_timeout": 16,
        }
        try:
            with YoutubeDL(slow_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            last_py = str(e)
            if cli:
                t2, err2 = _title_via_cli_json(cli, url)
                if t2:
                    return t2, None
                return None, err2 or last_py
            return None, last_py
        if not info:
            return None, "Brak danych z yt-dlp"
        title = (info.get("title") or info.get("fulltitle") or "").strip()
        if title:
            return title, None
        if cli:
            return _title_via_cli_json(cli, url)
        return None, "Brak tytułu"

    if cli:
        return _title_via_cli_json(cli, url)
    return None, INSTALL_YT_DLP_MSG


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

    # Na Raspberry Pi CLI bywa stabilniejsze/szybsze niż moduł Python.
    cli = _which_ytdlp_cli()
    if cli:
        got, err = _stream_via_cli(cli, url)
        if got:
            return got, None

    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        YoutubeDL = None  # type: ignore

    if YoutubeDL is None:
        cli = _which_ytdlp_cli()
        if cli:
            return _stream_via_cli(cli, url)
        return None, INSTALL_YT_DLP_MSG

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
        "noplaylist": True,
        "socket_timeout": 28,
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

    if cli:
        got, err = _stream_via_cli(cli, url)
        if got:
            return got, None
        last_err = last_err or err

    return None, (
        last_err
        or "Nie udało się wyciągnąć strumienia. Spróbuj: sudo apt install ffmpeg"
    )


def ytdlp_available() -> tuple[bool, str]:
    """Czy działa biblioteka lub CLI (krótki opis do logu)."""
    try:
        import yt_dlp  # noqa: F401
        return True, "yt-dlp (moduł Python)"
    except ImportError:
        pass
    cli = _which_ytdlp_cli()
    if cli:
        return True, f"yt-dlp (program: {cli})"
    return False, "brak modułu i brak polecenia yt-dlp"
