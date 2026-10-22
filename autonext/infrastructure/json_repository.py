"""Adaptador ProfileRepository: perfiles, progreso y ajustes en un archivo JSON."""
from __future__ import annotations

import json
import os
import secrets
import threading
from dataclasses import asdict

from ..domain.models import Progress, SiteProfile, default_profiles
from ..domain.ports import ProfileRepository


class JsonProfileRepository(ProfileRepository):
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        data = self._read() if os.path.exists(path) else {"active": "", "settings": {}, "profiles": {}}
        # Perfiles incluidos: se agregan si faltan y se completan campos nuevos sin pisar los del usuario
        for p in default_profiles():
            data["profiles"][p.name] = {**p.to_dict(), **data["profiles"].get(p.name, {})}
        data["active"] = data["active"] or default_profiles()[0].name
        data.setdefault("progress", {})
        settings = data.setdefault("settings", {})
        settings.setdefault("web_port", 8765)
        settings.setdefault("token", secrets.token_urlsafe(6))  # protege el control desde la red
        settings.setdefault("theme", "dark")
        self._write(data)

    def _read(self) -> dict:
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: dict) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    def all(self) -> dict[str, SiteProfile]:
        with self._lock:
            return {k: SiteProfile.from_dict(v) for k, v in self._read()["profiles"].items()}

    def active_name(self) -> str:
        with self._lock:
            return self._read()["active"]

    def save(self, profile: SiteProfile, make_active: bool = True) -> None:
        with self._lock:
            data = self._read()
            old = data["profiles"].get(profile.name, {})
            d = profile.to_dict()
            if not d["health"] and old.get("health"):
                d["health"] = old["health"]  # la UI no conoce la salud mas reciente
            data["profiles"][profile.name] = d
            if make_active:
                data["active"] = profile.name
            self._write(data)

    def save_health(self, profile: SiteProfile) -> None:
        with self._lock:
            data = self._read()
            if profile.name in data["profiles"]:
                data["profiles"][profile.name]["health"] = profile.to_dict()["health"]
                self._write(data)

    def delete(self, name: str) -> None:
        with self._lock:
            data = self._read()
            data["profiles"].pop(name, None)
            data["progress"].pop(name, None)
            if data["active"] == name and data["profiles"]:
                data["active"] = next(iter(data["profiles"]))
            self._write(data)

    def save_progress(self, profile_name: str, progress: Progress) -> None:
        with self._lock:
            data = self._read()
            data["progress"][profile_name] = asdict(progress)
            self._write(data)

    def progress(self, profile_name: str) -> Progress | None:
        with self._lock:
            p = self._read()["progress"].get(profile_name)
            return Progress(**p) if p else None

    def clear_progress(self, profile_name: str) -> None:
        with self._lock:
            data = self._read()
            data["progress"].pop(profile_name, None)
            self._write(data)

    # Ajustes generales de la app (ruta de Brave, puertos, tema, token)
    def settings(self) -> dict:
        with self._lock:
            return self._read().get("settings", {})

    def save_settings(self, settings: dict) -> None:
        with self._lock:
            data = self._read()
            data["settings"] = {**data.get("settings", {}), **settings}
            self._write(data)
