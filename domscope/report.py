"""Write self-contained artifacts without replacing existing results."""
from __future__ import annotations

import csv
from html import escape
import json
import os
from pathlib import Path
import tempfile

from .audit import AuditResult

ARTIFACTS = {
    "samples": "samples.csv", "groups": "groups.csv", "issues": "issues.csv",
    "cases": "cases.jsonl", "report": "report.md",
}


class ReportError(ValueError):
    """An output location or report cannot be used safely."""


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str) and (value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))):
        return "'" + value
    return value


def _write_csv(path: Path, rows: list[dict], fallback_fields: tuple[str, ...] = ()):
    fields = list(rows[0]) if rows else list(fallback_fields)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _csv_value(v) for k, v in row.items()})


def metric_text(metric: dict) -> str:
    n, d = metric["numerator"], metric["denominator"]
    if metric["value"] is None:
        return f"N/A ({n}/{d})"
    return f"{metric['value']:.1%} ({n}/{d})"


def _md(text: str) -> str:
    return escape(str(text)).replace("|", "&#124;").replace("\n", " ").replace("\r", " ").replace("[", "&#91;").replace("]", "&#93;").replace("`", "&#96;")


def markdown_report(summary: dict) -> str:
    kind = summary["data_kind"]
    lines = ["# DOMScope audit report", "",
             "**Synthetic demonstration / 合成演示数据. These results are not research evidence.**"
             if kind == "synthetic" else "**User-supplied data / 用户提供的数据. Labels and provenance are not independently verified.**",
             "", "The tool audits representations, not phishing detection performance.", "",
             "## Input coverage", "", "| Input | Valid DOM | Excluded | Hostname unavailable |",
             "|---:|---:|---:|---:|"]
    c = summary["counts"]
    lines.append(f"| {c['input']} | {c['valid']} | {c['excluded']} | {c['hostname_unavailable']} |")
    for key, title in (("dom", "All valid DOM samples"), ("host", "Valid DOM + hostname cohort")):
        cohort = summary["cohorts"][key]
        lines += ["", f"## {title}", "", f"Samples: {cohort['size']}. Each row uses the same eligible cohort.", "",
                  "| Representation | Unique groups | Redundancy | Samples in duplicate groups | val → train | test → train |",
                  "|---|---:|---|---|---|---|"]
        for field, rep in cohort["representations"].items():
            name = {"raw_hash": "Raw bytes", "dom_hash": "DOM", "dom_host_hash": "DOM + hostname"}[field]
            cells = [name, str(rep["unique_groups"]), metric_text(rep["redundant_samples"]),
                     metric_text(rep["duplicate_group_samples"]), metric_text(rep["overlap"]["val_to_train"]),
                     metric_text(rep["overlap"]["test_to_train"])]
            lines.append("| " + " | ".join(cells) + " |")
        lines += ["", "Among test samples whose raw bytes are unseen in training, DOM overlap: **"
                  + metric_text(cohort["extra_dom_overlap"]["test_to_train"]) + "**."]
    lines += ["", "## Label conflicts within normalized DOM groups", "",
              "| Scope | Labeled samples | Mixed-label groups | Samples in conflicting groups | Empirical conflict error |",
              "|---|---:|---:|---|---|"]
    conflicts = summary["dom_conflicts"]
    scopes = [("all", conflicts["all"])]
    scopes += [(f"split: {k}", v) for k, v in conflicts["by_split"].items()]
    scopes += [(f"source: {k}", v) for k, v in conflicts["by_source"].items()]
    for name, item in scopes:
        lines.append(f"| {_md(name)} | {item['labeled_samples']} | {item['mixed_groups']} | "
                     f"{metric_text(item['conflict_samples'])} | {metric_text(item['empirical_error'])} |")
    lines += ["", "## Interpretation", "",
              "- Empirical conflict error is sum of minority-label counts / all labeled samples in that scope. It is an in-sample description, not a generalization bound or a model score.",
              "- Shared DOM does not establish common phishing-kit origin, data leakage, or maliciousness. DOM + hostname is not the full SpecularNet input.",
              "- N/A means an empty denominator or no eligible training samples. No test threshold was selected and no labels were predicted.",
              "- Attributes and text are discarded after parsing; some values can influence HTML tree construction before being discarded.",
              "- CSV formula-like text is prefixed with an apostrophe for safe spreadsheet viewing. Machine identifiers in cases.jsonl are unchanged.",
              "", "## Reproducibility", "", f"Rule: `{summary['rule_version']}`; schema: `{summary['schema_version']}`.",
              "Metadata, limits, input hashes and versions are recorded in `summary.json`.",
              "See `samples.csv`, `groups.csv`, `issues.csv` and `cases.jsonl` for evidence. Previews can be truncated; fingerprints use full accepted inputs.", ""]
    return "\n".join(lines)


def write_report(result: AuditResult, out: Path) -> Path:
    out = Path(out)
    if out.is_symlink() or (out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise ReportError("Output already exists and is not an empty directory. Choose a new --out path.")
    out.parent.mkdir(parents=True, exist_ok=True)
    # Publish the complete bundle in one rename; never leave half a report behind.
    with tempfile.TemporaryDirectory(prefix=".domscope-", dir=out.parent) as temporary:
        stage = Path(temporary)
        summary = {**result.summary, "artifacts": ARTIFACTS.copy()}
        _write_csv(stage / ARTIFACTS["samples"], result.samples)
        _write_csv(stage / ARTIFACTS["groups"], result.groups)
        _write_csv(stage / ARTIFACTS["issues"], result.issues,
                   ("sample_id", "code", "detail", "severity"))
        with (stage / ARTIFACTS["cases"]).open("w", encoding="utf-8", newline="\n") as handle:
            for case in result.cases:
                handle.write(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n")
        (stage / ARTIFACTS["report"]).write_text(markdown_report(summary), encoding="utf-8")
        (stage / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if out.exists():
            out.rmdir()  # Only the previously checked, still-empty directory can be removed.
        os.rename(stage, out)
    return out / "summary.json"
