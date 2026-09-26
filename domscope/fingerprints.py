"""Offline, deterministic fingerprints of bytes and parsed HTML structure."""

from __future__ import annotations

import codecs
import hashlib
import ipaddress
import json
import platform
import re
from xml.etree.ElementTree import Element

import html5lib
from html5lib._tokenizer import HTMLTokenizer
from html5lib.constants import tokenTypes


RULE_VERSION = "domscope-v1"
PREVIEW_CHARS = 4000


class FingerprintError(ValueError):
    """A per-sample failure with a stable code and no input contents."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def parser_metadata() -> dict:
    """Configuration included in DOM and joint hashes and in audit reports."""
    return {
        "rule_version": RULE_VERSION,
        "python_version": platform.python_version(),
        "html5lib_version": html5lib.__version__,
        "tree_builder": "etree",
        "namespace_html_elements": True,
        "scripting": False,
        "canonical_format": "ordered-tag-attributes-children-json-v1",
        "qualified_names": "ElementTree Clark notation",
        "idna": "Python built-in IDNA (IDNA 2003); lowercase; remove one final ASCII dot; DNS only",
    }


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hostname(value: str | None) -> tuple[str | None, str]:
    if value is None:
        return None, "missing"
    if not isinstance(value, str) or not value or value != value.strip():
        return None, "invalid"
    value = value.lower()
    if value.endswith("."):
        value = value[:-1]
    try:
        ascii_name = value.encode("idna").decode("ascii")
    except UnicodeError:
        return None, "invalid"
    if not ascii_name or len(ascii_name) > 253:
        return None, "invalid"
    labels = ascii_name.split(".")
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
           for label in labels):
        return None, "invalid"
    try:
        ipaddress.ip_address(ascii_name)
    except ValueError:
        return ascii_name, "valid"
    return None, "invalid"


def _canonical(root: Element, max_nodes: int) -> tuple[str, int, int]:
    """Write nested JSON iteratively so deeply nested input needs no recursion.

    Every element is a typed object with an expanded tag, sorted expanded
    attribute names and ordered children. Text, tails and comments are omitted.
    The JSON never passes through a recursive encoder as a nested Python tree.
    """
    pieces: list[str] = []
    stack: list[tuple[Element | None, int, str]] = [(root, 1, "")]
    element_count = 0
    max_depth = 0
    while stack:
        node, depth, punctuation = stack.pop()
        pieces.append(punctuation)
        if node is None:
            continue
        element_count += 1
        if element_count > max_nodes:
            raise FingerprintError("node-limit", "Parsed HTML exceeds the element node limit.")
        max_depth = max(max_depth, depth)
        pieces.append('{"tag":' + _json(node.tag)
                      + ',"attributes":' + _json(sorted(node.attrib)) + ',"children":[')
        stack.append((None, depth, "]}"))
        children = [child for child in node if isinstance(child.tag, str)]
        for index in range(len(children) - 1, -1, -1):
            stack.append((children[index], depth + 1, "," if index else ""))
    return "".join(pieces), element_count, max_depth


def fingerprint(data: bytes, hostname: str | None = None,
                encoding: str = "utf-8", max_nodes: int = 50000) -> dict:
    """Parse bytes locally with strict explicit decoding; never fetch resources.

    Values and text are discarded *after* HTML tree construction: changing
    those values can still change the resulting tree (for example hidden inputs
    inside tables). Previews are independent from full-content fingerprinting.
    """
    if not isinstance(data, bytes):
        raise FingerprintError("invalid-input", "HTML input must be bytes.")
    if type(max_nodes) is not int or max_nodes < 1:
        raise FingerprintError("invalid-limit", "max_nodes must be a positive integer.")
    if not isinstance(encoding, str) or not encoding.strip():
        raise FingerprintError("invalid-encoding", "A supported text encoding is required.")
    try:
        codec = codecs.lookup(encoding).name
        if not isinstance(codecs.decode(b"", codec), str):
            raise ValueError("not a text codec")
    except (LookupError, ValueError, TypeError):
        raise FingerprintError("invalid-encoding", "A supported text encoding is required.") from None
    try:
        text = data.decode(codec, errors="strict")
        # Some transformation codecs can produce lone surrogates, which are not
        # portable Unicode HTML or serializable UTF-8 report preview contents.
        text.encode("utf-8", errors="strict")
    except UnicodeError:
        raise FingerprintError("decode-error", "HTML could not be decoded with the selected encoding.") from None

    try:
        has_tag = any(token["type"] in (tokenTypes["StartTag"], tokenTypes["EmptyTag"])
                      for token in HTMLTokenizer(text))
        if not has_tag:
            raise FingerprintError("no-elements", "HTML contains no explicit start or empty element tag.")
        parser = html5lib.HTMLParser(tree=html5lib.getTreeBuilder("etree"),
                                    namespaceHTMLElements=True)
        root = parser.parse(text, scripting=False)
        canonical, count, depth = _canonical(root, max_nodes)
    except FingerprintError:
        raise
    except Exception:
        raise FingerprintError("parse-error", "HTML parsing or normalization failed.") from None

    normalized_host, hostname_status = _hostname(hostname)
    configuration = _json(parser_metadata())
    dom_payload = '["dom",' + configuration + "," + canonical + "]"
    dom_hash = hashlib.sha256(dom_payload.encode("utf-8")).hexdigest()
    joint_hash = None
    if normalized_host is not None:
        joint_payload = ('["dom-host",' + configuration + "," + canonical
                         + "," + _json(normalized_host) + "]")
        joint_hash = hashlib.sha256(joint_payload.encode("utf-8")).hexdigest()
    return {
        "raw_hash": hashlib.sha256(data).hexdigest(),
        "dom_hash": dom_hash,
        "dom_host_hash": joint_hash,
        "hostname": normalized_host,
        "hostname_status": hostname_status,
        "element_count": count,
        "max_depth": depth,
        "parse_warning_count": len(parser.errors),
        "parse_warning_codes": sorted({code for _, code, _ in parser.errors}),
        "canonical": canonical,
        "raw_preview": text[:PREVIEW_CHARS],
        "dom_preview": canonical[:PREVIEW_CHARS],
        "raw_preview_truncated": len(text) > PREVIEW_CHARS,
        "dom_preview_truncated": len(canonical) > PREVIEW_CHARS,
    }
