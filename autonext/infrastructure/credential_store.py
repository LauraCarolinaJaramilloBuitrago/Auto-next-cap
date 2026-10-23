"""Credenciales de los sitios: fuera de perfiles.json y fuera de git.

Primero el almacen del sistema (Administrador de credenciales en Windows, llavero de
GNOME/KDE en Linux). Si no hay, un archivo local ignorado por git con permisos 600.
"""
from __future__ import annotations

import json
import os
import threading

from ..domain.ports import CredentialPort

SERVICE = "autonext"

try:
    import keyring
    from keyring.errors import KeyringError
except ImportError:  # sin la libreria: solo archivo local
    keyring = None
    KeyringError = Exception


class CredentialStore(CredentialPort):
    def __init__(self, fallback_path: str):
        self.path = fallback_path
        self._lock = threading.Lock()
        self.backend = "archivo local" if keyring is None else "almacen del sistema"

    # ---------- archivo local ----------
    def _read(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: dict) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        try:
            os.chmod(self.path, 0o600)  # solo el usuario (en Windows no aplica)
        except OSError:
            pass

    # ---------- API ----------
    def get(self, profile: str) -> tuple[str, str] | None:
        with self._lock:
            user = self._read().get(profile, {}).get("user")
            if not user:
                return None
            if keyring is not None:
                try:
                    pwd = keyring.get_password(SERVICE, f"{profile}:{user}")
                    if pwd:
                        return user, pwd
                except KeyringError:
                    pass
            pwd = self._read().get(profile, {}).get("password")
            return (user, pwd) if pwd else None

    def user(self, profile: str) -> str:
        with self._lock:
            return self._read().get(profile, {}).get("user", "")

    def set(self, profile: str, user: str, password: str) -> str:
        """Guarda y devuelve donde quedo la contraseña."""
        with self._lock:
            data = self._read()
            entry = {"user": user}
            stored = "archivo local"
            if keyring is not None:
                try:
                    keyring.set_password(SERVICE, f"{profile}:{user}", password)
                    stored = "almacen del sistema"
                except KeyringError:
                    pass  # sin llavero (Linux sin escritorio): archivo local
            if stored == "archivo local":
                entry["password"] = password
            data[profile] = entry
            self._write(data)
            self.backend = stored
            return stored

    def delete(self, profile: str) -> None:
        with self._lock:
            data = self._read()
            user = data.pop(profile, {}).get("user")
            if user and keyring is not None:
                try:
                    keyring.delete_password(SERVICE, f"{profile}:{user}")
                except Exception:  # noqa: BLE001  ya no estaba
                    pass
            self._write(data)
