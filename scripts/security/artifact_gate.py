#!/usr/bin/env python3
"""Seal/verify an accepted static artifact. Receipt must remain outside the public site.

Checksums prove byte integrity against a trusted detached digest, not source truth or
protection from an attacker controlling both the trusted build and deployment.
"""
import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

CITIES = set("berlin hamburg munich cologne frankfurt dusseldorf stuttgart leipzig dortmund bremen essen dresden hannover nuremberg".split())
ALLOWED = set(".html .js .mjs .css .json .geojson .png .jpg .jpeg .webp .ico .svg .woff .woff2 .ttf .txt .xml".split())
PRIVATE = {"raw_html", "article_body", "source_body", "raw_body", "full_body", "full_text", "authorization", "api_key", "access_token", "private_key", "password", "secret"}
FORBIDDEN_PARTS = {".runtime", ".git", "node_modules", "src", "test_suite", "reviews", "review", "archives", "archive", "source-downloads"}
SECRET = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{60,}\b|\bAKIA[A-Z0-9]{16}\b")
SVG_TAGS = set("svg g path circle ellipse line polyline polygon rect text tspan title desc defs linearGradient radialGradient stop clipPath mask use".split())

def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def check_json(value):
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if PRIVATE.intersection(str(key).lower() for key in item):
                raise ValueError("Private JSON field in public artifact")
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)

def check_svg(raw):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("SVG entities/DOCTYPE forbidden")
    root = ET.fromstring(raw)
    if root.tag.split("}")[-1] != "svg":
        raise ValueError("Not SVG")
    for element in root.iter():
        if element.tag.split("}")[-1] not in SVG_TAGS:
            raise ValueError("Active/unsupported SVG element")
        for key, value in element.attrib.items():
            key = key.split("}")[-1].lower()
            if key.startswith("on") or key in {"src", "base"}:
                raise ValueError("Active SVG attribute")
            if key == "href" and not re.fullmatch(r"#[A-Za-z_][A-Za-z0-9_.:-]*", value):
                raise ValueError("External SVG reference")
            if re.search(r"@import|expression\s*\(|javascript\s*:|data\s*:|https?\s*:|//", value, re.I):
                raise ValueError("External/active SVG value")
            for reference in re.findall(r"url\s*\((.*?)\)", value, re.I):
                if not re.fullmatch(r"['\"]?#[A-Za-z_][A-Za-z0-9_.:-]*['\"]?", reference.strip()):
                    raise ValueError("Unsafe SVG CSS reference")

class StaticHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.csp = False
        self.script = False
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if any(k.lower().startswith("on") for k in attrs):
            raise ValueError("HTML event handler forbidden")
        if tag == "meta" and attrs.get("http-equiv", "").lower() == "content-security-policy":
            policy = attrs.get("content", "")
            directives = dict((p.strip().split(None, 1) + [""])[:2] for p in policy.split(";") if p.strip())
            if directives.get("script-src") not in {"'none'", "'self'", "'self' https://challenges.cloudflare.com"} or directives.get("object-src") != "'none'" or directives.get("base-uri") != "'none'":
                raise ValueError("Missing restrictive executable-content CSP")
            self.csp = True
        if tag == "script":
            src = attrs.get("src", "")
            challenge = src in {"https://challenges.cloudflare.com/turnstile/v0/api.js", "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"}
            if not challenge and (not src or src.startswith("//") or re.search(r"[\\:%\s]", src) or ".." in src.split("/")):
                raise ValueError("Inline/external script forbidden")
            self.script = True
    def handle_endtag(self, tag):
        if tag == "script":
            self.script = False
    def handle_data(self, data):
        if self.script and data.strip():
            raise ValueError("Inline script body forbidden")

def scan(root, city, commit):
    if city not in CITIES or not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("City or code commit invalid")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Artifact root must be a real directory")
    files = {}
    total = 0
    generations = set()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        if path.is_symlink():
            raise ValueError("Artifact symlink forbidden")
        if path.is_dir():
            continue
        if not path.is_file() or any(part in FORBIDDEN_PARTS for part in parts):
            raise ValueError("Private/unsupported artifact path")
        if any(part.startswith(".") for part in parts) and relative not in {".nojekyll", ".well-known/security.txt"}:
            raise ValueError("Hidden artifact path forbidden")
        if path.suffix.lower() not in ALLOWED and relative != ".nojekyll":
            raise ValueError("Unsupported artifact extension")
        if re.search(r"(?i)(?:sqlite|credentials|source[-_]review|review[-_]decisions|scope[-_]decisions|scene[-_]decisions|geometry[-_]decisions|map[-_]decisions|source[-_]packet|owner[-_]review)", relative):
            raise ValueError("Private audit/credential file forbidden")
        size = path.stat().st_size
        total += size
        if total > 900_000_000 or size > 100_000_000 or len(files) >= 100_000:
            raise ValueError("Artifact exceeds bounded Pages budget")
        suffix = path.suffix.lower()
        if suffix in {".html", ".js", ".mjs", ".css", ".json", ".geojson", ".txt", ".xml", ".svg"}:
            raw = path.read_bytes()
            if SECRET.search(raw):
                raise ValueError("Credential signature found; details suppressed")
            if suffix in {".json", ".geojson"}:
                check_json(json.loads(raw))
            if suffix == ".svg":
                check_svg(raw)
            if suffix == ".html":
                parser = StaticHTML()
                parser.feed(raw.decode("utf-8"))
                if not parser.csp:
                    raise ValueError("Public HTML missing CSP")
        for part in parts:
            if re.fullmatch(r"[a-f0-9]{16}-\d{8}T\d{6}", part):
                generations.add(part)
        files[relative] = {"sha256": digest(path), "bytes": size}
    if "index.html" not in files or len(generations) > 1:
        raise ValueError("Missing entrance or multiple data generations")
    return {"schema_version": 1, "city": city, "code_commit": commit, "total_bytes": total, "files": files}

def verify(root, expected, expected_sha256, city, commit):
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256) or digest(expected) != expected_sha256:
        raise ValueError("Detached receipt does not match trusted digest")
    actual = scan(root, city, commit)
    if json.loads(expected.read_text()) != actual:
        raise ValueError("Artifact differs from accepted receipt")
    return actual

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["seal", "verify"])
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--city", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    try:
        if args.mode == "seal":
            if not args.out or args.artifact.resolve() == args.out.resolve() or args.artifact.resolve() in args.out.resolve().parents:
                raise ValueError("Receipt must be outside artifact")
            result = scan(args.artifact, args.city, args.commit)
            args.out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
            receipt_hash = digest(args.out)
        else:
            if not args.expected or not args.expected_sha256:
                raise ValueError("Expected receipt and trusted digest required")
            result = verify(args.artifact, args.expected, args.expected_sha256, args.city, args.commit)
            receipt_hash = args.expected_sha256
        print(json.dumps({"ok": True, "city": args.city, "files": len(result["files"]), "bytes": result["total_bytes"], "receipt_sha256": receipt_hash}))
    except (ValueError, OSError, ET.ParseError, UnicodeError) as error:
        parser.exit(1, f"Artifact gate rejected: {error}\n")

if __name__ == "__main__":
    main()
