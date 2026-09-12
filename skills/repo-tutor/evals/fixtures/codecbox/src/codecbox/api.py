from __future__ import annotations

from codecbox.identity import IdentityCodec
from codecbox.protocol import Codec

_CODECS: dict[str, Codec] = {"identity": IdentityCodec()}


def encode_text(value: str, *, codec: str) -> bytes:
    try:
        selected = _CODECS[codec]
    except KeyError as exc:
        raise ValueError(f"unknown codec: {codec}") from exc
    return selected.encode(value)
