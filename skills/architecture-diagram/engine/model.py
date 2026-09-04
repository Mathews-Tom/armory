"""Authored architecture-diagram model objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Node:
    id: str
    label: str
    service: str | None = None
    sublabel: str = ""
    zone: str | None = None
    color: str = "#3A3A3A"
    provider: str = "generic"
    owner: str | None = None
    external: bool = False
    storage: bool = False


@dataclass
class Zone:
    id: str
    label: str
    parent: str | None = None
    kind: str = "generic"


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""
    type: str = "default"
    id: str | None = None


@dataclass
class Spec:
    title: str
    direction: str
    provider: str
    nodes: list[Node]
    zones: list[Zone]
    edges: list[Edge]
    profile: str | None = None
