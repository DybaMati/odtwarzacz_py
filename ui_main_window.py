"""Główne okno: zakładka Odtwarzacz+seanse, Ustawienia, Log."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig, load_config, save_config
from player_engine import PlayerEngine
from schedule_engine import ScheduleEngine, default_slots_thirteen_to_twentytwo
from security import hash_pin, verify_pin


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._cfg = load_config()
        self._slots = default_slots_thirteen_to_twentytwo()
        self._schedule = ScheduleEngine(lambda: self._cfg, self._slots)
        self._player = PlayerEngine()
        self._settings_unlocked = not bool(self._cfg.pin_hash_hex)

        self.setWindowTitle("Odtwarzacz — seanse")
        w = max(600, self._cfg.window_width)
        h = max(520, self._cfg.window_height)
        self.resize(w, h)
        self.setMinimumSize(700, 560)

        tabs = QTabWidget()
        tabs.addTab(self._build_player_tab(), "Odtwarzacz i seanse")
        tabs.addTab(self._build_settings_tab(), "Ustawienia")
        tabs.addTab(self._build_log_tab(), "Log")

        self.setCentralWidget(tabs)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._tick_transport)
        self._poll_timer.start(400)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(1000)

        self._log("Start aplikacji.")
        if not self._player.available():
            self._log("Ostrzeżenie: brak python-vlc / libvlc — transport będzie pusty.")

    def _build_player_tab(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)

        left = QVBoxLayout()
        self.playlist = QListWidget()
        self._fill_playlist_from_config()
        left.addWidget(QLabel("Lista odtwarzania (tytuł + URL YouTube / plik — docelowo)"))
        left.addWidget(self.playlist)

        transport = QHBoxLayout()
        self.btn_play = QPushButton("Odtwarzaj")
        self.btn_pause = QPushButton("Pauza")
        self.btn_play.clicked.connect(self._on_play)
        self.btn_pause.clicked.connect(self._on_pause)
        transport.addWidget(self.btn_play)
        transport.addWidget(self.btn_pause)
        left.addLayout(transport)

        self.slider_pos = QSlider(Qt.Orientation.Horizontal)
        self.slider_pos.setRange(0, 1000)
        self.slider_pos.sliderMoved.connect(self._on_seek)
        left.addWidget(QLabel("Pozycja"))
        left.addWidget(self.slider_pos)

        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(70)
        self.slider_vol.valueChanged.connect(self._on_volume)
        left.addWidget(QLabel("Głośność"))
        left.addWidget(self.slider_vol)

        right = QVBoxLayout()
        right.addWidget(QLabel("Harmonogram seansów (domyślnie 13:00–22:00)"))
        self.seance_list = QTextEdit()
        self.seance_list.setReadOnly(True)
        self.seance_list.setMaximumHeight(160)
        self._refresh_seance_text()
        right.addWidget(self.seance_list)

        self.status_box = QTextEdit()
        self.status_box.setReadOnly(True)
        right.addWidget(QLabel("Co się dzieje / następne kroki"))
        right.addWidget(self.status_box)

        layout.addLayout(left, 3)
        layout.addLayout(right, 2)
        return w

    def _build_settings_tab(self) -> QWidget:
        scroll = QWidget()
        outer = QVBoxLayout(scroll)

        pin_box = QGroupBox("Dostęp do ustawień (PIN)")
        pin_form = QFormLayout(pin_box)
        self.pin_input = QLineEdit()
        self.pin_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin_new = QLineEdit()
        self.pin_new.setEchoMode(QLineEdit.EchoMode.Password)
        btn_unlock = QPushButton("Odblokuj / ustaw PIN")
        btn_unlock.clicked.connect(self._on_pin_action)
        pin_form.addRow("PIN:", self.pin_input)
        pin_form.addRow("Nowy PIN (gdy pierwszy raz):", self.pin_new)
        pin_form.addRow(btn_unlock)
        outer.addWidget(pin_box)

        net = QGroupBox("Sieć")
        nf = QFormLayout(net)
        self.ws_alarm = QLineEdit(self._cfg.ws_alarm_url)
        self.ws_player = QLineEdit(self._cfg.ws_player_url)
        nf.addRow("WebSocket alarmy:", self.ws_alarm)
        nf.addRow("WebSocket status playera:", self.ws_player)
        outer.addWidget(net)

        times = QGroupBox("Czasy automatyki (minuty)")
        tf = QFormLayout(times)
        self.sp_query = QSpinBox()
        self.sp_query.setRange(0, 180)
        self.sp_query.setValue(self._cfg.query_ws_minutes)
        self.sp_ann = QSpinBox()
        self.sp_ann.setRange(0, 180)
        self.sp_ann.setValue(self._cfg.announcement_minutes_before)
        self.sp_resume = QSpinBox()
        self.sp_resume.setRange(0, 180)
        self.sp_resume.setValue(self._cfg.resume_minutes_after_start)
        tf.addRow("Pytanie WS — min przed seansem:", self.sp_query)
        tf.addRow("Zapowiedź — min przed seansem:", self.sp_ann)
        tf.addRow("Podgłośnienie po seansie — min po godzinie seansu:", self.sp_resume)
        outer.addWidget(times)

        fade = QGroupBox("Fade i duck")
        ff = QFormLayout(fade)
        self.sp_fo = QSpinBox()
        self.sp_fo.setRange(500, 120000)
        self.sp_fo.setSingleStep(500)
        self.sp_fo.setValue(self._cfg.fade_out_ms)
        self.sp_fi = QSpinBox()
        self.sp_fi.setRange(500, 300000)
        self.sp_fi.setSingleStep(500)
        self.sp_fi.setValue(self._cfg.fade_in_ms)
        self.sp_duck_sec = QSpinBox()
        self.sp_duck_sec.setRange(5, 300)
        self.sp_duck_sec.setValue(self._cfg.pre_seance_duck_seconds)
        ff.addRow("Fade-out (ms):", self.sp_fo)
        ff.addRow("Fade-in (ms):", self.sp_fi)
        ff.addRow("Okno duck przed seansem (s):", self.sp_duck_sec)
        outer.addWidget(fade)

        ann = QGroupBox("Pliki zapowiedzi (ścieżki lokalne)")
        af = QFormLayout(ann)
        self.path_teatr = QLineEdit(self._cfg.announcement_teatr)
        self.path_finska = QLineEdit(self._cfg.announcement_finska)
        self.path_default = QLineEdit(self._cfg.announcement_default)
        af.addRow("Teatr:", self.path_teatr)
        af.addRow("Fińska:", self.path_finska)
        af.addRow("Domyślna:", self.path_default)
        outer.addWidget(ann)

        btn_save = QPushButton("Zapisz ustawienia")
        btn_save.clicked.connect(self._save_settings)
        outer.addWidget(btn_save)

        outer.addStretch()
        self._apply_settings_lock_ui()
        return scroll

    def _build_log_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        lay.addWidget(self.log_view)
        return w

    def _apply_settings_lock_ui(self) -> None:
        locked = not self._settings_unlocked
        for w in (
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
        ):
            w.setEnabled(not locked)

    def _on_pin_action(self) -> None:
        pin = self.pin_input.text()
        new_pin = self.pin_new.text()
        if not self._cfg.pin_hash_hex:
            if len(new_pin) < 4:
                QMessageBox.warning(self, "PIN", "Ustaw nowy PIN (min. 4 znaki).")
                return
            self._cfg.pin_hash_hex = hash_pin(new_pin)
            save_config(self._cfg)
            self._settings_unlocked = True
            self._apply_settings_lock_ui()
            self._log("Ustawiono PIN.")
            QMessageBox.information(self, "PIN", "PIN ustawiony. Ustawienia odblokowane.")
            return
        if verify_pin(pin, self._cfg.pin_hash_hex):
            self._settings_unlocked = True
            self._apply_settings_lock_ui()
            self._log("Ustawienia odblokowane.")
        else:
            QMessageBox.warning(self, "PIN", "Nieprawidłowy PIN.")

    def _save_settings(self) -> None:
        if not self._settings_unlocked:
            QMessageBox.warning(self, "PIN", "Najpierw odblokuj ustawienia.")
            return
        self._cfg.ws_alarm_url = self.ws_alarm.text().strip()
        self._cfg.ws_player_url = self.ws_player.text().strip()
        self._cfg.query_ws_minutes = self.sp_query.value()
        self._cfg.announcement_minutes_before = self.sp_ann.value()
        self._cfg.resume_minutes_after_start = self.sp_resume.value()
        self._cfg.fade_out_ms = self.sp_fo.value()
        self._cfg.fade_in_ms = self.sp_fi.value()
        self._cfg.pre_seance_duck_seconds = self.sp_duck_sec.value()
        self._cfg.announcement_teatr = self.path_teatr.text().strip()
        self._cfg.announcement_finska = self.path_finska.text().strip()
        self._cfg.announcement_default = self.path_default.text().strip()
        self._cfg.window_width = self.width()
        self._cfg.window_height = self.height()
        save_config(self._cfg)
        self._refresh_seance_text()
        self._log("Zapisano config.json.")
        QMessageBox.information(self, "Zapis", "Zapisano ustawienia.")

    def _fill_playlist_from_config(self) -> None:
        self.playlist.clear()
        for item in self._cfg.yt_playlist:
            title = item.get("title", "—")
            self.playlist.addItem(title)

    def _refresh_seance_text(self) -> None:
        lines = []
        for s in self._slots:
            if not s.enabled:
                continue
            lines.append(f"{s.hour:02d}:{s.minute:02d}  ({s.mode})")
        self.seance_list.setPlainText("\n".join(lines) if lines else "(brak)")

    def _refresh_status(self) -> None:
        self.status_box.setPlainText(self._schedule.next_events_description())

    def _tick_transport(self) -> None:
        if not self._player.available():
            return
        pos = self._player.get_position()
        self.slider_pos.blockSignals(True)
        self.slider_pos.setValue(int(pos * 1000))
        self.slider_pos.blockSignals(False)
        vol = self._player.get_volume()
        self.slider_vol.blockSignals(True)
        self.slider_vol.setValue(vol)
        self.slider_vol.blockSignals(False)

    def _on_play(self) -> None:
        item = self.playlist.currentItem()
        if not item:
            self._log("Wybierz pozycję na liście.")
            return
        idx = self.playlist.row(item)
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

    def _on_seek(self, v: int) -> None:
        self._player.set_position(v / 1000.0)

    def _on_volume(self, v: int) -> None:
        self._player.set_volume(v)

    def _log(self, msg: str) -> None:
        self.log_view.append(msg)
