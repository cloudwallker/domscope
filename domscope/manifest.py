"""Validate an offline JSONL manifest without opening its HTML inputs."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re


class ManifestError(ValueError):
    """A manifest-wide contract failure, safe to display to the user."""


@dataclass(frozen=True)
class Sample:
    sample_id: str
    html_path: str
    split: str
    source: str
    label: int | None
    hostname: str | None
    encoding: str
    path: Path


_SAMPLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_WINDOWS_DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?\Z", re.I)


def _error(line: int, description: str) -> ManifestError:
    return ManifestError(f"Manifest line {line}: {description}.")


def _unsafe_text(value: str) -> bool:
    return any(ord(char) < 32 or 127 <= ord(char) <= 159
               or 0xD800 <= ord(char) <= 0xDFFF for char in value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    item = {}
    for key, value in pairs:
        if key in item:
            raise ValueError("duplicate object key")
        item[key] = value
    return item


def _sample(item: dict, root: Path, line: int) -> Sample:
    sample_id = item.get("sample_id")
    if not isinstance(sample_id, str) or not _SAMPLE_ID.fullmatch(sample_id):
        raise _error(line, "sample_id must be 1-128 ASCII identifier characters")

    split = item.get("split")
    if not isinstance(split, str) or split not in ("train", "val", "test"):
        raise _error(line, "split must be train, val, or test")
    source = item.get("source")
    if not isinstance(source, str) or not source.strip() or _unsafe_text(source):
        raise _error(line, "source must be a nonempty string without control characters")
    label = item.get("label")
    if label is not None and (type(label) is not int or label not in (0, 1)):
        raise _error(line, "label must be integer 0, integer 1, or null")
    hostname = item.get("hostname")
    if hostname is not None and not isinstance(hostname, str):
        raise _error(line, "hostname must be a string or null")

    encoding = item.get("encoding", "utf-8")
    if not isinstance(encoding, str) or not encoding.strip():
        raise _error(line, "encoding must name a text encoding")
    try:
        encoding = codecs.lookup(encoding).name
        if not isinstance(codecs.decode(b"", encoding), str):
            raise ValueError("not a text codec")
    except (LookupError, ValueError, TypeError):
        raise _error(line, "encoding must name a supported text encoding") from None

    html_path = item.get("html_path")
    if (not isinstance(html_path, str) or not html_path.strip()
            or _unsafe_text(html_path) or ":" in html_path):
        raise _error(line, "html_path must be a safe relative path")
    if PureWindowsPath(html_path).anchor or PurePosixPath(html_path).is_absolute():
        raise _error(line, "html_path must be relative to the manifest directory")
    # Interpret either platform's relative separators consistently.
    relative = PurePosixPath(html_path.replace("\\", "/"))
    for part in relative.parts:
        if part == "..":
            continue  # The resolved containment check below handles traversal.
        if (part.endswith((".", " ")) or _WINDOWS_DEVICE.fullmatch(part)
                or any(char in part for char in '<>"|?*')):
            raise _error(line, "html_path contains a reserved or ambiguous path component")
    try:
        resolved = root.joinpath(*relative.parts).resolve()
        if not resolved.is_relative_to(root):
            raise _error(line, "html_path resolves outside the manifest directory")
    except (OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, ManifestError):
            raise
        raise _error(line, "html_path cannot be safely resolved") from None

    return Sample(sample_id, relative.as_posix(), split, source, label,
                  hostname, encoding, resolved)


def load_manifest(path: Path, max_samples: int = 5000) -> list[Sample]:
    """Load typed samples; missing HTML files are intentionally not checked here.

    The manifest's resolved parent is the data root. Absolute paths, Windows
    drive/stream forms and links escaping that root are rejected on all systems.
    Blank lines are ignored; reported line numbers always refer to the source.
    """
    if type(max_samples) is not int or max_samples < 1:
        raise ManifestError("max_samples must be a positive integer.")
    try:
        manifest_path = Path(path).resolve()
        root = manifest_path.parent
        samples: list[Sample] = []
        ids: set[str] = set()
        with manifest_path.open("r", encoding="utf-8-sig", errors="strict") as handle:
            for line_number, text in enumerate(handle, 1):
                if not text.strip():
                    continue
                if len(samples) >= max_samples:
                    raise _error(line_number, "sample limit exceeded")
                try:
                    item = json.loads(text, object_pairs_hook=_unique_object)
                except (ValueError, RecursionError):
                    raise _error(line_number, "invalid JSON object") from None
                if not isinstance(item, dict):
                    raise _error(line_number, "each record must be a JSON object")
                sample = _sample(item, root, line_number)
                if sample.sample_id in ids:
                    raise _error(line_number, "duplicate sample_id")
                ids.add(sample.sample_id)
                samples.append(sample)
    except ManifestError:
        raise
    except (OSError, UnicodeError, ValueError, RuntimeError, TypeError):
        raise ManifestError("Manifest could not be read as UTF-8 JSONL.") from None
    if not samples:
        raise ManifestError("Manifest contains no samples.")
    return samples
