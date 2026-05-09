"""Lekki monitor połączeń WebSocket (thread + asyncio)."""

from __future__ import annotations

import asyncio
import threading
from typing import Callable

import websockets


StatusCallback = Callable[[str, str], None]
MessageCallback = Callable[[str], None]

class WsMonitor:
    def __init__(
        self,
        name: str,
        url: str,
        on_status: StatusCallback,
        on_message: MessageCallback | None = None,
    ) -> None:
        self.name = name
        self.url = url
        self._on_status = on_status
        self._on_message = on_message
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run_thread, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def update_url(self, url: str) -> None:
        self.url = url.strip()

    def _run_thread(self) -> None:
        asyncio.run(self._run_loop())

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            url = (self.url or "").strip()
            if not url:
                self._on_status("off", "brak URL")
                await asyncio.sleep(2.0)
                continue
            self._on_status("connecting", f"łączenie: {url}")
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                ) as ws:
                    self._on_status("connected", "połączono")
                    while not self._stop.is_set():
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            if self._on_message is not None:
                                self._on_message(str(msg))
                        except asyncio.TimeoutError:
                            continue
            except Exception as e:
                self._on_status("error", str(e))
                await asyncio.sleep(3.0)

