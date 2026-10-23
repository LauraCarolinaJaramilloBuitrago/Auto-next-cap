"""Comandos que la interfaz (escritorio o movil) envia al motor."""
from __future__ import annotations

from dataclasses import dataclass, field

# nombre -> descripcion; la aplicacion valida contra esta lista
COMMANDS = {
    "toggle_pause": "Pausar / reanudar",
    "seek": "Ir a un segundo exacto (args: position)",
    "seek_relative": "Adelantar / atrasar (args: delta)",
    "skip": "Saltar al siguiente capitulo",
    "switch_server": "Probar otro servidor",
    "fullscreen": "Pantalla completa on/off (args: on; sin on = alternar)",
    "set_quality": "Calidad maxima automatica on/off (args: enabled)",
    "volume": "Subir / bajar volumen (args: delta, de -1 a 1)",
    "mute": "Silenciar / quitar silencio",
    "server": "Usar un servidor concreto (args: name)",
    "search": "Buscar serie (args: query)",
    "home": "Series de la pantalla de inicio del sitio",
    "open": "Abrir serie o capitulo (args: url)",
    "back": "Volver a la pagina anterior",
    "episodes": "Listar capitulos de la pagina actual",
    "seasons": "Listar temporadas",
    "season": "Elegir temporada (args: index)",
    "set_limit": "Limite de capitulos (args: enabled, count)",
}


@dataclass(frozen=True)
class Command:
    name: str
    args: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.name not in COMMANDS:
            raise ValueError(f"Comando desconocido: {self.name}")
