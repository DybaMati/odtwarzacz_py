"""PIN — tylko hash w pliku konfiguracji."""

from __future__ import annotations

import hashlib


def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.strip().encode("utf-8")).hexdigest()


def verify_pin(pin: str, stored_hex: str) -> bool:
    if not stored_hex:
        return True
    return hash_pin(pin) == stored_hex
