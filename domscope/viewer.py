"""Read a report bundle; this module never parses or renders input HTML."""
import csv
import io
import json
import math
from pathlib import Path
import re

from .audit import SCHEMA_VERSION
from .report import ARTIFACTS, ReportError

MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
# One group can contain all 5,000 IDs. The csv module default is only 128 KiB.
csv.field_size_limit(MAX_ARTIFACT_BYTES)


def _nonnegative(value):
    if type(value) is not int or value < 0:
        raise ReportError("Invalid count in report.")


def _metric(item):
    n, d, value = item["numerator"], item["denominator"], item["value"]
    _nonnegative(n)
    _nonnegative(d)
    if n > d:
        raise ReportError("Invalid metric denominator.")
    if value is None:
        if d and item.get("reason") != "no_training_samples":
            raise ReportError("Missing metric value.")
    elif (type(value) not in (int, float) or not d or not math.isfinite(value)
          or not math.isclose(value, n / d, abs_tol=1e-12)):
        raise ReportError("Metric does not match its numerator and denominator.")


def _conflict(item):
    for field in ("labeled_samples", "labeled_groups", "mixed_groups"):
        _nonnegative(item[field])
    for field in ("conflict_samples", "empirical_error"):
        _metric(item[field])
        if item[field]["denominator"] != item["labeled_samples"]:
            raise ReportError("Inconsistent labeled denominator.")


def _summary(summary):
    if summary["data_kind"] not in ("synthetic", "user", "mixed"):
        raise ReportError("Invalid dataset kind.")
    counts = summary["counts"]
    for key in ("input", "valid", "excluded", "hostname_unavailable"):
        _nonnegative(counts[key])
    if counts["valid"] + counts["excluded"] != counts["input"]:
        raise ReportError("Input counts are inconsistent.")
    metadata = summary["metadata"]
    if not isinstance(metadata, dict) or not isinstance(metadata["created_utc"], str):
        raise ReportError("Missing run metadata.")
    for key in ("dom", "host"):
        cohort = summary["cohorts"][key]
        _nonnegative(cohort["size"])
        for split in ("train", "val", "test"):
            _nonnegative(cohort["split_counts"][split])
        if sum(cohort["split_counts"].values()) != cohort["size"]:
            raise ReportError("Cohort counts are inconsistent.")
        fields = ("raw_hash", "dom_hash") if key == "dom" else ("raw_hash", "dom_hash", "dom_host_hash")
        for field in fields:
            rep = cohort["representations"][field]
            _nonnegative(rep["unique_groups"])
            for metric in ("redundant_samples", "duplicate_group_samples"):
                _metric(rep[metric])
            for direction in ("val_to_train", "test_to_train"):
                _metric(rep["overlap"][direction])
        for direction in ("val_to_train", "test_to_train"):
            _metric(cohort["extra_dom_overlap"][direction])
    if (summary["cohorts"]["dom"]["size"] != counts["valid"]
            or summary["cohorts"]["host"]["size"] != counts["valid"] - counts["hostname_unavailable"]):
        raise ReportError("Eligible sample counts are inconsistent.")
    conflicts = summary["dom_conflicts"]
    _conflict(conflicts["all"])
    for split in ("train", "val", "test"):
        _conflict(conflicts["by_split"][split])
    for item in conflicts["by_source"].values():
        _conflict(item)


def load_bundle(path: Path) -> dict:
    path = Path(path).resolve()
    try:
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ReportError("Summary is too large.")
        summary = json.loads(path.read_text(encoding="utf-8"))
        if summary.get("schema_version") != SCHEMA_VERSION or summary.get("rule_version") != "domscope-v1":
            raise ReportError("Unsupported report version. Generate a report with this version of DOMScope.")
        if summary.get("artifacts") != ARTIFACTS:
            raise ReportError("Invalid artifact paths. Regenerate the report bundle.")
        _summary(summary)
        contents = {}
        for key, filename in ARTIFACTS.items():
            artifact = path.parent / filename
            if artifact.is_symlink() or artifact.resolve().parent != path.parent:
                raise ReportError("An artifact points outside the report directory.")
            if artifact.stat().st_size > MAX_ARTIFACT_BYTES:
                raise ReportError("An artifact exceeds the viewer's 256 MiB limit; audit a smaller batch.")
            contents[key] = artifact.read_bytes()
        samples = list(csv.DictReader(io.StringIO(contents["samples"].decode("utf-8-sig"))))
        groups = list(csv.DictReader(io.StringIO(contents["groups"].decode("utf-8-sig"))))
        issues = list(csv.DictReader(io.StringIO(contents["issues"].decode("utf-8-sig"))))
        cases = [json.loads(line) for line in contents["cases"].decode("utf-8").splitlines() if line]
        ids = [r["sample_id"] for r in samples]
        if (not ids or len(ids) != summary["counts"]["valid"] or len(set(ids)) != len(ids)
                or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", sid) for sid in ids)
                or sorted(ids) != sorted(c["sample_id"] for c in cases)):
            raise ReportError("Sample evidence is inconsistent. Regenerate the report.")
        for row in samples:
            row["label"] = None if row["label"] == "" else int(row["label"])
            for field in ("element_count", "max_depth", "parse_warning_count"):
                row[field] = int(row[field])
            for field in ("raw_seen_in_train", "dom_seen_in_train", "dom_only_seen_in_train"):
                if row[field] not in ("true", "false"):
                    raise ReportError("Invalid boolean evidence.")
                row[field] = row[field] == "true"
        for group in groups:
            for field in ("size", "benign", "phishing", "unlabeled", "raw_variants", "hostname_variants"):
                group[field] = int(group[field])
            group["mixed_labels"] = group["mixed_labels"] == "true"
            for field in ("sample_ids", "sources", "splits"):
                group[field] = json.loads(group[field])
        for case in cases:
            for field in ("raw_preview", "dom_preview"):
                if not isinstance(case[field], str) or len(case[field]) > 4000:
                    raise ReportError("Invalid case preview.")
                if type(case[field + "_truncated"]) is not bool:
                    raise ReportError("Invalid preview truncation flag.")
        if sum(g["size"] for g in groups) != len(samples):
            raise ReportError("Group sizes do not match samples.")
        return {"summary": summary, "samples": samples, "groups": groups, "issues": issues,
                "cases": {c["sample_id"]: c for c in cases},
                "downloads": {**{ARTIFACTS[k]: v for k, v in contents.items()}, "summary.json": path.read_bytes()}}
    except ReportError:
        raise
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError, csv.Error, RecursionError):
        raise ReportError("Report is incomplete or unreadable. Run the audit again in a new output directory.") from None
