from __future__ import annotations


class IdentityCodec:
    def encode(self, value: str) -> bytes:
        return value.encode("utf-8")
