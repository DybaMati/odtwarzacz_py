# Odtwarzacz (Linux / Python)

Desktopowy odtwarzacz audio z harmonogramem seansów, fade i WebSocket — **bez** mieszania z `lista.html`.

## Wymagania

- Python 3.11+
- Linux: zainstalowany **VLC** (`vlc`, biblioteki `libvlc`)
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

## Uruchomienie

```bash
python main.py
```

## Okno

Domyślnie **750×600** px (minimalnie trochę mniej, żeby się mieściło UI).

## Zakładki

1. **Odtwarzacz i seanse** — lista, transport, suwaki + harmonogram seansów + panel „co się dzieje”.
2. **Ustawienia** — PIN, WS, czasy, fade, ścieżki zapowiedzi (szczegóły w aplikacji).
3. **Log** — krótki dziennik zdarzeń.

Konfiguracja zapisywana do pliku `config.json` (obok `main.py`).
