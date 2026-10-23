"""Caso de uso: ver capitulos seguidos con failover de servidores, controles remotos y busqueda."""
from __future__ import annotations

import queue
import re
import threading
import time
from dataclasses import asdict
from typing import Callable
from urllib.parse import urlparse

from ..domain import events as ev
from ..domain.commands import Command
from ..domain.models import PlaybackState, Progress, Server, SiteProfile
from ..domain.ports import BrowserPort, CredentialPort, ProfileRepository
from ..domain.services import EpisodeTransitionPolicy, StallDetector

WATCHING, BROWSING = "watching", "browsing"


class AutoNextService:
    def __init__(self, profile: SiteProfile, browser: BrowserPort, repo: ProfileRepository,
                 publish: Callable[[ev.DomainEvent], None], start_url: str | None = None,
                 credentials: CredentialPort | None = None):
        self.profile = profile
        self.credentials = credentials
        self._login_tried = False       # un intento automatico por sesion
        self.browser = browser
        self.repo = repo
        self.publish = publish
        self.start_url = start_url
        self.transition = EpisodeTransitionPolicy(profile.seconds_before_end)
        self.stall = StallDetector(profile.stall_seconds)
        self.current_server: Server | None = None
        self.episodes = 0
        self.mode = WATCHING
        self._commands: queue.Queue[Command] = queue.Queue()
        self._stop = threading.Event()
        self._last_saved = 0.0
        self._user_paused = False       # pausa pedida desde el panel o el celular
        self._paused_since: float | None = None
        self._listed_url = ""           # pagina de la que ya se publicaron los capitulos
        self.want_fullscreen = profile.fullscreen  # el usuario puede quitarla durante la sesion
        self._quality_tries = 0         # intentos de subir calidad en el capitulo actual

    # ---------- entrada desde interfaces (cualquier hilo) ----------
    def stop(self):
        self._stop.set()

    def send(self, cmd: Command):
        self._commands.put(cmd)

    # compatibilidad con botones existentes
    def skip_episode(self):
        self.send(Command("skip"))

    def switch_server(self):
        self.send(Command("switch_server"))

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    # ---------- utilidades ----------
    def _wait(self, s: float):
        end = time.time() + s
        while not self.stopped and time.time() < end:
            self.browser.wait(min(0.5, end - time.time()))

    def _video(self) -> PlaybackState | None:
        return self.browser.video_state(self.profile.min_video_duration)

    def _is_episode(self, url: str) -> bool:
        return bool(re.search(self.profile.episode_pattern, url or ""))

    def _save_progress(self, position: float = 0.0, force: bool = False):
        if not force and time.time() - self._last_saved < 10:
            return
        url = self.browser.current_url()
        if self._is_episode(url):
            self.repo.save_progress(self.profile.name, Progress(url, position, self.browser.page_title()))
            self._last_saved = time.time()

    # ---------- servidores ----------
    def _starts_playing(self) -> bool:
        """Pulsa play hasta que el video real avance o se agote el tiempo del servidor."""
        deadline = time.time() + self.profile.server_timeout
        while not self.stopped and time.time() < deadline:
            st = self._video()
            if st and not st.error and not st.paused:
                # Ya corre: no pulsar play (muchos botones son play/pausa y lo pausarian)
                p1 = st.position
                self._wait(2.5)
                st2 = self._video()
                if st2 and st2.position > p1 + 0.5:
                    return True
                continue
            self.browser.press_play(self.profile)
            self._wait(2)
            self.browser.close_popups(self.profile)
        return False

    def _candidates(self, exclude: Server | None) -> list[Server]:
        ranked = self.profile.ranked_servers()
        if exclude:
            ranked = [s for s in ranked if s != exclude] + [s for s in ranked if s == exclude]
        return ranked

    def ensure_playing(self, resume_at: float | None = None, exclude: Server | None = None,
                       first: Server | None = None) -> bool:
        self.mode = WATCHING
        if self.browser.select_language(self.profile):
            self.publish(ev.info(f"Idioma: {self.profile.preferred_language}"))
        self._quality_tries = 0
        cands = self._candidates(exclude)
        if first:  # elegido a mano: primero ese, luego el resto como respaldo
            cands = [first] + [s for s in cands if s.name != first.name]
        if not cands:
            # Sitio sin servidores configurados: solo intentar play
            return self._starts_playing()
        for server in cands:
            if self.stopped:
                return False
            self.publish(ev.info(f"Probando servidor {server.name}", server=server.name))
            if not self.browser.select_server(server, self.profile):
                self.publish(ev.warn(f"Boton de servidor '{server.name}' no encontrado"))
                continue
            self._wait(2)
            self.browser.close_popups(self.profile)
            if self._starts_playing():
                self.current_server = server
                self.profile.record_success(server)
                self.repo.save_health(self.profile)
                self.publish(ev.ok(f"Servidor {server.name} funcionando", server=server.name))
                self._publish_servers()  # algunos sitios solo listan servidores tras dar play
                if resume_at and resume_at > 5:
                    self.browser.seek(resume_at - 3, self.profile.min_video_duration)
                    self.publish(ev.info(f"Retomando en {fmt(resume_at - 3)}"))
                self._apply_quality()
                if self.want_fullscreen:
                    self.browser.enter_fullscreen()
                self.stall.reset()
                return True
            if self.stopped:
                return False  # detenido por el usuario: no es culpa del servidor
            self.profile.record_failure(server)
            self.repo.save_health(self.profile)
            self.publish(ev.warn(f"Servidor {server.name} no reproduce, siguiente", server=server.name))
        self.publish(ev.error("Ningun servidor funciono"))
        return False

    # ---------- capitulos ----------
    def next_episode(self) -> bool:
        self.publish(ev.info("Saliendo de pantalla completa"))
        self.browser.exit_fullscreen()
        self.browser.close_popups(self.profile)
        old = self.browser.current_url()
        if not self.browser.click_next(self.profile) and not self._open_next_from_list(old):
            self.publish(ev.error("No hay boton Siguiente: fin de la serie"))
            return False
        self.episodes += 1
        self.current_server = None
        self._user_paused = False
        self.publish(ev.ok(f"Capitulo {self.episodes} cambiado", url=self.browser.current_url(), old=old))
        self._save_progress(0, force=True)
        self._wait(3)
        self.browser.close_popups(self.profile)
        self.stall.reset()
        self.ensure_playing()
        self._wait(10)  # evita disparar de nuevo con datos del capitulo anterior
        return True

    def _open_next_from_list(self, current: str) -> bool:
        """Sitios sin boton Siguiente: abrir el capitulo que sigue en la lista de la pagina."""
        eps = self.browser.episodes(self.profile)
        urls = [e.url.rstrip("/") for e in eps]
        cur = current.split("#")[0].rstrip("/")
        if cur not in urls or urls.index(cur) + 1 >= len(urls):
            return False
        self.browser.open(eps[urls.index(cur) + 1].url)
        return True

    def _end_of_episode(self, st: PlaybackState) -> bool:
        """Devuelve False si hay que terminar la sesion."""
        if self.profile.limit.reached(self.episodes + 1):
            self.publish(ev.ok(f"Limite de {self.profile.episode_limit} capitulos alcanzado. Buenas noches"))
            self.browser.exit_fullscreen()
            self.browser.set_paused(True, self.profile.min_video_duration)
            # deja guardado el siguiente para continuar mañana
            if self.browser.click_next(self.profile):
                self._save_progress(0, force=True)
            return False
        self.publish(ev.info(f"Faltan {st.remaining:.0f}s: cambiando capitulo"))
        return self.next_episode()

    # ---------- comandos ----------
    def _handle(self, cmd: Command, last: PlaybackState | None) -> bool:
        a, md = cmd.args, self.profile.min_video_duration
        if cmd.name == "toggle_pause":
            self._user_paused = not (last.paused if last else True)
            self.browser.set_paused(self._user_paused, md)
        elif cmd.name == "seek":
            self.browser.seek(float(a["position"]), md)
            self.stall.reset()
        elif cmd.name == "seek_relative":
            if last:
                target = max(0.0, min(last.duration - 1, last.position + float(a["delta"])))
                self.browser.seek(target, md)
                self.stall.reset()
        elif cmd.name == "skip":
            return self.next_episode()
        elif cmd.name == "switch_server":
            self.publish(ev.info("Cambio de servidor manual"))
            self.ensure_playing(resume_at=last.position if last else None, exclude=self.current_server)
        elif cmd.name == "fullscreen":
            on = a["on"] if "on" in a else not self.browser.is_fullscreen()
            self.want_fullscreen = bool(on)
            (self.browser.enter_fullscreen if on else self.browser.exit_fullscreen)()
        elif cmd.name == "volume":
            vol = self.browser.change_volume(float(a.get("delta", 0.1)), md)
            if vol is not None:
                self.publish(ev.info(f"Volumen {round(vol * 100)}%"))
        elif cmd.name == "mute":
            muted = self.browser.toggle_mute(md)
            if muted is not None:
                self.publish(ev.info("Silenciado" if muted else "Sonido activado"))
        elif cmd.name == "server":
            name = str(a["name"])
            found = next((s for s in self.browser.list_servers(self.profile) if s.name == name), None)
            conf = next((s for s in self.profile.servers if s.match_text.lower() in name.lower()), None)
            server = conf or found
            if not server:
                self.publish(ev.warn(f"Servidor '{name}' no esta en la pagina"))
                return True
            self.publish(ev.info(f"Servidor elegido: {name}"))
            self.browser.exit_fullscreen()
            self.ensure_playing(resume_at=last.position if last else None, first=server)
        elif cmd.name == "set_quality":
            self.profile.max_quality = bool(a.get("enabled"))
            self.publish(ev.info("Calidad maxima " + ("activada" if self.profile.max_quality else "desactivada")))
            self._quality_tries = 0
            self._apply_quality()
        elif cmd.name == "set_limit":
            self.profile.episode_limit_enabled = bool(a.get("enabled"))
            self.profile.episode_limit = int(a.get("count", self.profile.episode_limit))
            self.publish(ev.info("Limite " + (f"de {self.profile.episode_limit} capitulos activado"
                                              if self.profile.episode_limit_enabled else "desactivado")))
        elif cmd.name == "search":
            self.mode = BROWSING
            self.browser.exit_fullscreen()
            q = str(a.get("query", "")).strip()
            self.publish(ev.info(f"Buscando '{q}'"))
            results = self.browser.search(self.profile, q)
            self.publish(ev.DomainEvent("results", f"{len(results)} resultados",
                                        {"results": [asdict(r) for r in results]}))
        elif cmd.name == "home":
            self.mode = BROWSING
            self.browser.exit_fullscreen()
            u = urlparse(self.profile.url)
            self.browser.open(self.profile.home_url or f"{u.scheme}://{u.netloc}/")
            self.browser.close_popups(self.profile)
            self.browser.wait(3)  # sitios que cargan las tarjetas con JavaScript
            self._check_login()
            results = self.browser.results_here(self.profile)
            self.publish(ev.DomainEvent("results", f"{len(results)} series en el inicio",
                                        {"results": [asdict(r) for r in results]}))
        elif cmd.name == "open":
            url = str(a["url"])
            self.browser.exit_fullscreen()
            self.browser.open(url)
            self.browser.close_popups(self.profile)
            if self._is_episode(url):
                self.publish(ev.info("Abriendo capitulo"))
                self.current_server = None
                self._save_progress(0, force=True)
                self.ensure_playing()
            else:
                self._browse()
        elif cmd.name == "back":
            self.browser.exit_fullscreen()
            if not self.browser.go_back():
                self.publish(ev.warn("No hay pagina anterior"))
                return True
            self.browser.close_popups(self.profile)
            url = self.browser.current_url()
            self.publish(ev.info("Pagina anterior"))
            if self._is_episode(url):
                self.current_server = None
                self.ensure_playing()
            else:
                self._browse()
        elif cmd.name == "episodes":
            self._publish_episodes()
        elif cmd.name == "seasons":
            self._publish_seasons()
        elif cmd.name == "season":
            self.browser.choose_season(self.profile, int(a["index"]))
            self._publish_episodes()
        return True

    def _check_login(self) -> None:
        if not (self.profile.login_selector and self.browser.has_element(self.profile.login_selector)):
            return
        creds = self.credentials.get(self.profile.name) if self.credentials else None
        if not creds or not self.profile.login_url or self._login_tried:
            self.publish(ev.warn("Sin sesion iniciada: guarda tu cuenta en el panel (pestaña Sitio) "
                                 "o entra a mano en la ventana de Brave"))
            return
        self._login_tried = True
        back = self.browser.current_url()
        self.publish(ev.info(f"Iniciando sesion como {creds[0]}..."))
        if self.browser.login(self.profile, *creds):
            self.publish(ev.ok("Sesion iniciada"))
            self.browser.open(back)
        else:
            self.publish(ev.warn("No se pudo iniciar sesion: revisa la cuenta o resuelve el captcha en Brave"))

    def _apply_quality(self) -> None:
        """Los reproductores cargan las calidades tarde: se reintenta unas veces por capitulo."""
        if not self.profile.max_quality or self._quality_tries >= 5:
            return
        self._quality_tries += 1
        label = self.browser.max_quality()
        if label:
            self._quality_tries = 5
            self.publish(ev.ok(f"Calidad: {label}"))

    def _browse(self):
        """Pagina de serie: publicar temporadas y capitulos."""
        self.mode = BROWSING
        seasons = self.browser.seasons(self.profile)
        self.publish(ev.DomainEvent("seasons", "", {"seasons": seasons}))
        if not self.browser.episodes(self.profile) and seasons:
            self.browser.choose_season(self.profile, 0)  # serie sin lista: abrir temporada 1
        self._publish_episodes()
        if not self.browser.episodes(self.profile):  # portada del sitio: ofrecer sus series
            results = self.browser.results_here(self.profile)
            if results:
                self.publish(ev.DomainEvent("results", f"{len(results)} series en la pagina",
                                            {"results": [asdict(r) for r in results]}))

    def _publish_episodes(self):
        self._listed_url = self.browser.current_url()
        eps = self.browser.episodes(self.profile)
        self.publish(ev.DomainEvent("episodes", f"{len(eps)} capitulos", {"episodes": [asdict(e) for e in eps]}))

    def _publish_servers(self):
        names = [s.name for s in self.browser.list_servers(self.profile)] or [s.name for s in self.profile.servers]
        self.publish(ev.DomainEvent("servers", "", {"servers": names}))

    def _publish_seasons(self):
        ss = self.browser.seasons(self.profile)
        self.publish(ev.DomainEvent("seasons", "", {"seasons": ss}))

    # ---------- bucle principal ----------
    def run(self):
        try:
            host = urlparse(self.profile.url).hostname
            url = self.start_url or self.profile.url
            resume_at = None
            saved = self.repo.progress(self.profile.name) if self.profile.resume and not self.start_url else None
            if saved:
                url, resume_at = saved.url, saved.position
                self.publish(ev.info(f"Continuando: {saved.title or saved.url} ({fmt(saved.position)})"))
            self.publish(ev.info("Conectando con Brave..."))
            self.browser.start(url, host if not (saved or self.start_url) else None)
            self.publish(ev.ok(f"Pestaña: {self.browser.current_url()}"))
            self._wait(2)
            self._check_login()
            if self._is_episode(self.browser.current_url()):
                self.ensure_playing(resume_at=resume_at if resume_at and resume_at > 30 else None)
            else:
                self._browse()
            last: PlaybackState | None = None
            while not self.stopped:
                if not self.browser.is_alive():
                    self.publish(ev.error("Navegador cerrado"))
                    break
                self.browser.close_popups(self.profile, deep=False)
                if self.browser.current_url() != self._listed_url:  # pagina nueva: listas al dia
                    self._publish_seasons()
                    self._publish_episodes()
                    self._publish_servers()
                st = self._video() if self.mode == WATCHING else None
                if st:
                    last = st
                    self._save_progress(st.position)
                    if int(st.position) % 10 == 0:
                        self._apply_quality()
                self.publish(ev.status(
                    mode=self.mode,
                    position=st.position if st else 0, duration=st.duration if st else 0,
                    paused=st.paused if st else True, episode=self.episodes,
                    fullscreen=self.want_fullscreen, quality=self.profile.max_quality,
                    volume=round(st.volume * 100) if st else None, muted=st.muted if st else False,
                    server=self.current_server.name if self.current_server else "-",
                    url=self.browser.current_url(), title=self.browser.page_title(),
                    limit_enabled=self.profile.episode_limit_enabled, limit=self.profile.episode_limit,
                    ranking=[(s.name, round(self.profile.health_of(s).score, 2)) for s in self.profile.ranked_servers()],
                ))
                handled = False
                try:
                    cmd = self._commands.get_nowait()
                    handled = True
                    if not self._handle(cmd, last):
                        break
                except queue.Empty:
                    pass
                except Exception as e:  # noqa: BLE001  un comando fallido no tumba la sesion
                    self.publish(ev.error(f"No se pudo '{cmd.name}': {str(e).splitlines()[0]}"))
                if handled or self.mode != WATCHING:
                    self._wait(0.3 if handled else 1)
                    continue
                if st and st.paused and not st.ended and not self._user_paused and self.profile.auto_resume:
                    self._paused_since = self._paused_since or time.time()
                    if time.time() - self._paused_since > 4:
                        self.publish(ev.info("El reproductor se pausó solo: reanudando"))
                        self.browser.set_paused(False, self.profile.min_video_duration)
                        self._paused_since = None
                else:
                    self._paused_since = None
                if st and st.duration and self.transition.should_advance(st):
                    if not self._end_of_episode(st):
                        break
                elif self.stall.feed(st, time.time()):
                    self.publish(ev.warn(f"Servidor {self.current_server.name if self.current_server else ''} caido/congelado"))
                    if self.current_server:
                        self.profile.record_failure(self.current_server, stalled=True)
                        self.repo.save_health(self.profile)
                    self.browser.exit_fullscreen()
                    self.ensure_playing(resume_at=last.position if last else None, exclude=self.current_server)
                self._wait(1)
        except Exception as e:  # noqa: BLE001
            self.publish(ev.error(f"Error: {e}"))
        finally:
            self.browser.close()
            self.publish(ev.info("Detenido", finished=True))


def fmt(sec: float) -> str:
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
