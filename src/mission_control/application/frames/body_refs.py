"""The `frame-body://` reference scheme (1.4.4, TR-D3).

A promoted frame body is evidence of a frame, not a governed artifact: the frame row already
registers its digest, size and media type, so no `artifact_metadata_revision` row is written.
The reference names the body in the content-addressed payload store:

    frame-body://sha256:<hex>?bytes=<n>&type=<media>

`bytes` and `type` repeat what the frame row holds so a reader can bound and label the read
before touching the store; the store locates the bytes by the digest alone
(`address_for`) and the reader verifies them against the digest and the byte count. Every
value is URL-encoded. Tracing Stage 3 (R4-F6): the `&ref=<object locator>` parameter is
gone (the promoter never wrote it, and a caller-supplied locator must never address the
store); a legacy `ref=` is ignored on parse.

Bodies are content-addressed and shared: two runs that promote identical bytes reference one
object. A reference therefore proves nothing about which run produced it; the transcript
reader authorizes the read by the caller's grant on the run it is materializing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import parse_qsl, quote, unquote

FRAME_BODY_PREFIX: Final = "frame-body://"
_DIGEST_PREFIX: Final = "sha256:"
_HEX: Final = frozenset("0123456789abcdef")


class MalformedFrameBodyRef(ValueError):
    """The string is not a well-formed `frame-body://` reference."""


@dataclass(frozen=True)
class FrameBodyRef:
    """A parsed `frame-body://` reference."""

    digest: str
    """`sha256:<hex>` of the promoted bytes."""
    bytes: int
    media_type: str

    @property
    def hex_digest(self) -> str:
        return self.digest.removeprefix(_DIGEST_PREFIX)

    def render(self) -> str:
        return frame_body_ref(digest=self.digest, size_bytes=self.bytes, media_type=self.media_type)


def is_frame_body_ref(ref: str | None) -> bool:
    return ref is not None and ref.startswith(FRAME_BODY_PREFIX)


def frame_body_ref(*, digest: str, size_bytes: int, media_type: str) -> str:
    """Render a reference; `digest` is `sha256:<hex>` (the payload store's content digest)."""

    hex_digest = _hex_digest(digest)
    if size_bytes < 0:
        raise MalformedFrameBodyRef("frame body size cannot be negative")
    if not media_type:
        raise MalformedFrameBodyRef("frame body media type is required")
    return (
        f"{FRAME_BODY_PREFIX}{_DIGEST_PREFIX}{hex_digest}"
        f"?bytes={size_bytes}&type={quote(media_type, safe='')}"
    )


def parse_frame_body_ref(ref: str) -> FrameBodyRef:
    """Parse a reference; raises `MalformedFrameBodyRef` for anything else."""

    if not is_frame_body_ref(ref):
        raise MalformedFrameBodyRef("not a frame-body reference")
    rest = ref.removeprefix(FRAME_BODY_PREFIX)
    address, separator, query = rest.partition("?")
    if not separator or not address.startswith(_DIGEST_PREFIX):
        raise MalformedFrameBodyRef("frame-body reference needs a sha256 digest and a query")
    hex_digest = _hex_digest(address)
    params = dict(parse_qsl(query, keep_blank_values=True, strict_parsing=False))
    size = params.get("bytes")
    media_type = params.get("type")
    if size is None or not size.isdigit():
        raise MalformedFrameBodyRef("frame-body reference needs an integer `bytes`")
    if not media_type:
        raise MalformedFrameBodyRef("frame-body reference needs a `type`")
    return FrameBodyRef(
        digest=f"{_DIGEST_PREFIX}{hex_digest}", bytes=int(size), media_type=unquote(media_type)
    )


def _hex_digest(digest: str) -> str:
    value = digest.removeprefix(_DIGEST_PREFIX).lower()
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise MalformedFrameBodyRef("frame body digest is not a sha256 hex digest")
    return value


__all__ = [
    "FRAME_BODY_PREFIX",
    "FrameBodyRef",
    "MalformedFrameBodyRef",
    "frame_body_ref",
    "is_frame_body_ref",
    "parse_frame_body_ref",
]
