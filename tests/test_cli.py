"""Exercise real files and the command-line entry point."""
import csv
import json
from pathlib import Path
import subprocess
import sys

import pytest

from domscope.audit import AuditError, audit_manifest
from domscope.report import ReportError, write_report

ROOT = Path(__file__).resolve().parents[1]


def make_manifest(tmp_path, rows=None, html=b'<!doctype html><html><head><title>Demo</title></head><body><p>Hello</p></body></html>'):
    (tmp_path / "page.html").write_bytes(html)
    if rows is None:
        rows = [{"sample_id": "one", "html_path": "page.html", "split": "test",
                 "source": "synthetic", "label": 0, "hostname": "a.example"}]
    path = tmp_path / "manifest.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


def cli(manifest, out, *args):
    return subprocess.run([sys.executable, "-m", "domscope", "audit", "--manifest", str(manifest),
                           "--out", str(out), *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")


def test_cli_exports_a_reproducible_report_and_does_not_overwrite(tmp_path):
    manifest = make_manifest(tmp_path)
    out = tmp_path / "out"
    first = cli(manifest, out)
    assert first.returncode == 0, first.stderr
    report = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert report["counts"] == {"input": 1, "valid": 1, "excluded": 0, "hostname_unavailable": 0}
    assert report["data_kind"] == "synthetic"
    for name in ("samples.csv", "groups.csv", "issues.csv", "cases.jsonl", "report.md"):
        assert (out / name).is_file()
    before = (out / "summary.json").read_bytes()
    repeated = cli(manifest, out)
    assert repeated.returncode != 0
    assert (out / "summary.json").read_bytes() == before
    assert "Traceback" not in repeated.stderr
    second = audit_manifest(manifest)
    assert second.summary["metadata"]["inputs_sha256"] == report["metadata"]["inputs_sha256"]
    assert second.summary["cohorts"] == report["cohorts"]


def test_bad_pages_are_counted_while_recoverable_pages_survive(tmp_path):
    rows = [{"sample_id": name, "html_path": filename, "split": "train", "source": "user", "label": None}
            for name, filename in [("ok", "page.html"), ("missing", "missing.html"), ("large", "large.html"), ("blank", "blank.html")]]
    manifest = make_manifest(tmp_path, rows, html=b"<p>Recover me")
    (tmp_path / "large.html").write_bytes(b"<div>" + b"x" * 500 + b"</div>")
    (tmp_path / "blank.html").write_text(" ", encoding="utf-8")
    result = audit_manifest(manifest, max_bytes=100)
    assert result.summary["counts"] == {"input": 4, "valid": 1, "excluded": 3, "hostname_unavailable": 1}
    assert result.samples[0]["parse_warning_count"] > 0
    assert len([i for i in result.issues if i["severity"] == "excluded"]) == 3
    assert result.samples[0]["dom_host_hash"] is None


def test_all_invalid_and_bad_cli_limits_have_no_success_report(tmp_path):
    manifest = make_manifest(tmp_path, html=b"plain text")
    with pytest.raises(AuditError, match="No valid"):
        audit_manifest(manifest)
    result = cli(manifest, tmp_path / "out")
    assert result.returncode != 0
    assert not (tmp_path / "out" / "summary.json").exists()
    result = cli(manifest, tmp_path / "out", "--max-bytes", "-2")
    assert result.returncode != 0 and "Traceback" not in result.stderr


def test_csv_formulas_escaped_and_no_absolute_paths_in_artifacts(tmp_path):
    rows = [{"sample_id": "one", "html_path": "page.html", "split": "train",
             "source": "=HYPERLINK(\"https://example.invalid\")", "label": 0}]
    result = audit_manifest(make_manifest(tmp_path, rows))
    out = tmp_path / "out"
    write_report(result, out)
    with (out / "samples.csv").open(encoding="utf-8-sig", newline="") as f:
        row = next(csv.DictReader(f))
    assert row["source"].startswith("'=HYPERLINK")
    for item in out.iterdir():
        text = item.read_text(encoding="utf-8-sig")
        assert str(tmp_path) not in text
        assert str(tmp_path).replace("\\", "\\\\") not in text


def test_preview_is_truncated_but_full_content_is_hashed(tmp_path):
    manifest = make_manifest(tmp_path, html=b"<p>" + b"x" * 5000 + b"</p>")
    a = audit_manifest(manifest)
    assert len(a.cases[0]["raw_preview"]) == 4000
    assert a.cases[0]["raw_preview_truncated"] is True
    (tmp_path / "page.html").write_bytes(b"<p>" + b"x" * 5000 + b"</p><hr>")
    b = audit_manifest(manifest)
    assert a.samples[0]["dom_hash"] != b.samples[0]["dom_hash"]


def test_no_training_split_does_not_claim_measured_zero_overlap(tmp_path):
    result = audit_manifest(make_manifest(tmp_path))
    metric = result.summary["cohorts"]["dom"]["representations"]["raw_hash"]["overlap"]["test_to_train"]
    assert metric["denominator"] == 1
    assert metric["value"] is None


def test_demo_matches_the_hand_calculated_acceptance_table(tmp_path):
    run = cli(ROOT / "examples" / "manifest.jsonl", tmp_path / "demo")
    assert run.returncode == 0, run.stderr
    summary = json.loads((tmp_path / "demo" / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["valid"] == 8
    assert summary["cohorts"]["dom"]["representations"]["raw_hash"]["overlap"]["test_to_train"]["value"] == 0.25
    assert summary["cohorts"]["dom"]["representations"]["dom_hash"]["overlap"]["test_to_train"]["value"] == 0.5
    assert summary["cohorts"]["host"]["representations"]["dom_host_hash"]["overlap"]["test_to_train"]["value"] == 0.25
    assert summary["dom_conflicts"]["all"]["empirical_error"]["value"] == 0.125
