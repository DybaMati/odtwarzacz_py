"""Niezależny odtwarzacz zapowiedzi oparty o ffplay (ffmpeg)."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path


class AnnouncementPlayer:
    """Prosty odtwarzacz lokalnych plików audio dla zapowiedzi."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def play_file(self, path: str) -> tuple[bool, str | None]:
        p = Path(path).expanduser()
        if not p.exists():
            return False, f"Plik nie istnieje: {p}"
        if not p.is_file():
            return False, f"To nie jest plik: {p}"

        with self._lock:
            self.stop()
            cmd = [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "error",
                str(p),
            ]
            try:
                self._proc = subprocess.Popen(cmd)
                return True, None
            except FileNotFoundError:
                return False, "Brak ffplay. Zainstaluj pakiet ffmpeg."
            except Exception as e:
                return False, str(e)

    def is_playing(self) -> bool:
        with self._lock:
            return bool(self._proc and self._proc.poll() is None)

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
            if not proc:
                return
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            self._proc = None
