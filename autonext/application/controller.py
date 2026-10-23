"""Fachada de aplicacion: una sola instancia que comparten el panel de escritorio y el servidor web."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import asdict
from typing import Callable
from urllib.parse import urlparse

from ..domain import events as ev
from ..domain.commands import Command
from ..domain.ports import BrowserPort, CredentialPort, ProfileRepository
from .autonext_service import AutoNextService

IDLE_STATUS = {"mode": "idle", "position": 0, "duration": 0, "paused": True, "episode": 0,
               "server": "-", "url": "", "title": "", "ranking": [], "limit_enabled": False, "limit": 0}


class AppController:
    def __init__(self, repo: ProfileRepository, browser_factory: Callable[[], BrowserPort],
                 credentials: CredentialPort | None = None):
        self.repo = repo
        self.credentials = credentials
        self.browser_factory = browser_factory
        self.service: AutoNextService | None = None
        self._subs: list[Callable[[ev.DomainEvent], None]] = []
        self._lock = threading.Lock()
        self.status = dict(IDLE_STATUS)
        self.logs: deque[dict] = deque(maxlen=300)
        self._log_id = 0
        self.results: list[dict] = []
        self.episodes: list[dict] = []
        self.seasons: list[str] = []
        self.servers: list[str] = []
        self.server_url = ""  # la pone el servidor web al arrancar

    # ---------- eventos ----------
    def subscribe(self, cb: Callable[[ev.DomainEvent], None]):
        self._subs.append(cb)

    def _on_event(self, e: ev.DomainEvent):
        with self._lock:
            if e.kind == "status":
                self.status = {**IDLE_STATUS, **e.data, "running": True}
            elif e.kind == "results":
                self.results = e.data["results"]
            elif e.kind == "episodes":
                self.episodes = e.data["episodes"]
            elif e.kind == "seasons":
                self.seasons = e.data["seasons"]
            elif e.kind == "servers":
                self.servers = e.data["servers"]
            if e.kind != "status" and e.message:
                self._log_id += 1
                self.logs.append({"id": self._log_id, "kind": e.kind, "message": e.message, "at": e.at})
            if e.data.get("finished"):
                self.service = None
                self.status = dict(IDLE_STATUS)
        for cb in list(self._subs):
            try:
                cb(e)
            except Exception:
                pass

    # ---------- ciclo de vida ----------
    @property
    def running(self) -> bool:
        return self.service is not None

    def active_profile(self):
        return self.repo.all()[self.repo.active_name()]

    def start(self, profile_name: str | None = None, url: str | None = None) -> None:
        if self.running:
            return
        profiles = self.repo.all()
        profile = profiles[profile_name] if profile_name in profiles else self.active_profile()
        self.repo.save(profile)  # pasa a ser el activo
        self.service = AutoNextService(profile, self.browser_factory(), self.repo, self._on_event, start_url=url,
                                       credentials=self.credentials)
        threading.Thread(target=self.service.run, daemon=True).start()

    def stop(self) -> None:
        if self.service:
            self.service.stop()

    def command(self, name: str, **args) -> None:
        cmd = Command(name, args)
        if not self.running:
            # Buscar o abrir sin sesion: arranca Brave sin reproducir nada
            if name == "open":
                self.start(url=args["url"])
                return
            if name == "home":
                p = self.active_profile()
                u = urlparse(p.url)
                self.start(url=p.home_url or f"{u.scheme}://{u.netloc}/")
            elif name == "search":
                p = self.active_profile()
                u = urlparse(p.url)
                self.start(url=f"{u.scheme}://{u.netloc}/")
            else:
                return
        self.service.send(cmd)

    # ---------- consultas ----------
    def state(self, since: int = 0) -> dict:
        with self._lock:
            profiles = self.repo.all()
            active = self.repo.active_name()
            progress = {n: (asdict(p) if (p := self.repo.progress(n)) else None) for n in profiles}
            p = profiles[active]
            return {
                "running": self.running,
                "status": self.status,
                "logs": [l for l in self.logs if l["id"] > since],
                "results": self.results,
                "episodes": self.episodes,
                "seasons": self.seasons,
                "servers": self.servers,
                "profiles": list(profiles),
                "active": active,
                "progress": progress,
                "limit": {"enabled": p.episode_limit_enabled, "count": p.episode_limit},
                "quality": p.max_quality,
                "account": self._account_info(active),
                "language": p.preferred_language,
                "server_url": self.server_url,
                "now": time.time(),
            }

    def set_active(self, name: str) -> None:
        if not self.running and name in self.repo.all():
            self.repo.save(self.repo.all()[name])

    # ---------- cuentas (la contraseña entra pero nunca sale) ----------
    def _account_info(self, profile: str) -> dict:
        user = self.credentials.user(profile) if self.credentials else ""
        if not user:
            return {"saved": False, "user": ""}
        name, _, domain = user.partition("@")
        return {"saved": True, "user": name[:2] + "***" + ("@" + domain if domain else "")}

    def set_account(self, profile: str, user: str, password: str) -> str:
        if not self.credentials:
            raise ValueError("Sin almacen de credenciales")
        if profile not in self.repo.all():
            raise ValueError("Perfil desconocido")
        if not user.strip() or not password:
            raise ValueError("Falta usuario o contraseña")
        return self.credentials.set(profile, user.strip(), password)

    def delete_account(self, profile: str) -> None:
        if self.credentials and profile in self.repo.all():
            self.credentials.delete(profile)

    def set_quality(self, enabled: bool) -> None:
        p = self.active_profile()
        p.max_quality = bool(enabled)
        self.repo.save(p)
        if self.running:
            self.service.send(Command("set_quality", {"enabled": p.max_quality}))

    def set_limit(self, enabled: bool, count: int) -> None:
        p = self.active_profile()
        p.episode_limit_enabled, p.episode_limit = enabled, int(count)
        self.repo.save(p)
        if self.running:
            self.service.send(Command("set_limit", {"enabled": enabled, "count": count}))
