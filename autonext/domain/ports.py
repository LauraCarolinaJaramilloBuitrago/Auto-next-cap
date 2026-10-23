"""Puertos: contratos que la infraestructura implementa."""
from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Episode, PlaybackState, Progress, SearchResult, Server, SiteProfile


class BrowserPort(ABC):
    @abstractmethod
    def start(self, url: str, reuse_host: str | None) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def is_alive(self) -> bool: ...

    @abstractmethod
    def current_url(self) -> str: ...

    @abstractmethod
    def page_title(self) -> str: ...

    @abstractmethod
    def wait(self, seconds: float) -> None: ...

    # reproduccion
    @abstractmethod
    def video_state(self, min_duration: float) -> PlaybackState | None: ...

    @abstractmethod
    def seek(self, position: float, min_duration: float) -> None: ...

    @abstractmethod
    def set_paused(self, paused: bool, min_duration: float) -> None: ...

    @abstractmethod
    def exit_fullscreen(self) -> None: ...

    @abstractmethod
    def enter_fullscreen(self) -> None: ...

    @abstractmethod
    def press_play(self, profile: SiteProfile) -> None: ...

    # navegacion
    @abstractmethod
    def close_popups(self, profile: SiteProfile, deep: bool = True) -> int: ...

    @abstractmethod
    def click_next(self, profile: SiteProfile) -> bool: ...

    @abstractmethod
    def select_server(self, server: Server, profile: SiteProfile) -> bool: ...

    @abstractmethod
    def open(self, url: str) -> None: ...

    @abstractmethod
    def select_language(self, profile: SiteProfile) -> bool:
        """Pulsa la pestaña del idioma preferido si el sitio la tiene."""

    @abstractmethod
    def change_volume(self, delta: float, min_duration: float) -> float | None:
        """Suma delta (0..1) al volumen del video; devuelve el nuevo volumen."""

    @abstractmethod
    def toggle_mute(self, min_duration: float) -> bool | None:
        """Alterna silencio; devuelve True si quedo silenciado."""

    @abstractmethod
    def list_servers(self, profile: SiteProfile) -> list[Server]:
        """Servidores que la pagina muestra ahora (botones visibles)."""

    @abstractmethod
    def max_quality(self) -> str | None:
        """Sube el reproductor a su calidad mas alta; devuelve la etiqueta elegida o None."""

    @abstractmethod
    def go_back(self) -> bool:
        """Pagina anterior del historial; False si no hay."""

    @abstractmethod
    def search(self, profile: SiteProfile, query: str) -> list[SearchResult]: ...

    @abstractmethod
    def results_here(self, profile: SiteProfile) -> list[SearchResult]:
        """Series/peliculas enlazadas en la pagina actual."""

    @abstractmethod
    def has_element(self, selector: str) -> bool:
        """Hay algun elemento que coincide (visible o no)."""

    @abstractmethod
    def episodes(self, profile: SiteProfile) -> list[Episode]: ...

    @abstractmethod
    def seasons(self, profile: SiteProfile) -> list[str]: ...

    @abstractmethod
    def choose_season(self, profile: SiteProfile, index: int) -> None: ...


class ProfileRepository(ABC):
    @abstractmethod
    def all(self) -> dict[str, SiteProfile]: ...

    @abstractmethod
    def active_name(self) -> str: ...

    @abstractmethod
    def save(self, profile: SiteProfile, make_active: bool = True) -> None: ...

    @abstractmethod
    def delete(self, name: str) -> None: ...

    @abstractmethod
    def save_health(self, profile: SiteProfile) -> None:
        """Guarda solo la salud de servidores (el motor no pisa la config que edita la UI)."""

    @abstractmethod
    def save_progress(self, profile_name: str, progress: Progress) -> None: ...

    @abstractmethod
    def progress(self, profile_name: str) -> Progress | None: ...
