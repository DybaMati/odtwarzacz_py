"""
Logika czasu seansów (odpowiednik harmonogramu z wersji HTML).

Stan tekstowy dla UI: co się dzieje teraz i co następne.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Callable

from config import AppConfig


@dataclass
class SeanceSlot:
    hour: int
    minute: int
    enabled: bool = True
    mode: str = "default"  # teatr | finska | default


def wall_seconds(h: int, m: int) -> int:
    return h * 3600 + m * 60


class ScheduleEngine:
    def __init__(
        self,
        get_config: Callable[[], AppConfig],
        slots: list[SeanceSlot],
    ) -> None:
        self._get_config = get_config
        self.slots = slots

    def now_seconds(self) -> int:
        n = dt.datetime.now().time()
        return n.hour * 3600 + n.minute * 60 + n.second

    def next_events_description(self) -> str:
        """Krótki opis dla kartki „co się dzieje”."""
        cfg = self._get_config()
        lines: list[str] = []
        now_s = self.now_seconds()

        active = [s for s in self.slots if s.enabled]
        if not active:
            lines.append("Brak zaznaczonych seansów.")
            return "\n".join(lines)

        nearest = None
        nearest_delta = 10**9
        for s in active:
            ss = wall_seconds(s.hour, s.minute)
            d = ss - now_s
            if d > 0 and d < nearest_delta:
                nearest_delta = d
                nearest = s

        lines.append(f"Czas serwera: {dt.datetime.now().strftime('%H:%M:%S')}")

        if nearest:
            t = f"{nearest.hour:02d}:{nearest.minute:02d}"
            qm = cfg.query_ws_minutes
            am = cfg.announcement_minutes_before
            duck = cfg.pre_seance_duck_seconds
            rm = cfg.resume_minutes_after_start
            ss = wall_seconds(nearest.hour, nearest.minute)
            lines.append(f"Najbliższy seans: {t}")
            lines.append(
                f"  • Zapytanie WS: ok. {qm} min przed → "
                f"{self._fmt_before(ss, qm * 60)}"
            )
            lines.append(
                f"  • Zapowiedź głosowa: ok. {am} min przed → "
                f"{self._fmt_before(ss, am * 60)}"
            )
            lines.append(
                f"  • Duck ~30%: ostatnie {duck}s przed seansem → "
                f"{self._fmt_window(ss - duck, ss)}"
            )
            lines.append(
                f"  • Podgłośnienie po seansie: +{rm} min od godziny seansu → "
                f"{self._fmt_after(ss, rm * 60)}"
            )
        else:
            lines.append("Dziś nie ma już przyszłych seansów (wg listy).")

        lines.append("")
        lines.append(
            "Uwaga: faktyczne odpalenie zapowiedzi/duck/restart "
            "podłączymy w kolejnej iteracji do silnika audio."
        )
        return "\n".join(lines)

    def _fmt_before(self, seans_sec: int, delta_sec: int) -> str:
        t = seans_sec - delta_sec
        if t < 0:
            t += 24 * 3600
        return self._fmt_clock(t)

    def _fmt_after(self, seans_sec: int, delta_sec: int) -> str:
        t = seans_sec + delta_sec
        return self._fmt_clock(t % (24 * 3600))

    def _fmt_window(self, start_s: int, end_s: int) -> str:
        return f"{self._fmt_clock(start_s)} – {self._fmt_clock(end_s)}"

    def _fmt_clock(self, sec: int) -> str:
        sec = sec % (24 * 3600)
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        return f"{h:02d}:{m:02d}:{s:02d}"


def default_slots_thirteen_to_twentytwo() -> list[SeanceSlot]:
    """Domyślna siatka jak w starej liście (13:00–22:00 co godzinę)."""
    return [SeanceSlot(hour=h, minute=0, enabled=True) for h in range(13, 23)]
