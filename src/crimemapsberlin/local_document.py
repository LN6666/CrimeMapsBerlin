"""Verify a user-supplied official document without requesting its website.

The file hash proves which local bytes were reviewed, not that a claimed sender
or URL is authentic. PDF transcriptions need a separate visual source check.
"""

from __future__ import annotations

import hashlib
import re
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

MAX_LOCAL_BYTES = 20_000_000
FORMATS = {".html": "html", ".htm": "html", ".eml": "email", ".pdf": "pdf", ".xml": "rss"}


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _plain_html(raw: bytes) -> str:
    parser = _VisibleText()
    parser.feed(raw.decode("utf-8-sig"))
    return " ".join(parser.parts)


def _plain_email(raw: bytes) -> str:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    if not message.get("From") or not message.get("Date"):
        raise ValueError("Saved email lacks From or Date headers")
    parts = list(message.walk()) if message.is_multipart() else [message]
    rendered = []
    for part in parts:
        kind = part.get_content_type()
        if kind not in {"text/plain", "text/html"} or part.get_content_disposition() == "attachment":
            continue
        text = part.get_content()
        if isinstance(text, str):
            rendered.append(text if kind == "text/plain" else _plain_html(text.encode()))
    if not rendered:
        raise ValueError("Saved email has no readable text part")
    return " ".join(rendered)


def _plain_rss(raw: bytes) -> str:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DTD is not accepted in local RSS")
    root = ElementTree.fromstring(raw)
    if root.tag.lower() not in {"rss", "{http://www.w3.org/2005/atom}feed"}:
        raise ValueError("Local XML is not RSS or Atom")
    return _plain_html(" ".join(root.itertext()).encode())


def _normalized(text: str) -> str:
    text = re.sub(r"(?m)^\s*#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*\*\s*\*\s*\*\s*$", "", text)
    return " ".join(text.split())


def verify_local_document(
    filename: str | Path, declared_sha256: str, source_text: str, *, base_dir: Path | None = None,
) -> dict[str, str | bool]:
    """Check local bytes and full supplied text; return private file provenance.

    HTML, email and RSS must contain the supplied text. A PDF is
    accepted with a clearly unverified transcription so an LLM can compare it
    to the original during review; no OCR or PDF network service is used.
    """
    path = Path(filename)
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    path = path.resolve(strict=True)
    kind = FORMATS.get(path.suffix.lower())
    if kind is None:
        raise ValueError("Local source must be HTML, EML, PDF, RSS or Atom XML")
    size = path.stat().st_size
    if not 0 < size <= MAX_LOCAL_BYTES:
        raise ValueError("Local source file is empty or too large")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", declared_sha256) or digest != declared_sha256:
        raise ValueError("Local source file SHA-256 mismatch")
    if not isinstance(source_text, str) or len(source_text.strip()) < 30:
        raise ValueError("Local source transcription is incomplete")
    if kind == "pdf":
        if not raw.startswith(b"%PDF-"):
            raise ValueError("Local PDF has no PDF signature")
        text_verified = False
    else:
        plain = {"html": _plain_html, "email": _plain_email, "rss": _plain_rss}[kind](raw)
        if _normalized(source_text) not in _normalized(plain):
            raise ValueError("Supplied text is not present in the local source file")
        text_verified = True
    return {
        "path": str(path), "sha256": digest, "format": kind,
        "text_matches_file": text_verified,
    }
