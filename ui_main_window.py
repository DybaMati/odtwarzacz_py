"""Główne okno: zakładka Odtwarzacz+seanse, Ustawienia, Log — Tkinter (działa na Raspberry Pi)."""

from __future__ import annotations

import copy
import datetime as dt
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from announcement_player import AnnouncementPlayer
from config import AppConfig, load_config, save_config
from player_engine import PlayerEngine, vlc_setup_hint
from schedule_engine import ScheduleEngine, SeanceSlot, slots_from_config, slots_to_json
from security import hash_pin, verify_pin
from ytdlp_utils import fetch_title, get_audio_stream_url, ytdlp_available


def install_hints_text() -> str:
    py = sys.executable or "python3"
    return (
        vlc_setup_hint()
        + "\n\n--- yt-dlp (tytuły / YouTube) ---\nsudo apt install -y yt-dlp ffmpeg\n"
        + f"LUB w venv: {py} -m pip install -U yt-dlp\n"
    )


class MainApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._cfg = load_config()
        self._slots = slots_from_config(self._cfg)
        self._migrate_legacy_seance_modes()
        self._playlist_data: list[dict[str, str]] = copy.deepcopy(self._cfg.yt_playlist)
        self._schedule = ScheduleEngine(lambda: self._cfg, self._slots)
        self._player = PlayerEngine()
        self._ann_player = AnnouncementPlayer()
        self._settings_unlocked = not bool(self._cfg.pin_hash_hex)
        self._slider_sync = False
        self._seance_row_refs: list[dict] = []
        self._last_geom_label = ""
        self._play_busy = False
        self._play_busy_since_ms = 0
        self._last_busy_log_ms = 0
        self._dbg_req_ms = 0
        self._dbg_stream_ms = 0
        self._dbg_play_cmd_ms = 0
        self._dbg_first_sec_logged = False
        self._dbg_label = ""
        self._last_status_body = ""
        self._last_countdown_text = ""
        self._ann_fired_keys: set[str] = set()
        self._ann_prepared_keys: set[str] = set()
        self._announcement_active = False
        self._yt_volume_before_announcement = 70

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
        ok_yt, yt_desc = ytdlp_available()
        self._log(f"yt-dlp: {'OK — ' + yt_desc if ok_yt else 'BRAK — zainstaluj pip yt-dlp lub apt yt-dlp'}")
        if not self._player.available():
            vlc_msg = self._player.init_error() or "Brak VLC (python-vlc / libvlc)."
            self._log(vlc_msg)
            self._log("--- Komendy instalacji (zaznacz w Log lub Zakładka Ustawienia → pole tekstowe) ---")
            for line in install_hints_text().splitlines():
                self._log(line)
        self._log("Zapowiedzi: niezależny player ffplay (nie resetuje streamu YT).")

        root.after(900, self._tick_transport)
        root.after(1500, self._refresh_status_loop)
        root.bind("<Configure>", self._on_root_configure)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._update_active_countdown()

    def _migrate_legacy_seance_modes(self) -> None:
        """
        Migracja starych configów: kiedy wszystkie sloty mają "teatr"
        (historyczny domyślny wybór), ustaw puste tryby.
        """
        if not self._slots:
            return
        modes = [s.mode for s in self._slots]
        if all(m == "teatr" for m in modes):
            for s in self._slots:
                s.mode = ""
            self._cfg.seance_slots = slots_to_json(self._slots)
            save_config(self._cfg)

    def _on_root_configure(self, _event: tk.Event) -> None:
        if not hasattr(self, "lbl_win_current"):
            return
        try:
            w, h = self.root.winfo_width(), self.root.winfo_height()
            if w < 10 or h < 10:
                return
            g = f"{w} × {h}"
            if g == self._last_geom_label:
                return
            self._last_geom_label = g
            self.lbl_win_current.configure(text=f"Aktualny rozmiar okna: {g} px")
        except tk.TclError:
            pass

    def _build_player_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="Odtwarzacz i seanse")

        pan = ttk.PanedWindow(tab, orient=tk.HORIZONTAL)
        pan.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(pan, width=380)
        right = ttk.Frame(pan, width=340)
        pan.add(left, weight=3)
        pan.add(right, weight=2)

        # —— Playlist ——
        pl_fr = ttk.LabelFrame(left, text="Playlista (YouTube / URL audio)")
        pl_fr.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        row_btns = ttk.Frame(pl_fr)
        row_btns.pack(fill=tk.X, padx=4, pady=4)
        ttk.Button(row_btns, text="Dodaj utwór…", command=self._show_add_playlist_dialog).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(row_btns, text="Usuń zaznaczone", command=self._playlist_remove).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(row_btns, text="Zapisz playlistę", command=self._playlist_save).pack(side=tk.LEFT)

        self.playlist = tk.Listbox(pl_fr, height=8, exportselection=False)
        self.playlist.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        self.playlist.bind("<Double-Button-1>", lambda _e: self._on_play())
        self._refresh_playlist_listbox()

        transport = ttk.Frame(left)
        transport.pack(fill=tk.X)
        ttk.Button(transport, text="Odtwarzaj", command=self._on_play).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(transport, text="Pauza", command=self._on_pause).pack(side=tk.LEFT)

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
        self.lbl_time = ttk.Label(left, text="Czas: 00:00 / --:--")
        self.lbl_time.pack(anchor=tk.W, pady=(2, 4))

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

        # —— Seanse ——
        sec_outer = ttk.LabelFrame(right, text="Harmonogram seansów")
        sec_outer.pack(fill=tk.BOTH, expand=True)

        btns_fr = ttk.Frame(sec_outer)
        btns_fr.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Button(btns_fr, text="Dodaj seans", command=self._seance_add).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns_fr, text="Zapisz harmonogram", command=self._seance_save).pack(side=tk.LEFT)

        cv_se = tk.Canvas(sec_outer, highlightthickness=0, height=220)
        sb_se = ttk.Scrollbar(sec_outer, orient=tk.VERTICAL, command=cv_se.yview)
        cv_se.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_se.pack(side=tk.RIGHT, fill=tk.Y)
        cv_se.configure(yscrollcommand=sb_se.set)

        self.seance_inner = ttk.Frame(cv_se)
        cv_se.create_window((0, 0), window=self.seance_inner, anchor=tk.NW)

        def _cfg_se(_e: tk.Event) -> None:
            cv_se.configure(scrollregion=cv_se.bbox("all"))

        self.seance_inner.bind("<Configure>", _cfg_se)

        def _scroll_se(event: tk.Event) -> None:
            if getattr(event, "num", 0) == 4:
                cv_se.yview_scroll(-1, "units")
            elif getattr(event, "num", 0) == 5:
                cv_se.yview_scroll(1, "units")

        cv_se.bind("<Button-4>", _scroll_se)
        cv_se.bind("<Button-5>", _scroll_se)

        self._rebuild_seance_rows(cv_se)

        st_head = ttk.Frame(right)
        st_head.pack(fill=tk.X, pady=(6, 2))
        ttk.Label(st_head, text="Co się dzieje / następne kroki — zaznacz tekst lub „Kopiuj”").pack(side=tk.LEFT)
        self.lbl_countdown = ttk.Label(
            right,
            text="Aktywne odliczanie: --:--:--",
            font=("TkDefaultFont", 10, "bold"),
        )
        self.lbl_countdown.pack(anchor=tk.W, pady=(0, 4))
        self.status_box = tk.Text(right, height=11, wrap=tk.WORD, font=("Courier", 9))
        self.status_box.pack(fill=tk.BOTH, expand=True, pady=(0, 2))
        self._wire_copyable_text(self.status_box, "status")
        ttk.Button(st_head, text="Kopiuj", command=lambda: self._copy_text_all(self.status_box)).pack(side=tk.RIGHT)

        self._seance_canvas = cv_se

    def _clipboard_set(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()

    def _copy_text_selection(self, w: tk.Text) -> None:
        try:
            t = w.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            return
        if t.strip():
            self._clipboard_set(t)

    def _copy_text_all(self, w: tk.Text) -> None:
        t = w.get("1.0", tk.END + "-1c")
        self._clipboard_set(t)

    def _wire_copyable_text(self, w: tk.Text, _name: str = "") -> None:
        """Tekst jak notatnik: Ctrl+C/A, Bez edycji; PPM menu; zaznaczanie myszą."""
        w.configure(undo=False, insertwidth=2)

        def block_key(ev: tk.Event) -> str | None:
            if ev.state & 0x0004 or ev.state & 0x20000:
                ks = ev.keysym.lower()
                if ks in ("c", "a"):
                    return None
                if ks == "x":
                    try:
                        w.get(tk.SEL_FIRST, tk.SEL_LAST)
                    except tk.TclError:
                        return "break"
                    return None
            nav = (
                "Left",
                "Right",
                "Up",
                "Down",
                "Home",
                "End",
                "Prior",
                "Next",
                "Return",
                "Escape",
            )
            if ev.keysym in nav:
                return None
            if len(ev.char or "") == 1:
                return "break"
            if ev.keysym in ("Shift_L", "Shift_R", "Control_L", "Control_R"):
                return None
            return "break"

        def block_paste(_ev: tk.Event) -> str:
            return "break"

        w.bind("<Key>", block_key)
        w.bind("<<Paste>>", block_paste)
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Kopiuj zaznaczenie", command=lambda wi=w: self._copy_text_selection(wi))
        menu.add_command(label="Kopiuj wszystko", command=lambda wi=w: self._copy_text_all(wi))

        def popup(ev: tk.Event) -> None:
            try:
                menu.tk_popup(ev.x_root, ev.y_root)
            finally:
                menu.grab_release()

        w.bind("<Button-3>", popup)

    def _set_notes_text(self, w: tk.Text, content: str) -> None:
        w.delete("1.0", tk.END)
        w.insert("1.0", content)
        w.mark_set(tk.INSERT, "1.0")

    def _update_active_countdown(self) -> None:
        now = self._schedule.now_seconds()
        nearest = None
        nearest_delta = 10**9
        for s in self._slots:
            if not s.enabled:
                continue
            sec = s.hour * 3600 + s.minute * 60
            d = sec - now
            if d > 0 and d < nearest_delta:
                nearest_delta = d
                nearest = s
        if nearest is None:
            txt = "Aktywne odliczanie: brak kolejnych seansów"
            if txt != self._last_countdown_text:
                self._last_countdown_text = txt
                self.lbl_countdown.configure(text=txt)
            return
        hh = nearest_delta // 3600
        mm = (nearest_delta % 3600) // 60
        ss = nearest_delta % 60
        mode_txt = "Teatr" if nearest.mode == "teatr" else ("Fińska" if nearest.mode == "finska" else "Brak")
        txt = (
            f"Aktywne odliczanie: {nearest.hour:02d}:{nearest.minute:02d} "
            f"[{mode_txt}] za {hh:02d}:{mm:02d}:{ss:02d}"
        )
        if txt != self._last_countdown_text:
            self._last_countdown_text = txt
            self.lbl_countdown.configure(text=txt)

    def _rebuild_seance_rows(self, canvas: tk.Canvas | None = None) -> None:
        cv = canvas or getattr(self, "_seance_canvas", None)
        for w in self.seance_inner.winfo_children():
            w.destroy()
        self._seance_row_refs.clear()

        for idx, slot in enumerate(self._slots):
            fr = ttk.Frame(self.seance_inner)
            fr.pack(fill=tk.X, pady=2, padx=2)

            ven = tk.BooleanVar(value=slot.enabled)
            ttk.Checkbutton(fr, variable=ven, width=2).pack(side=tk.LEFT, padx=(0, 4))

            ttk.Label(fr, text="Godz.").pack(side=tk.LEFT)
            sh = tk.Spinbox(fr, from_=0, to=23, width=3, justify=tk.CENTER)
            sh.delete(0, tk.END)
            sh.insert(0, str(slot.hour))
            sh.pack(side=tk.LEFT, padx=2)

            ttk.Label(fr, text="Min.").pack(side=tk.LEFT)
            sm = tk.Spinbox(fr, from_=0, to=59, width=3, justify=tk.CENTER)
            sm.delete(0, tk.END)
            sm.insert(0, str(slot.minute))
            sm.pack(side=tk.LEFT, padx=2)

            mode_var = tk.StringVar(value=slot.mode if slot.mode in ("teatr", "finska") else "")
            mode_fr = ttk.Frame(fr)
            mode_fr.pack(side=tk.LEFT, padx=(6, 2))
            ttk.Label(mode_fr, text="Tryb:").pack(side=tk.LEFT, padx=(0, 2))
            ttk.Radiobutton(mode_fr, text="Teatr", variable=mode_var, value="teatr").pack(side=tk.LEFT, padx=2)
            ttk.Radiobutton(mode_fr, text="Fińska", variable=mode_var, value="finska").pack(side=tk.LEFT, padx=2)

            ttk.Button(fr, text="✕", width=3, command=lambda i=idx: self._seance_remove(i)).pack(
                side=tk.RIGHT, padx=4
            )

            self._seance_row_refs.append(
                {"var_en": ven, "spin_h": sh, "spin_m": sm, "mode_var": mode_var, "idx": idx}
            )

        if cv:
            self.seance_inner.update_idletasks()
            cv.configure(scrollregion=cv.bbox("all"))

    def _read_slots_from_ui(self) -> None:
        for row in self._seance_row_refs:
            i = row["idx"]
            if i >= len(self._slots):
                continue
            s = self._slots[i]
            s.enabled = row["var_en"].get()
            try:
                s.hour = max(0, min(23, int(row["spin_h"].get())))
                s.minute = max(0, min(59, int(row["spin_m"].get())))
            except (ValueError, tk.TclError):
                pass
            m = row["mode_var"].get()
            s.mode = m if m in ("teatr", "finska") else ""

    def _seance_add(self) -> None:
        self._read_slots_from_ui()
        last = self._slots[-1] if self._slots else SeanceSlot(13, 0, True, "")
        self._slots.append(SeanceSlot(last.hour, last.minute, True, ""))
        self._rebuild_seance_rows()

    def _seance_remove(self, index: int) -> None:
        self._read_slots_from_ui()
        if 0 <= index < len(self._slots):
            del self._slots[index]
        self._rebuild_seance_rows()

    def _seance_save(self) -> None:
        self._read_slots_from_ui()
        self._cfg.seance_slots = slots_to_json(self._slots)
        save_config(self._cfg)
        self._log("Zapisano harmonogram seansów.")
        messagebox.showinfo("Harmonogram", "Zapisano godziny i tryby seansów.")

    def _refresh_playlist_listbox(self) -> None:
        self.playlist.delete(0, tk.END)
        for item in self._playlist_data:
            title = (item.get("title") or "—").strip()
            url = (item.get("url") or "").strip()
            short = url if len(url) <= 42 else url[:39] + "…"
            self.playlist.insert(tk.END, f"{title}  |  {short}")

    def _persist_playlist_quiet(self) -> None:
        """Auto-zapis playlisty bez wyskakujących okien."""
        self._cfg.yt_playlist = copy.deepcopy(self._playlist_data)
        save_config(self._cfg)

    def _append_playlist_item(self, url: str, title: str) -> None:
        self._playlist_data.append({"title": title, "url": url})
        self._refresh_playlist_listbox()
        self._persist_playlist_quiet()
        self._log(f"Dodano do listy: {title}")

    def _show_add_playlist_dialog(self) -> None:
        dlg = tk.Toplevel(self.root)
        dlg.title("Dodaj utwór do playlisty")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(True, False)

        f = ttk.Frame(dlg, padding=12)
        f.pack(fill=tk.BOTH, expand=True)

        ttk.Label(f, text="URL (najpierw — YouTube lub bezpośredni link):").grid(row=0, column=0, sticky=tk.W)
        e_url = ttk.Entry(f, width=58)
        e_url.grid(row=1, column=0, sticky=tk.EW, pady=(0, 10))

        ttk.Label(f, text="Tytuł (opcjonalnie — zostaw puste, użyj „Pobierz tytuł”):").grid(row=2, column=0, sticky=tk.W)
        e_title = ttk.Entry(f, width=58)
        e_title.grid(row=3, column=0, sticky=tk.EW, pady=(0, 8))

        status_lbl = ttk.Label(f, text="", foreground="#666")
        status_lbl.grid(row=5, column=0, sticky=tk.W, pady=(0, 4))

        btn_fetch = ttk.Button(f)

        def do_fetch_title() -> None:
            u = e_url.get().strip()
            if not u.startswith("http"):
                messagebox.showwarning("URL", "Podaj najpierw poprawny adres https://…", parent=dlg)
                return
            self._log("Pobieranie tytułu (w tle, okno się nie zamraża)…")
            status_lbl.configure(text="Pobieranie tytułu…")
            btn_fetch.configure(state=tk.DISABLED)

            def worker() -> None:
                title, err = fetch_title(u)

                def done() -> None:
                    btn_fetch.configure(state=tk.NORMAL)
                    if err:
                        status_lbl.configure(text="")
                        messagebox.showerror("Tytuł", err, parent=dlg)
                        self._log(f"Tytuł: błąd — {err[:120]}")
                    elif title:
                        e_title.delete(0, tk.END)
                        e_title.insert(0, title)
                        status_lbl.configure(text="")
                        disp = title if len(title) <= 72 else title[:69] + "…"
                        self._log(f"Tytuł: {disp}")
                    else:
                        status_lbl.configure(text="")

                self.root.after(0, done)

            threading.Thread(target=worker, daemon=True).start()

        btn_fetch.configure(text="Pobierz tytuł z internetu", command=do_fetch_title)
        btn_fetch.grid(row=4, column=0, sticky=tk.W, pady=(0, 4))

        btn_fr = ttk.Frame(f)
        btn_fr.grid(row=6, column=0, sticky=tk.EW)

        btn_ok = ttk.Button(btn_fr)

        def on_ok() -> None:
            u = e_url.get().strip()
            if not u.startswith("http"):
                messagebox.showwarning("URL", "Podaj pełny URL (https://…)", parent=dlg)
                return
            t = e_title.get().strip()
            if t:
                self._append_playlist_item(u, t)
                dlg.destroy()
                return

            # Dodaj od razu (bez czekania), a tytuł pobierz i podmień w tle.
            placeholder = "Pobieranie tytułu..."
            self._append_playlist_item(u, placeholder)
            new_idx = len(self._playlist_data) - 1
            self._log("Dodano od razu; tytuł zostanie uzupełniony w tle.")
            dlg.destroy()

            def worker() -> None:
                title, err = fetch_title(u)

                def done() -> None:
                    if new_idx >= len(self._playlist_data):
                        return
                    if title:
                        self._playlist_data[new_idx]["title"] = title
                        self._refresh_playlist_listbox()
                        self._persist_playlist_quiet()
                        self._log(f"Tytuł uzupełniony: {title[:72]}")
                    else:
                        self._playlist_data[new_idx]["title"] = "Bez tytułu"
                        self._refresh_playlist_listbox()
                        self._persist_playlist_quiet()
                        self._log(f"Tytuł: nie udało się pobrać ({(err or 'brak')[:120]})")

                self.root.after(0, done)

            threading.Thread(target=worker, daemon=True).start()

        btn_ok.configure(text="OK", command=on_ok)
        btn_ok.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_fr, text="Anuluj", command=dlg.destroy).pack(side=tk.LEFT)

        f.columnconfigure(0, weight=1)
        e_url.focus_set()
        dlg.geometry("+100+100")

    def _playlist_remove(self) -> None:
        sel = self.playlist.curselection()
        if not sel:
            messagebox.showinfo("Playlista", "Zaznacz pozycję na liście.")
            return
        i = sel[0]
        if 0 <= i < len(self._playlist_data):
            del self._playlist_data[i]
        self._refresh_playlist_listbox()
        self._persist_playlist_quiet()

    def _playlist_save(self) -> None:
        if not self._playlist_data:
            messagebox.showwarning("Playlista", "Lista jest pusta.")
            return
        self._cfg.yt_playlist = copy.deepcopy(self._playlist_data)
        save_config(self._cfg)
        self._log("Zapisano playlistę.")
        messagebox.showinfo("Playlista", "Zapisano playlistę do config.json.")

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

        win_fr = ttk.LabelFrame(inner, text="Okno aplikacji")
        win_fr.pack(fill=tk.X, padx=4, pady=6)
        self.lbl_win_current = ttk.Label(
            win_fr,
            text="Aktualny rozmiar okna: — (zmień rozmiar okna, wartość się zaktualizuje)",
        )
        self.lbl_win_current.pack(anchor=tk.W, padx=8, pady=4)
        self.lbl_win_saved = ttk.Label(
            win_fr,
            text=(
                f"Ostatnio zapisane w config.json: {self._cfg.window_width} × "
                f"{self._cfg.window_height} px — powiększ okno i kliknij „Zapisz ustawienia”, żeby zapamiętać."
            ),
            wraplength=520,
            justify=tk.LEFT,
        )
        self.lbl_win_saved.pack(anchor=tk.W, padx=8, pady=(0, 8))

        cmd_fr = ttk.LabelFrame(inner, text="Instalacja VLC / yt-dlp — zaznacz myszą, Ctrl+C lub PPM → Kopiuj")
        cmd_fr.pack(fill=tk.X, padx=4, pady=6)
        self.install_cmds_text = tk.Text(cmd_fr, height=10, wrap=tk.WORD, font=("Courier", 9))
        self.install_cmds_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self._wire_copyable_text(self.install_cmds_text, "install_cmds")
        self._set_notes_text(self.install_cmds_text, install_hints_text())
        ttk.Button(
            cmd_fr,
            text="Kopiuj całą instalację do schowka",
            command=lambda: self._copy_text_all(self.install_cmds_text),
        ).pack(pady=(0, 6))

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
        ttk.Label(ann_fr, text="Koniec dnia (endDay):").grid(row=3, column=0, sticky=tk.W, padx=4)
        self.path_end_day = ttk.Entry(ann_fr)
        self.path_end_day.insert(0, self._cfg.announcement_end_day)
        self.path_end_day.grid(row=3, column=1, sticky=tk.EW, padx=4)
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
            self.path_end_day,
        )
        self._apply_settings_lock_ui()

    def _build_log_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="Log")
        bar = ttk.Frame(tab)
        bar.pack(fill=tk.X)
        ttk.Button(bar, text="Kopiuj zaznaczenie", command=lambda: self._copy_text_selection(self.log_view)).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(bar, text="Kopiuj cały log", command=lambda: self._copy_text_all(self.log_view)).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(bar, text="Wyczyść log", command=self._log_clear).pack(side=tk.LEFT, padx=12)
        ttk.Label(
            bar,
            text="Tekst jak w notatniku: zaznacz myszą, Ctrl+C lub PPM",
        ).pack(side=tk.RIGHT, padx=6)

        self.log_view = tk.Text(tab, wrap=tk.WORD, height=22, font=("Courier", 9))
        self.log_view.pack(fill=tk.BOTH, expand=True, pady=4)
        self._wire_copyable_text(self.log_view, "log")

    def _log_clear(self) -> None:
        self.log_view.delete("1.0", tk.END)

    def _on_close(self) -> None:
        """Zapisz kluczowe dane nawet gdy user nie kliknął „Zapisz ustawienia”."""
        try:
            self._cfg.window_width = self.root.winfo_width()
            self._cfg.window_height = self.root.winfo_height()
            self._cfg.yt_playlist = copy.deepcopy(self._playlist_data)
            self._read_slots_from_ui()
            self._cfg.seance_slots = slots_to_json(self._slots)
            save_config(self._cfg)
        except Exception:
            pass
        try:
            self._ann_player.stop()
        except Exception:
            pass
        self.root.destroy()

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
        self._cfg.announcement_end_day = self.path_end_day.get().strip()
        self._cfg.window_width = self.root.winfo_width()
        self._cfg.window_height = self.root.winfo_height()
        self._cfg.yt_playlist = copy.deepcopy(self._playlist_data)
        self._cfg.seance_slots = slots_to_json(self._slots)
        save_config(self._cfg)
        self.lbl_win_saved.configure(
            text=(
                f"Ostatnio zapisane w config.json: {self._cfg.window_width} × "
                f"{self._cfg.window_height} px — następny start użyje tego rozmiaru."
            )
        )
        self._log("Zapisano config.json.")
        messagebox.showinfo("Zapis", "Zapisano ustawienia.")

    def _refresh_status_loop(self) -> None:
        # Czytaj bieżące wartości z UI seansów, żeby status i odliczanie
        # reagowały natychmiast po zmianie godzin/trybu.
        self._read_slots_from_ui()
        self._check_and_trigger_announcements()
        self._refresh_status()
        self._update_active_countdown()
        self.root.after(1500, self._refresh_status_loop)

    def _check_and_trigger_announcements(self) -> None:
        """Fade kończy się równo na starcie zapowiedzi (min przed seansem)."""
        now = dt.datetime.now()
        day_key = now.strftime("%Y-%m-%d")
        now_s = now.hour * 3600 + now.minute * 60 + now.second
        pre_min = max(0, int(self._cfg.announcement_minutes_before))
        fade_sec = max(1, int(max(0, int(self._cfg.fade_out_ms)) / 1000))

        # Ogranicz pamięć kluczy do bieżącego dnia.
        self._ann_fired_keys = {k for k in self._ann_fired_keys if k.startswith(day_key + "|")}
        self._ann_prepared_keys = {k for k in self._ann_prepared_keys if k.startswith(day_key + "|")}

        for s in self._slots:
            if not s.enabled:
                continue
            seans_s = s.hour * 3600 + s.minute * 60
            ann_s = seans_s - pre_min * 60
            if ann_s < 0:
                ann_s += 24 * 3600
            key = f"{day_key}|{s.hour:02d}:{s.minute:02d}|{s.mode}"
            if key in self._ann_fired_keys:
                continue

            # Różnice kołowe (24h), odporne na przejście przez północ.
            until_ann_s = (ann_s - now_s) % (24 * 3600)  # ile sekund do zapowiedzi
            since_ann_s = (now_s - ann_s) % (24 * 3600)  # ile sekund od zapowiedzi
            # Przygotowanie fade rozpoczynamy w ostatnich ~fade_sec sekundach.
            in_prepare_window = 0 < until_ann_s <= (fade_sec + 2)
            # Start zapowiedzi ma tolerancję 10s (tick co 1.5s + jitter).
            in_start_window = since_ann_s <= 10
            if self._announcement_active:
                continue

            mode = s.mode if s.mode in ("teatr", "finska") else ""
            if mode == "":
                self._ann_fired_keys.add(key)
                self._log(
                    f"Zapowiedź dla seansu {s.hour:02d}:{s.minute:02d} pominięta: "
                    "nie wybrano trybu (Teatr/Fińska)."
                )
                continue
            path = (self._cfg.announcement_teatr if mode == "teatr" else self._cfg.announcement_finska).strip()
            if not path:
                self._ann_fired_keys.add(key)
                self._log(
                    f"Zapowiedź {mode} dla seansu {s.hour:02d}:{s.minute:02d} pominięta: "
                    "brak ścieżki pliku w Ustawieniach."
                )
                continue
            if not self._player.available():
                self._ann_fired_keys.add(key)
                self._log("Zapowiedź pominięta: brak VLC (player główny).")
                continue

            if in_prepare_window and key not in self._ann_prepared_keys:
                self._ann_prepared_keys.add(key)
                self._prepare_announcement_duck(key, mode, s.hour, s.minute, ann_s)
                continue

            if in_start_window:
                self._start_announcement(key, path, mode, s.hour, s.minute, pre_min)

    def _prepare_announcement_duck(self, key: str, mode: str, h: int, m: int, ann_s: int) -> None:
        """Przygotuj fade tak, aby zapowiedź ruszyła dokładnie o godzinie zapowiedzi."""
        now = dt.datetime.now()
        now_s = now.hour * 3600 + now.minute * 60 + now.second
        remaining_sec = ann_s - now_s
        if remaining_sec < 0:
            remaining_sec += 24 * 3600
        remaining_ms = max(150, remaining_sec * 1000 - int(now.microsecond / 1000))
        try:
            base_vol = max(0, min(100, int(self._player.get_volume())))
        except Exception:
            base_vol = 70
        steps = max(1, min(32, int(remaining_ms / 120)))
        step_delay = max(20, int(remaining_ms / steps))
        self._yt_volume_before_announcement = base_vol

        self._log(
            f"Przygotowanie zapowiedzi {mode} {h:02d}:{m:02d}: "
            f"duck YT {base_vol}% -> 0% przez {remaining_ms}ms, start zapowiedzi równo o czasie zapowiedzi."
        )

        def after_duck() -> None:
            self._player.set_volume(0)

        if steps <= 1 or base_vol <= 0:
            self._player.set_volume(0)
            self.root.after(20, after_duck)
            return

        def step(i: int) -> None:
            ratio = max(0.0, 1.0 - (i / steps))
            self._player.set_volume(int(base_vol * ratio))
            if i >= steps:
                after_duck()
            else:
                self.root.after(step_delay, lambda: step(i + 1))

        step(1)

    def _start_announcement(self, key: str, path: str, mode: str, h: int, m: int, pre_min: int) -> None:
        if key in self._ann_fired_keys:
            return
        self._announcement_active = True
        ok_play, err_play = self._ann_player.play_file(path)
        if not ok_play:
            self._log(f"Zapowiedź {mode} {h:02d}:{m:02d} play() błąd: {err_play}")
            self._finish_announcement(key, mode, h, m, failed=True)
            return
        self._log(
            f"START zapowiedzi {mode} dla seansu {h:02d}:{m:02d} "
            f"({pre_min} min przed seansem, osobny player ffplay)."
        )
        self.root.after(250, lambda: self._watch_announcement_end(key, mode, h, m))

    def _watch_announcement_end(self, key: str, mode: str, h: int, m: int) -> None:
        if self._ann_player.is_playing():
            self.root.after(250, lambda: self._watch_announcement_end(key, mode, h, m))
            return
        self._finish_announcement(key, mode, h, m, failed=False)

    def _finish_announcement(self, key: str, mode: str, h: int, m: int, failed: bool) -> None:
        self._announcement_active = False
        self._ann_fired_keys.add(key)
        self._player.set_volume(self._yt_volume_before_announcement or 70)
        if failed:
            self._log(f"Zapowiedź {mode} {h:02d}:{m:02d} nie wystartowała; YT przywrócone.")
        else:
            self._log(f"KONIEC zapowiedzi {mode} {h:02d}:{m:02d}; YT wraca od razu.")

    def _refresh_status(self) -> None:
        body = self._schedule.next_events_description()
        if body != self._last_status_body:
            self._last_status_body = body
            self._set_notes_text(self.status_box, body)

    def _tick_transport(self) -> None:
        next_ms = 1200
        if self._player.available() and not self._slider_sync:
            pos = self._player.get_position()
            self.var_pos.set(int(pos * 1000))
            vol = self._player.get_volume()
            self.var_vol.set(vol)
            cur_ms = self._player.get_time_ms()
            len_ms = self._player.get_length_ms()
            self.lbl_time.configure(
                text=f"Czas: {self._fmt_ms(cur_ms)} / {self._fmt_ms(len_ms)}"
            )
            if self._player.is_playing():
                next_ms = 500
            if (
                not self._dbg_first_sec_logged
                and self._dbg_req_ms > 0
                and self._dbg_play_cmd_ms > 0
                and cur_ms >= 1000
            ):
                now_ms = int(self.root.tk.call("clock", "milliseconds"))
                total = now_ms - self._dbg_req_ms
                to_stream = self._dbg_stream_ms - self._dbg_req_ms if self._dbg_stream_ms else -1
                to_play = self._dbg_play_cmd_ms - self._dbg_req_ms
                after_play = now_ms - self._dbg_play_cmd_ms
                self._dbg_first_sec_logged = True
                self._log(
                    "DEBUG startu: "
                    f"stream={to_stream}ms, play_cmd={to_play}ms, "
                    f"1s_audio_po_play={after_play}ms, total_do_1s={total}ms "
                    f"[{self._dbg_label[:48]}]"
                )
        self.root.after(next_ms, self._tick_transport)

    def _fmt_ms(self, ms: int) -> str:
        if ms is None or ms < 0:
            return "--:--"
        sec = ms // 1000
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

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

    def _on_play(self, _event: tk.Event | None = None) -> None:
        now_ms = int(self.root.tk.call("clock", "milliseconds"))
        if self._play_busy:
            # Jeśli resolver utknął, odblokuj po czasie i pozwól na ponowną próbę.
            if self._play_busy_since_ms and (now_ms - self._play_busy_since_ms) > 30000:
                self._play_busy = False
                self._play_busy_since_ms = 0
                self._log("Poprzednia próba przekroczyła timeout (30s). Odblokowano ponowną próbę.")
            elif (now_ms - self._last_busy_log_ms) > 1500:
                self._last_busy_log_ms = now_ms
                self._log("Odtwarzanie już się przygotowuje — poczekaj chwilę.")
            return
        sel = self.playlist.curselection()
        if not sel:
            self._log("Wybierz pozycję na liście (lub kliknij dwukrotnie).")
            return
        idx = sel[0]
        entry = self._playlist_data[idx] if idx < len(self._playlist_data) else {}
        url = (entry.get("url") or "").strip()
        if not url.startswith("http"):
            self._log("Brak URL — dodaj wpis z https://")
            return
        if not self._player.available():
            msg = self._player.init_error() or "Brak VLC."
            self._log(msg)
            messagebox.showerror(
                "Brak VLC",
                msg + "\n\nPełna lista poleceń jest w zakładce Ustawienia (pole do skopiowania) i w Logu.",
            )
            return

        label = (entry.get("title") or url)[:80]
        self._dbg_req_ms = now_ms
        self._dbg_stream_ms = 0
        self._dbg_play_cmd_ms = 0
        self._dbg_first_sec_logged = False
        self._dbg_label = label
        self._play_busy = True
        self._play_busy_since_ms = now_ms
        self._log(f"Szukam strumienia dla: {label}… (nie blokuje okna)")

        def watchdog() -> None:
            if not self._play_busy:
                return
            self._play_busy = False
            self._play_busy_since_ms = 0
            self._log("Timeout pobierania strumienia (30s). Spróbuj ponownie.")

        self.root.after(30000, watchdog)

        def worker() -> None:
            stream: str | None = None
            err: str | None = None
            try:
                stream, err = get_audio_stream_url(url)
            except Exception as e:
                err = f"Wyjątek podczas pobierania strumienia: {e}"

            def finish() -> None:
                self._play_busy = False
                self._play_busy_since_ms = 0
                if not stream:
                    self._log(f"Błąd strumienia: {err or 'nieznany'}")
                    eb = err or "Nie udało się pobrać adresu audio (ffmpeg / yt-dlp / sieć?)."
                    messagebox.showerror("Odtwarzacz", eb + "\n\n(Szczegóły są w zakładce Log — można skopiować.)")
                    return
                self._dbg_stream_ms = int(self.root.tk.call("clock", "milliseconds"))
                self._log(f"DEBUG: stream gotowy po {self._dbg_stream_ms - self._dbg_req_ms}ms")
                ok_play, err2 = self._player.load_stream_url(stream)
                if not ok_play:
                    self._log(f"VLC nie załadował strumienia: {err2}")
                    messagebox.showerror("VLC", err2 or "Błąd odtwarzacza")
                    return
                ok_start, err_start = self._player.play()
                if not ok_start:
                    self._log(f"VLC play() błąd: {err_start}")
                    messagebox.showerror(
                        "VLC",
                        (err_start or "Nie udało się uruchomić odtwarzania.")
                        + "\n\nSprawdź wyjście audio systemu (HDMI/Jack) i pakiety VLC.",
                    )
                    return
                self._dbg_play_cmd_ms = int(self.root.tk.call("clock", "milliseconds"))
                self._log(f"DEBUG: play() wywołane po {self._dbg_play_cmd_ms - self._dbg_req_ms}ms")
                self._log(f"Odtwarzanie: {label}")

                def post_check() -> None:
                    dbg = self._player.debug_state()
                    self._log(f"VLC debug po starcie: {dbg}")

                self.root.after(2500, post_check)

            self.root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def _on_pause(self) -> None:
        self._player.pause()

    def _log(self, msg: str) -> None:
        self.log_view.insert(tk.END, msg + "\n")
        self.log_view.see(tk.END)
