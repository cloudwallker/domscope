import json
from pathlib import Path
import sys

import pytest

from domscope.audit import audit_manifest
from domscope.audit import AuditResult, summarize
from domscope.report import ReportError, write_report
from domscope.viewer import load_bundle

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bundle(tmp_path):
    return write_report(audit_manifest(ROOT / "examples/manifest.jsonl"), tmp_path / "report")


def test_bundle_loads_all_evidence_with_typed_values(bundle):
    data = load_bundle(bundle)
    assert len(data["samples"]) == len(data["cases"]) == 8
    assert {s["sample_id"] for s in data["samples"] if s["dom_only_seen_in_train"]} == {"A3"}
    assert data["summary"]["counts"]["valid"] == 8
    assert len(data["groups"]) == 5


@pytest.mark.parametrize("mutation", ["path", "version", "missing", "case_ids"])
def test_viewer_rejects_invalid_or_escaping_bundle(bundle, mutation):
    summary = json.loads(bundle.read_text(encoding="utf-8"))
    if mutation == "path":
        summary["artifacts"]["cases"] = "../outside.jsonl"
    elif mutation == "version":
        summary["schema_version"] = "future-report"
    elif mutation == "missing":
        (bundle.parent / "cases.jsonl").unlink()
    else:
        (bundle.parent / "cases.jsonl").write_text('{"sample_id":"wrong"}\n', encoding="utf-8")
    bundle.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ReportError):
        load_bundle(bundle)


def test_app_renders_real_metrics_and_inert_source_then_switches_language(bundle, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(sys, "argv", ["app.py", "--report", str(bundle)])
    app = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    assert not app.exception
    assert [m.value for m in app.metric][:4] == ["8", "0", "5", "1"]
    assert len(app.tabs) == 3
    assert any("<!doctype html>" in c.value.lower() for c in app.code)
    app.sidebar.selectbox(key="language").select("English").run()
    assert not app.exception
    assert "Overview" in [t.label for t in app.tabs]
    app.checkbox(key="dom_only").uncheck().run()
    app.selectbox(key="sample").select("A4").run()
    assert not app.exception
    assert any("A4" in text.value for text in app.caption)


def test_missing_report_shows_start_instructions_not_exception(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(sys, "argv", ["app.py", "--report", str(tmp_path / "none.json")])
    app = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    assert not app.exception
    assert app.info
    assert any("python -m domscope audit" in c.value for c in app.code)


def large_bundle(tmp_path, count, unicode_preview=False):
    html = "<!doctype html><main>" + ("\u6c49" * 4000 if unicode_preview else "hello") + "<i></i>" * 65 + "</main>"
    (tmp_path / "page.html").write_text(html, encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps({"sample_id": "seed", "html_path": "page.html", "split": "train",
                                    "label": 0, "source": "synthetic", "hostname": "a.example"}), encoding="utf-8")
    seed = audit_manifest(manifest)
    ids = [f"sample-{i:06d}-" + "x" * 100 for i in range(count)]
    samples = [{**seed.samples[0], "sample_id": sid} for sid in ids]
    cases = [{**seed.cases[0], "sample_id": sid} for sid in ids]
    group = {**seed.groups[0], "size": count, "benign": count, "sample_ids": ids}
    summary = {**seed.summary, **summarize(samples), "counts": {"input": count, "valid": count, "excluded": 0, "hostname_unavailable": 0}}
    return write_report(AuditResult(summary, samples, [group], [], cases), tmp_path / "large")


def test_large_valid_duplicate_group_exceeds_csv_default_field_limit(tmp_path):
    report = large_bundle(tmp_path, 1500)
    assert (report.parent / "groups.csv").stat().st_size > 131072
    data = load_bundle(report)
    assert len(data["samples"]) == 1500
    assert len(data["groups"][0]["sample_ids"]) == 1500


def test_default_5000_sample_unicode_previews_are_viewable(tmp_path):
    report = large_bundle(tmp_path, 5000, unicode_preview=True)
    assert (report.parent / "cases.jsonl").stat().st_size > 64 * 1024 * 1024
    data = load_bundle(report)
    assert len(data["cases"]) == 5000


@pytest.mark.parametrize("keys", [("counts", "excluded"), ("cohorts", "host"), ("metadata",), ("dom_conflicts", "by_split")])
def test_incomplete_summary_is_rejected_before_rendering(bundle, keys):
    summary = json.loads(bundle.read_text(encoding="utf-8"))
    target = summary
    for key in keys[:-1]:
        target = target[key]
    del target[keys[-1]]
    bundle.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ReportError):
        load_bundle(bundle)
