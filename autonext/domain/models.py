"""Modelo de dominio: perfiles de sitio, servidores, progreso y estado de reproduccion."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Server:
    """Value object: un servidor de video del sitio (boton que cambia el reproductor)."""
    name: str
    selector: str = "button.server-btn"
    text: str = ""          # texto que debe contener el boton (vacio = usa name)
    enabled: bool = True
    opener: str = ""        # selector que se pulsa antes (desplegables de idioma)

    @property
    def match_text(self) -> str:
        return self.text or self.name


@dataclass
class ServerHealth:
    """Historial de un servidor. Decide cual probar primero."""
    successes: int = 0
    failures: int = 0
    stalls: int = 0
    last_ok: float = 0.0
    last_fail: float = 0.0

    @property
    def score(self) -> float:
        total = self.successes + self.failures + self.stalls
        if total == 0:
            return 0.5  # sin datos: neutro
        # Laplace + castigo extra a congelamientos y a fallos recientes
        base = (self.successes + 1) / (total + 2)
        base -= 0.05 * self.stalls / max(total, 1)
        if self.last_fail and time.time() - self.last_fail < 600:
            base -= 0.15
        return max(0.0, min(1.0, base))


@dataclass(frozen=True)
class PlaybackState:
    """Value object: foto del <video> principal."""
    position: float
    duration: float
    paused: bool
    ended: bool
    error: bool = False
    volume: float = 1.0
    muted: bool = False

    @property
    def remaining(self) -> float:
        return max(0.0, self.duration - self.position)

    @property
    def progress(self) -> float:
        return self.position / self.duration if self.duration else 0.0


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    image: str = ""


@dataclass(frozen=True)
class Episode:
    title: str
    url: str
    current: bool = False


@dataclass
class Progress:
    """Donde se quedo el usuario en un perfil (para continuar)."""
    url: str
    position: float = 0.0
    title: str = ""
    updated: float = field(default_factory=time.time)


@dataclass(frozen=True)
class EpisodeLimit:
    """Value object: limite opcional de capitulos por sesion."""
    enabled: bool = False
    count: int = 3

    def reached(self, finished_episodes: int) -> bool:
        """finished_episodes = capitulos terminados en esta sesion (incluido el actual)."""
        return self.enabled and finished_episodes >= max(1, self.count)


@dataclass
class SiteProfile:
    """Aggregate root: toda la configuracion de un sitio + salud de sus servidores."""
    name: str
    url: str
    seconds_before_end: float = 10
    next_selector: str = "a.btn-accent[href*='episodio']"
    next_text: str = "Siguiente"
    play_selectors: list[str] = field(default_factory=list)
    popup_selectors: list[str] = field(default_factory=list)
    overlay_selectors: list[str] = field(default_factory=list)
    allowed_domains: list[str] = field(default_factory=list)
    fullscreen: bool = True
    max_quality: bool = True         # elegir la calidad mas alta si el reproductor la ofrece
    preferred_language: str = "Latino"
    language_selector: str = "[data-lang-tab], .player-tab"  # pestañas de idioma del reproductor
    servers: list[Server] = field(default_factory=list)
    auto_rank_servers: bool = True
    server_timeout: float = 50       # segundos para que un servidor arranque
    stall_seconds: float = 20        # segundos sin avanzar = servidor caido
    min_video_duration: float = 120  # ignora videos cortos (anuncios)
    # Busqueda y navegacion
    search_input_selector: str = ""  # se le da clic y se escribe
    search_url: str = ""             # respaldo: plantilla con {q}
    result_pattern: str = r"/serie/[^/]+/?$"
    episode_pattern: str = r"/episodio"
    season_selector: str = ""        # <select> de temporadas o pestañas/acordeones
    # Sesion
    episode_limit_enabled: bool = False
    episode_limit: int = 3
    resume: bool = True              # continuar donde se quedo
    auto_resume: bool = True         # reanudar si el reproductor se pausa solo
    health: dict[str, ServerHealth] = field(default_factory=dict)

    @property
    def limit(self) -> EpisodeLimit:
        return EpisodeLimit(self.episode_limit_enabled, int(self.episode_limit))

    # ---------- reglas de servidores ----------
    def health_of(self, server: Server) -> ServerHealth:
        return self.health.setdefault(server.name, ServerHealth())

    def speaks_preferred(self, server: Server) -> bool:
        lang = self.preferred_language.strip().lower()
        return bool(lang) and lang in f"{server.name} {server.text} {server.opener}".lower()

    def ranked_servers(self) -> list[Server]:
        active = [s for s in self.servers if s.enabled]
        order = {s.name: i for i, s in enumerate(active)}
        # idioma preferido siempre primero; luego mejor salud; empate = orden configurado
        health = (lambda s: -round(self.health_of(s).score, 2)) if self.auto_rank_servers else (lambda s: 0)
        return sorted(active, key=lambda s: (not self.speaks_preferred(s), health(s), order[s.name]))

    def record_success(self, server: Server) -> None:
        h = self.health_of(server)
        h.successes += 1
        h.last_ok = time.time()

    def record_failure(self, server: Server, stalled: bool = False) -> None:
        h = self.health_of(server)
        if stalled:
            h.stalls += 1
        else:
            h.failures += 1
        h.last_fail = time.time()

    def reset_health(self) -> None:
        self.health.clear()

    # ---------- serializacion ----------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["servers"] = [asdict(s) for s in self.servers]
        d["health"] = {k: asdict(v) for k, v in self.health.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SiteProfile":
        d = dict(d)
        servers = [Server(**s) for s in d.pop("servers", [])]
        health = {k: ServerHealth(**v) for k, v in d.pop("health", {}).items()}
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in known}, servers=servers, health=health)


COMMON_POPUPS = [
    "[class*='modal'] [class*='close']",
    "[class*='popup'] [class*='close']",
    "[aria-label='Close']",
    "[aria-label='Cerrar']",
    ".btn-close",
]
COMMON_PLAY = [
    "button.play-button-overlay",
    ".plyr__control--overlaid",
    ".jw-icon-display",
    ".vjs-big-play-button",
    "button[aria-label*='play' i]",
]


def default_profiles() -> list[SiteProfile]:
    sololatino = SiteProfile(
        name="sololatino",
        url="https://sololatino.co/serie/boku-no-hero/temporada-1/episodio-1",
        play_selectors=list(COMMON_PLAY),
        popup_selectors=list(COMMON_POPUPS),
        overlay_selectors=["[class*='modal-backdrop']", "div[style*='z-index: 2147483647']"],
        allowed_domains=["sololatino.co"],
        servers=[Server("Principal"), Server("SLPLAYER"), Server("FEMBED")],
        search_input_selector="input[placeholder='Buscar...']",
        search_url="https://sololatino.co/buscar?q={q}",
        result_pattern=r"/(serie|pelicula)/[^/]+/?$",
        episode_pattern=r"/temporada-\d+/episodio-\d+",
        season_selector="select:has(option:has-text('Temporada'))",
    )
    seriesflix = SiteProfile(
        name="seriesflixhd",
        url="https://seriesflixhd.pw/episodio/how-i-met-your-mother-2-1x1/",
        next_selector="a.next",
        play_selectors=list(COMMON_PLAY),
        popup_selectors=list(COMMON_POPUPS),
        overlay_selectors=["#ifnelta"],
        allowed_domains=["seriesflixhd.pw", "pelisflixhd1.online"],  # la busqueda redirige al espejo
        servers=[
            Server("Latino", ".optnslst .Button", "LATINO", opener="button.bstd:has-text('LATINO')"),
            Server("Castellano", ".optnslst .Button", "CASTELLANO", opener="button.bstd:has-text('CASTELLANO')"),
            Server("Subtitulado", ".optnslst .Button", "SUBTITULADO", opener="button.bstd:has-text('SUBTITULADO')"),
        ],
        search_input_selector="input[name='s']",
        search_url="https://seriesflixhd.pw/?s={q}",
        result_pattern=r"/(serie|pelicula)/[^/]+/?$",
        episode_pattern=r"/episodio/[^/#]+/?$",
        season_selector="section.SeasonBx .Title a",
    )
    movie0123 = SiteProfile(
        name="0123movie",
        url="https://0123movie.pro/episode/how-i-met-your-mother-2005-watch-online/s02-e02/",
        next_selector="",  # no tiene boton Siguiente: se usa la lista de capitulos
        next_text="",
        play_selectors=["#btn-big-play", *COMMON_PLAY],
        popup_selectors=list(COMMON_POPUPS),
        allowed_domains=["0123movie.pro"],
        # la lista de servidores aparece despues de pulsar el play grande
        servers=[Server("Vidmoly", "#server-list a", opener="#btn-big-play"),
                 Server("0123Movies", "#server-list a", opener="#btn-big-play")],
        search_input_selector="input.search-input",
        search_url="https://0123movie.pro/search?keyword={q}",
        result_pattern=r"/watch-(series|movie)/[^/]+/?$",
        episode_pattern=r"/episode/[^/]+/s\d+-e\d+/?$",
        season_selector="a.ss-item",
        preferred_language="",  # sitio en ingles: sin pestañas de idioma
    )
    return [sololatino, seriesflix, movie0123]


def default_profile() -> SiteProfile:
    return default_profiles()[0]
