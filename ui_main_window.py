"""Główne okno: zakładka Odtwarzacz+seanse, Ustawienia, Log — Tkinter (działa na Raspberry Pi)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from config import AppConfig, load_config, save_config
from player_engine import PlayerEngine
from schedule_engine import ScheduleEngine, default_slots_thirteen_to_twentytwo
from security import hash_pin, verify_pin


class MainApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._cfg = load_config()
        self._slots = default_slots_thirteen_to_twentytwo()
        self._schedule = ScheduleEngine(lambda: self._cfg, self._slots)
        self._player = PlayerEngine()
        self._settings_unlocked = not bool(self._cfg.pin_hash_hex)
        self._slider_sync = False

        root.title("Odtwarzacz — seanse")
        w = max(600, self._cfg.window_width)
        h = max(520, self._cfg.window_height)
        root.geometry(f"{w}x{h}")
        root.minsize(700, 560)

        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self._build_player_tab(notebook)
        self._build_settings_tab(notebook)
        self._build_log_tab(notebook)

        self._log("Start aplikacji.")
        if not self._player.available():
            self._log("Ostrzeżenie: brak python-vlc / libvlc — transport będzie pusty.")

        root.after(400, self._tick_transport)
        root.after(1000, self._refresh_status_loop)

    def _build_player_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="Odtwarzacz i seanse")

        pan = ttk.PanedWindow(tab, orient=tk.HORIZONTAL)
        pan.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(pan, width=360)
        right = ttk.Frame(pan, width=320)
        pan.add(left, weight=3)
        pan.add(right, weight=2)

        ttk.Label(left, text="Lista odtwarzania (tytuł + URL — config.json)").pack(anchor=tk.W)
        self.playlist = tk.Listbox(left, height=12, exportselection=False)
        self.playlist.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self._fill_playlist_from_config()

        row = ttk.Frame(left)
        row.pack(fill=tk.X)
        ttk.Button(row, text="Odtwarzaj", command=self._on_play).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row, text="Pauza", command=self._on_pause).pack(side=tk.LEFT)

        ttk.Label(left, text="Pozycja").pack(anchor=tk.W)
        self.var_pos = tk.IntVar(value=0)
        self.scale_pos = ttk.Scale(
            left,
            from_=0,
            to=1000,
            orient=tk.HORIZONTAL,
            variable=self.var_pos,
            command=self._on_seek_scale,
        )
        self.scale_pos.pack(fill=tk.X)

        ttk.Label(left, text="Głośność").pack(anchor=tk.W, pady=(8, 0))
        self.var_vol = tk.IntVar(value=70)
        self.scale_vol = ttk.Scale(
            left,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            variable=self.var_vol,
            command=self._on_volume_scale,
        )
        self.scale_vol.pack(fill=tk.X)

        ttk.Label(right, text="Harmonogram seansów (domyślnie 13:00–22:00)").pack(anchor=tk.W)
        self.seance_list = tk.Text(right, height=8, wrap=tk.WORD, state=tk.DISABLED)
        self.seance_list.pack(fill=tk.X, pady=(0, 6))
        self._refresh_seance_text_buffer()

        ttk.Label(right, text="Co się dzieje / następne kroki").pack(anchor=tk.W)
        self.status_box = tk.Text(right, height=14, wrap=tk.WORD, state=tk.DISABLED)
        self.status_box.pack(fill=tk.BOTH, expand=True)

    def _build_settings_tab(self, notebook: ttk.Notebook) -> None:
        outer = ttk.Frame(notebook)
        notebook.add(outer, text="Ustawienia")

        canvas = tk.Canvas(outer, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.configure(yscrollcommand=scroll.set)

        inner = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=inner, anchor=tk.NW)

        def _on_configure(_event: tk.Event) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        inner.bind("<Configure>", _on_configure)

        pin_fr = ttk.LabelFrame(inner, text="Dostęp do ustawień (PIN)")
        pin_fr.pack(fill=tk.X, padx=4, pady=6)
        ttk.Label(pin_fr, text="PIN:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=2)
        self.pin_input = ttk.Entry(pin_fr, show="*")
        self.pin_input.grid(row=0, column=1, sticky=tk.EW, padx=4, pady=2)
        ttk.Label(pin_fr, text="Nowy PIN (pierwszy raz):").grid(row=1, column=0, sticky=tk.W, padx=4, pady=2)
        self.pin_new = ttk.Entry(pin_fr, show="*")
        self.pin_new.grid(row=1, column=1, sticky=tk.EW, padx=4, pady=2)
        ttk.Button(pin_fr, text="Odblokuj / ustaw PIN", command=self._on_pin_action).grid(
            row=2, column=0, columnspan=2, pady=6
        )
        pin_fr.columnconfigure(1, weight=1)

        net_fr = ttk.LabelFrame(inner, text="Sieć")
        net_fr.pack(fill=tk.X, padx=4, pady=6)
        ttk.Label(net_fr, text="WebSocket alarmy:").grid(row=0, column=0, sticky=tk.W, padx=4)
        self.ws_alarm = ttk.Entry(net_fr)
        self.ws_alarm.insert(0, self._cfg.ws_alarm_url)
        self.ws_alarm.grid(row=0, column=1, sticky=tk.EW, padx=4, pady=2)
        ttk.Label(net_fr, text="WebSocket status playera:").grid(row=1, column=0, sticky=tk.W, padx=4)
        self.ws_player = ttk.Entry(net_fr)
        self.ws_player.insert(0, self._cfg.ws_player_url)
        self.ws_player.grid(row=1, column=1, sticky=tk.EW, padx=4, pady=2)
        net_fr.columnconfigure(1, weight=1)

        time_fr = ttk.LabelFrame(inner, text="Czasy automatyki (minuty)")
        time_fr.pack(fill=tk.X, padx=4, pady=6)
        self.sp_query = tk.Spinbox(time_fr, from_=0, to=180, width=8)
        self.sp_query.delete(0, tk.END)
        self.sp_query.insert(0, str(self._cfg.query_ws_minutes))
        self.sp_ann = tk.Spinbox(time_fr, from_=0, to=180, width=8)
        self.sp_ann.delete(0, tk.END)
        self.sp_ann.insert(0, str(self._cfg.announcement_minutes_before))
        self.sp_resume = tk.Spinbox(time_fr, from_=0, to=180, width=8)
        self.sp_resume.delete(0, tk.END)
        self.sp_resume.insert(0, str(self._cfg.resume_minutes_after_start))
        ttk.Label(time_fr, text="Pytanie WS — min przed seansem:").grid(row=0, column=0, sticky=tk.W, padx=4)
        self.sp_query.grid(row=0, column=1, sticky=tk.W, padx=4)
        ttk.Label(time_fr, text="Zapowiedź — min przed seansem:").grid(row=1, column=0, sticky=tk.W, padx=4)
        self.sp_ann.grid(row=1, column=1, sticky=tk.W, padx=4)
        ttk.Label(time_fr, text="Podgłośnienie po seansie — min po godzinie seansu:").grid(
            row=2, column=0, sticky=tk.W, padx=4
        )
        self.sp_resume.grid(row=2, column=1, sticky=tk.W, padx=4)

        fade_fr = ttk.LabelFrame(inner, text="Fade i duck")
        fade_fr.pack(fill=tk.X, padx=4, pady=6)
        self.sp_fo = tk.Spinbox(fade_fr, from_=500, to=120000, increment=500, width=10)
        self.sp_fo.delete(0, tk.END)
        self.sp_fo.insert(0, str(self._cfg.fade_out_ms))
        self.sp_fi = tk.Spinbox(fade_fr, from_=500, to=300000, increment=500, width=10)
        self.sp_fi.delete(0, tk.END)
        self.sp_fi.insert(0, str(self._cfg.fade_in_ms))
        self.sp_duck_sec = tk.Spinbox(fade_fr, from_=5, to=300, width=8)
        self.sp_duck_sec.delete(0, tk.END)
        self.sp_duck_sec.insert(0, str(self._cfg.pre_seance_duck_seconds))
        ttk.Label(fade_fr, text="Fade-out (ms):").grid(row=0, column=0, sticky=tk.W, padx=4)
        self.sp_fo.grid(row=0, column=1, sticky=tk.W, padx=4)
        ttk.Label(fade_fr, text="Fade-in (ms):").grid(row=1, column=0, sticky=tk.W, padx=4)
        self.sp_fi.grid(row=1, column=1, sticky=tk.W, padx=4)
        ttk.Label(fade_fr, text="Okno duck przed seansem (s):").grid(row=2, column=0, sticky=tk.W, padx=4)
        self.sp_duck_sec.grid(row=2, column=1, sticky=tk.W, padx=4)

        ann_fr = ttk.LabelFrame(inner, text="Pliki zapowiedzi (ścieżki lokalne)")
        ann_fr.pack(fill=tk.X, padx=4, pady=6)
        ttk.Label(ann_fr, text="Teatr:").grid(row=0, column=0, sticky=tk.W, padx=4)
        self.path_teatr = ttk.Entry(ann_fr)
        self.path_teatr.insert(0, self._cfg.announcement_teatr)
        self.path_teatr.grid(row=0, column=1, sticky=tk.EW, padx=4)
        ttk.Label(ann_fr, text="Fińska:").grid(row=1, column=0, sticky=tk.W, padx=4)
        self.path_finska = ttk.Entry(ann_fr)
        self.path_finska.insert(0, self._cfg.announcement_finska)
        self.path_finska.grid(row=1, column=1, sticky=tk.EW, padx=4)
        ttk.Label(ann_fr, text="Domyślna:").grid(row=2, column=0, sticky=tk.W, padx=4)
        self.path_default = ttk.Entry(ann_fr)
        self.path_default.insert(0, self._cfg.announcement_default)
        self.path_default.grid(row=2, column=1, sticky=tk.EW, padx=4)
        ann_fr.columnconfigure(1, weight=1)

        ttk.Button(inner, text="Zapisz ustawienia", command=self._save_settings).pack(pady=10)

        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        self._settings_widgets = (
            self.ws_alarm,
            self.ws_player,
            self.sp_query,
            self.sp_ann,
            self.sp_resume,
            self.sp_fo,
            self.sp_fi,
            self.sp_duck_sec,
            self.path_teatr,
            self.path_finska,
            self.path_default,
        )
        self._apply_settings_lock_ui()

    def _build_log_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="Log")
        self.log_view = tk.Text(tab, wrap=tk.WORD, state=tk.DISABLED)
        self.log_view.pack(fill=tk.BOTH, expand=True)

    def _apply_settings_lock_ui(self) -> None:
        locked = not self._settings_unlocked
        for w in self._settings_widgets:
            try:
                w.configure(state=tk.DISABLED if locked else tk.NORMAL)
            except tk.TclError:
                pass

    def _read_spin_int(self, spin: tk.Spinbox, fallback: int) -> int:
        try:
            return int(spin.get())
        except (ValueError, tk.TclError):
            return fallback

    def _on_pin_action(self) -> None:
        pin = self.pin_input.get()
        new_pin = self.pin_new.get()
        if not self._cfg.pin_hash_hex:
            if len(new_pin) < 4:
                messagebox.showwarning("PIN", "Ustaw nowy PIN (min. 4 znaki).")
                return
            self._cfg.pin_hash_hex = hash_pin(new_pin)
            save_config(self._cfg)
            self._settings_unlocked = True
            self._apply_settings_lock_ui()
            self._log("Ustawiono PIN.")
            messagebox.showinfo("PIN", "PIN ustawiony. Ustawienia odblokowane.")
            return
        if verify_pin(pin, self._cfg.pin_hash_hex):
            self._settings_unlocked = True
            self._apply_settings_lock_ui()
            self._log("Ustawienia odblokowane.")
        else:
            messagebox.showwarning("PIN", "Nieprawidłowy PIN.")

    def _save_settings(self) -> None:
        if not self._settings_unlocked:
            messagebox.showwarning("PIN", "Najpierw odblokuj ustawienia.")
            return
        self._cfg.ws_alarm_url = self.ws_alarm.get().strip()
        self._cfg.ws_player_url = self.ws_player.get().strip()
        self._cfg.query_ws_minutes = self._read_spin_int(self.sp_query, self._cfg.query_ws_minutes)
        self._cfg.announcement_minutes_before = self._read_spin_int(
            self.sp_ann, self._cfg.announcement_minutes_before
        )
        self._cfg.resume_minutes_after_start = self._read_spin_int(
            self.sp_resume, self._cfg.resume_minutes_after_start
        )
        self._cfg.fade_out_ms = self._read_spin_int(self.sp_fo, self._cfg.fade_out_ms)
        self._cfg.fade_in_ms = self._read_spin_int(self.sp_fi, self._cfg.fade_in_ms)
        self._cfg.pre_seance_duck_seconds = self._read_spin_int(
            self.sp_duck_sec, self._cfg.pre_seance_duck_seconds
        )
        self._cfg.announcement_teatr = self.path_teatr.get().strip()
        self._cfg.announcement_finska = self.path_finska.get().strip()
        self._cfg.announcement_default = self.path_default.get().strip()
        self._cfg.window_width = self.root.winfo_width()
        self._cfg.window_height = self.root.winfo_height()
        save_config(self._cfg)
        self._refresh_seance_text_buffer()
        self._log("Zapisano config.json.")
        messagebox.showinfo("Zapis", "Zapisano ustawienia.")

    def _fill_playlist_from_config(self) -> None:
        self.playlist.delete(0, tk.END)
        for item in self._cfg.yt_playlist:
            title = item.get("title", "—")
            self.playlist.insert(tk.END, title)

    def _refresh_seance_text_buffer(self) -> None:
        lines = []
        for s in self._slots:
            if not s.enabled:
                continue
            lines.append(f"{s.hour:02d}:{s.minute:02d}  ({s.mode})")
        text = "\n".join(lines) if lines else "(brak)"
        self.seance_list.configure(state=tk.NORMAL)
        self.seance_list.delete("1.0", tk.END)
        self.seance_list.insert("1.0", text)
        self.seance_list.configure(state=tk.DISABLED)

    def _refresh_status_loop(self) -> None:
        self._refresh_status()
        self.root.after(1000, self._refresh_status_loop)

    def _refresh_status(self) -> None:
        body = self._schedule.next_events_description()
        self.status_box.configure(state=tk.NORMAL)
        self.status_box.delete("1.0", tk.END)
        self.status_box.insert("1.0", body)
        self.status_box.configure(state=tk.DISABLED)

    def _tick_transport(self) -> None:
        if self._player.available() and not self._slider_sync:
            pos = self._player.get_position()
            self.var_pos.set(int(pos * 1000))
            vol = self._player.get_volume()
            self.var_vol.set(vol)
        self.root.after(400, self._tick_transport)

    def _on_seek_scale(self, _val: str) -> None:
        if not self._player.available():
            return
        self._slider_sync = True
        try:
            self._player.set_position(self.var_pos.get() / 1000.0)
        finally:
            self.root.after(120, lambda: setattr(self, "_slider_sync", False))

    def _on_volume_scale(self, _val: str) -> None:
        self._player.set_volume(int(float(self.var_vol.get())))

    def _on_play(self) -> None:
        sel = self.playlist.curselection()
        if not sel:
            self._log("Wybierz pozycję na liście.")
            return
        idx = sel[0]
        entry = self._cfg.yt_playlist[idx] if idx < len(self._cfg.yt_playlist) else {}
        url = (entry.get("url") or "").strip()
        if url.startswith("http"):
            self._player.load_url(url)
            self._player.play()
            self._log(f"Play URL: {url[:60]}…")
        else:
            self._log("Brak URL — ustaw w config.json (playlista).")

    def _on_pause(self) -> None:
        self._player.pause()

    def _log(self, msg: str) -> None:
        self.log_view.configure(state=tk.NORMAL)
        self.log_view.insert(tk.END, msg + "\n")
        self.log_view.see(tk.END)
        self.log_view.configure(state=tk.DISABLED)
