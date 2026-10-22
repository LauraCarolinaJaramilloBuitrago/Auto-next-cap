"""Servicios de dominio: reglas puras, sin navegador."""
from __future__ import annotations

from .models import PlaybackState


class EpisodeTransitionPolicy:
    """Decide cuando saltar al siguiente capitulo."""

    def __init__(self, seconds_before_end: float):
        self.threshold = seconds_before_end

    def should_advance(self, state: PlaybackState) -> bool:
        return state.ended or state.remaining <= self.threshold


class StallDetector:
    """Detecta servidor caido: video que no avanza, con error o que desaparece."""

    def __init__(self, stall_seconds: float):
        self.limit = stall_seconds
        self._last_pos: float | None = None
        self._since: float | None = None

    def reset(self) -> None:
        self._last_pos = None
        self._since = None

    def feed(self, state: PlaybackState | None, now: float) -> bool:
        if state is not None and state.error:
            return True
        # Pausa manual del usuario no cuenta como caida
        if state is not None and state.paused and not state.ended:
            self._since = None
            self._last_pos = state.position
            return False
        moving = state is not None and (self._last_pos is None or abs(state.position - self._last_pos) > 0.2)
        if moving:
            self._last_pos = state.position
            self._since = None
            return False
        if self._since is None:
            self._since = now
        return now - self._since >= self.limit
