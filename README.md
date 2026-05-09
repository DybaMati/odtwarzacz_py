# Odtwarzacz (Linux / Python)

Desktopowy odtwarzacz audio z harmonogramem seansów, fade i WebSocket — **bez** mieszania z `lista.html`.

## Wymagania

- Python 3.11+
- Linux: zainstalowany **VLC** (`vlc`, biblioteki `libvlc`) — aplikacja w logu przy starcie wypisuje, czy VLC się podniosło; jeśli nie: `sudo apt install vlc libvlc-dev` oraz w **venv**: `pip install python-vlc`
- Dla YouTube: pakiet **ffmpeg** w systemie (`sudo apt install ffmpeg`) — często wymagany, żeby `yt-dlp` i VLC miały poprawny strumień audio
- Interfejs: **Tkinter** (standardowa biblioteka) — działa na **Raspberry Pi** bez PySide6.

```bash
sudo apt install vlc libvlc-dev   # Debian/Ubuntu — nazwy mogą się różnić
```

## Instalacja

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Na Raspberry Pi **nie instaluj PySide6** — nie ma stabilnych kół ARM na PyPI; aplikacja używa Tkintera.

### yt-dlp — „brak pakietu”

Działa **albo** moduł Python (`pip install yt-dlp` w **tym samym** venv co `python main.py`), **albo** program systemowy (`sudo apt install yt-dlp`). Aplikacja po starcie wpisuje w **Log**, która opcja jest widoczna.

## Uruchomienie

```bash
python main.py
```

## Okno

Domyślnie **750×600** px (minimalnie trochę mniej, żeby się mieściło UI).

## Zakładki

1. **Odtwarzacz i seanse** — playlista (tytuł + URL YouTube), transport, suwaki + **edytowalny harmonogram** (checkbox, godzina, minuta, radio Teatr / Fińska / Domyślna, usuń wiersz) + panel „co się dzieje”.
2. **Ustawienia** — PIN, WS, czasy, fade, ścieżki zapowiedzi (szczegóły w aplikacji).
3. **Log** — krótki dziennik zdarzeń.

Konfiguracja zapisywana do pliku `config.json` (obok `main.py`): pole `yt_playlist` oraz `seance_slots`.

**Log i komunikaty:** w zakładce „Log” oraz w polu „Instalacja VLC / yt-dlp” (Ustawienia) tekst można **zaznaczyć myszą** i skopiować (**Ctrl+C** lub **PPM → Kopiuj**). Są też przyciski „Kopiuj cały log” / „Kopiuj zaznaczenie”.

- **Zapisz playlistę** — zapisuje listę utworów.
- **Zapisz harmonogram** — zapisuje godziny i tryby seansów (bez PIN-u).
- **Zapisz ustawienia** (zakładka Ustawienia) — zapisuje też aktualną playlistę i seanse do jednego pliku.
