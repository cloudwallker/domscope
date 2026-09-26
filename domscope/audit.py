"""Cohort-aware descriptive statistics and the offline audit pipeline."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time

from . import __version__

SCHEMA_VERSION = "domscope-report-v1"


class AuditError(ValueError):
    """A run cannot produce a valid audit report."""


def ratio(n: int, d: int) -> dict:
    return {"numerator": n, "denominator": d, "value": n / d if d else None}


def _overlap(rows: list[dict], field: str, split: str) -> dict:
    train = {r[field] for r in rows if r["split"] == "train"}
    target = [r for r in rows if r["split"] == split]
    result = ratio(sum(r[field] in train for r in target), len(target))
    if not train and target:
        result.update(value=None, reason="no_training_samples")
    return result


def _cohort(rows: list[dict], fields: tuple[str, ...]) -> dict:
    representations = {}
    for field in fields:
        counts = Counter(r[field] for r in rows)
        representations[field] = {
            "unique_groups": len(counts),
            "redundant_samples": ratio(len(rows) - len(counts), len(rows)),
            "duplicate_group_samples": ratio(sum(n for n in counts.values() if n > 1), len(rows)),
            "overlap": {f"{s}_to_train": _overlap(rows, field, s) for s in ("val", "test")},
        }
    train_raw = {r["raw_hash"] for r in rows if r["split"] == "train"}
    train_dom = {r["dom_hash"] for r in rows if r["split"] == "train"}
    extra = {}
    for split in ("val", "test"):
        eligible = [r for r in rows if r["split"] == split and r["raw_hash"] not in train_raw]
        item = ratio(sum(r["dom_hash"] in train_dom for r in eligible), len(eligible))
        if not train_dom and eligible:
            item.update(value=None, reason="no_training_samples")
        extra[f"{split}_to_train"] = item
    return {
        "size": len(rows),
        "split_counts": {s: sum(r["split"] == s for r in rows) for s in ("train", "val", "test")},
        "representations": representations,
        "extra_dom_overlap": extra,
    }


def _conflicts(rows: list[dict]) -> dict:
    groups = defaultdict(Counter)
    for row in rows:
        if row["label"] is not None:
            groups[row["dom_hash"]][row["label"]] += 1
    total = sum(sum(g.values()) for g in groups.values())
    mixed = [g for g in groups.values() if g[0] and g[1]]
    return {
        "labeled_samples": total,
        "labeled_groups": len(groups),
        "mixed_groups": len(mixed),
        "conflict_samples": ratio(sum(sum(g.values()) for g in mixed), total),
        "empirical_error": ratio(sum(min(g[0], g[1]) for g in groups.values()), total),
    }


def summarize(samples: list[dict]) -> dict:
    """Count samples, never matching pairs; retain unknown values explicitly."""
    host = [r for r in samples if r["dom_host_hash"] is not None]
    return {
        "cohorts": {
            "dom": _cohort(samples, ("raw_hash", "dom_hash")),
            "host": _cohort(host, ("raw_hash", "dom_hash", "dom_host_hash")),
        },
        "dom_conflicts": {
            "all": _conflicts(samples),
            "by_split": {s: _conflicts([r for r in samples if r["split"] == s])
                         for s in ("train", "val", "test")},
            "by_source": {s: _conflicts([r for r in samples if r["source"] == s])
                          for s in sorted({r["source"] for r in samples})},
        },
    }


@dataclass
class AuditResult:
    summary: dict
    samples: list[dict]
    groups: list[dict]
    issues: list[dict]
    cases: list[dict]


def _groups(samples: list[dict]) -> list[dict]:
    buckets = defaultdict(list)
    for sample in samples:
        buckets[sample["dom_hash"]].append(sample)
    result = []
    for group_id, members in sorted(buckets.items()):
        counts = Counter(m["label"] for m in members)
        result.append({
            "group_id": group_id, "size": len(members),
            "benign": counts[0], "phishing": counts[1], "unlabeled": counts[None],
            "mixed_labels": bool(counts[0] and counts[1]),
            "raw_variants": len({m["raw_hash"] for m in members}),
            "hostname_variants": len({m["hostname"] for m in members if m["hostname"]}),
            "sources": sorted({m["source"] for m in members}),
            "splits": sorted({m["split"] for m in members}),
            "sample_ids": sorted(m["sample_id"] for m in members),
        })
    return result


def audit_manifest(path: Path, *, max_bytes: int = 2097152,
                   max_samples: int = 5000, max_nodes: int = 50000) -> AuditResult:
    from .manifest import load_manifest
    from .fingerprints import FingerprintError, fingerprint, parser_metadata

    if any(type(n) is not int or n < 1 for n in (max_bytes, max_samples, max_nodes)):
        raise AuditError("Limits must be positive integers.")
    started = time.perf_counter()
    path = Path(path)
    manifest_bytes = path.read_bytes()
    manifest = load_manifest(path, max_samples=max_samples)
    samples, issues, cases, digests = [], [], [], []
    canonical_index = {}

    def issue(sid, code, detail, severity="excluded"):
        issues.append(dict(sample_id=sid, code=code, detail=detail, severity=severity))

    # Keep full canonical strings on disk, not one in RAM for every distinct page.
    with tempfile.TemporaryFile() as canonical_store:
        for item in manifest:
            try:
                with item.path.open("rb") as stream:
                    data = stream.read(max_bytes + 1)
            except OSError:
                issue(item.sample_id, "file_unreadable", "File is missing or cannot be read.")
                digests.append([item.sample_id, "file_unreadable"])
                continue
            if len(data) > max_bytes:
                issue(item.sample_id, "file_too_large", "File exceeds the configured byte limit.")
                digests.append([item.sample_id, "file_too_large"])
                continue
            digests.append([item.sample_id, hashlib.sha256(data).hexdigest()])
            try:
                fp = fingerprint(data, item.hostname, item.encoding, max_nodes=max_nodes)
            except FingerprintError as exc:
                issue(item.sample_id, exc.code, "Page excluded during decoding or structural parsing.")
                continue
            canonical = fp.pop("canonical").encode("utf-8")
            group = fp["dom_hash"]
            if group in canonical_index:
                offset, length = canonical_index[group]
                canonical_store.seek(offset)
                if canonical_store.read(length) != canonical:
                    raise AuditError("Canonical hash collision detected; audit aborted.")
            else:
                canonical_store.seek(0, 2)
                canonical_index[group] = (canonical_store.tell(), len(canonical))
                canonical_store.write(canonical)
            preview_fields = ("raw_preview", "dom_preview", "raw_preview_truncated", "dom_preview_truncated")
            cases.append({"sample_id": item.sample_id, **{k: fp.pop(k) for k in preview_fields}})
            sample = dict(sample_id=item.sample_id, html_path=item.html_path,
                          split=item.split, source=item.source, label=item.label, encoding=item.encoding, **fp)
            samples.append(sample)
            if fp["hostname_status"] != "valid":
                issue(item.sample_id, f"hostname_{fp['hostname_status']}",
                      "Excluded only from the hostname cohort.", "warning")
            if fp["parse_warning_count"]:
                issue(item.sample_id, "html_recovered", "Recoverable HTML parsing issues; see sample warning codes.", "warning")
    if not samples:
        counts = Counter(r["code"] for r in issues if r["severity"] == "excluded")
        detail = ", ".join(f"{code}={count}" for code, count in sorted(counts.items()))
        raise AuditError(f"No valid pages remain. {detail}")
    train_raw = {s["raw_hash"] for s in samples if s["split"] == "train"}
    train_dom = {s["dom_hash"] for s in samples if s["split"] == "train"}
    for sample in samples:
        held_out = sample["split"] != "train"
        sample["raw_seen_in_train"] = held_out and sample["raw_hash"] in train_raw
        sample["dom_seen_in_train"] = held_out and sample["dom_hash"] in train_dom
        sample["dom_only_seen_in_train"] = sample["dom_seen_in_train"] and not sample["raw_seen_in_train"]
    source_set = {s.source for s in manifest}
    data_kind = "synthetic" if source_set == {"synthetic"} else "mixed" if "synthetic" in source_set else "user"
    metadata = parser_metadata()
    summary = {
        "schema_version": SCHEMA_VERSION,
        "rule_version": "domscope-v1",
        "data_kind": data_kind,
        "counts": {"input": len(manifest), "valid": len(samples),
                   "excluded": len(manifest) - len(samples),
                   "hostname_unavailable": sum(s["dom_host_hash"] is None for s in samples)},
        "metadata": {**metadata, "domscope_version": __version__,
                     "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                     "inputs_sha256": hashlib.sha256(json.dumps(digests, separators=(",", ":")).encode()).hexdigest(),
                     "input_digests": digests,
                     "created_utc": datetime.now(timezone.utc).isoformat(),
                     "elapsed_seconds": round(time.perf_counter() - started, 6),
                     "limits": {"max_bytes": max_bytes, "max_samples": max_samples, "max_nodes": max_nodes}},
        "exclusion_reasons": dict(sorted(Counter(i["code"] for i in issues if i["severity"] == "excluded").items())),
        **summarize(samples),
    }
    return AuditResult(summary, samples, _groups(samples), issues, cases)
