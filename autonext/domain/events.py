"""Eventos de dominio que la aplicacion publica hacia la interfaz."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DomainEvent:
    kind: str           # info | ok | warn | error | status
    message: str = ""
    data: dict = field(default_factory=dict)
    at: float = field(default_factory=time.time)


def info(msg, **data):
    return DomainEvent("info", msg, data)


def ok(msg, **data):
    return DomainEvent("ok", msg, data)


def warn(msg, **data):
    return DomainEvent("warn", msg, data)


def error(msg, **data):
    return DomainEvent("error", msg, data)


def status(**data):
    return DomainEvent("status", "", data)
