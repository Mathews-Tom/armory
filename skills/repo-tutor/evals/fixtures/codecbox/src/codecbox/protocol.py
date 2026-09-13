from __future__ import annotations

from typing import Protocol


class Codec(Protocol):
    def encode(self, value: str) -> bytes: ...
