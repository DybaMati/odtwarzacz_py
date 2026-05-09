#!/usr/bin/env python3
"""Uruchomienie aplikacji desktopowej (Tkinter — Raspberry Pi OK)."""

from __future__ import annotations

import tkinter as tk

from ui_main_window import MainApp


def main() -> None:
    root = tk.Tk()
    MainApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
