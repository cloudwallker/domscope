"""Input-contract tests use temporary data, never user files."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest


def api():
    from domscope.manifest import ManifestError, load_manifest

    return ManifestError, load_manifest


def write_manifest(tmp_path, rows):
    path = tmp_path / "manifest.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def row(**overrides):
    return {"sample_id": "A1", "html_path": "html/a.html", "split": "train",
            "source": "synthetic", **overrides}


def test_valid_manifest_defaults_and_private_resolved_path(tmp_path):
    _, load = api()
    path = write_manifest(tmp_path, [row()])
    sample, = load(path)
    assert (sample.sample_id, sample.split, sample.source) == ("A1", "train", "synthetic")
    assert (sample.label, sample.hostname, sample.encoding) == (None, None, "utf-8")
    assert sample.html_path == "html/a.html"
    assert sample.path == (tmp_path / "html/a.html").resolve()
    assert not sample.path.exists()  # Missing files are a per-sample audit issue.
    with pytest.raises(FrozenInstanceError):
        sample.split = "test"


def test_unicode_source_label_and_encoding_alias(tmp_path):
    _, load = api()
    sample, = load(write_manifest(tmp_path, [row(source="公开数据", label=1,
        hostname="https://invalid.example", encoding="UTF8")]))
    assert sample.source == "公开数据"
    assert sample.label == 1
    assert sample.hostname == "https://invalid.example"  # Validation is in fingerprints.
    assert sample.encoding == "utf-8"


@pytest.mark.parametrize("field,value", [
    ("sample_id", ""), ("sample_id", "../x"), ("sample_id", "=FORMULA"),
    ("sample_id", "x\nprivate"), ("sample_id", "x" * 129), ("sample_id", 1),
    ("html_path", None), ("html_path", ""), ("html_path", 1),
    ("source", ""), ("source", "   "), ("source", 1), ("source", "x\x00"),
    ("split", "validation"), ("split", None), ("split", []),
    ("label", True), ("label", False), ("label", 1.0), ("label", 2), ("label", "0"),
    ("hostname", 5), ("hostname", []),
    ("encoding", ""), ("encoding", "unknown-codec"), ("encoding", None),
    ("encoding", "base64_codec"),
])
def test_invalid_fields_stop_manifest_with_line_without_value(tmp_path, field, value):
    error, load = api()
    with pytest.raises(error) as caught:
        load(write_manifest(tmp_path, [row(**{field: value})]))
    assert "1" in str(caught.value)
    assert str(tmp_path) not in str(caught.value)


@pytest.mark.parametrize("field", ["sample_id", "html_path", "split", "source"])
def test_required_fields(tmp_path, field):
    error, load = api()
    item = row()
    del item[field]
    with pytest.raises(error):
        load(write_manifest(tmp_path, [item]))


@pytest.mark.parametrize("relative", ["../outside.html", "html/../../outside.html",
    "/absolute.html", "C:/absolute.html", "C:relative.html", "\\\\server\\share\\a.html",
    "html/a.html:secret", "html/secret\x00.html", "html/secret\n.html"])
def test_paths_cannot_escape_or_use_windows_special_forms(tmp_path, relative):
    error, load = api()
    with pytest.raises(error) as caught:
        load(write_manifest(tmp_path, [row(html_path=relative)]))
    assert str(tmp_path) not in str(caught.value)


def test_symlink_resolved_outside_is_rejected(tmp_path):
    error, load = api()
    data = tmp_path / "data"
    data.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text("<p>private", encoding="utf-8")
    link = data / "alias.html"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Operating system does not permit unprivileged symlinks")
    with pytest.raises(error):
        load(write_manifest(data, [row(html_path="alias.html")]))


def test_duplicate_ids_and_sample_limit(tmp_path):
    error, load = api()
    with pytest.raises(error, match="2"):
        load(write_manifest(tmp_path, [row(), row()]))
    with pytest.raises(error):
        load(write_manifest(tmp_path, [row(), row(sample_id="A2")]), max_samples=1)


@pytest.mark.parametrize("text", ["", "  \n", "{broken secret}", "[]", "null", "\"private\""])
def test_empty_or_non_object_manifest_is_clean_error(tmp_path, text):
    error, load = api()
    path = tmp_path / "manifest.jsonl"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(error) as caught:
        load(path)
    assert "secret" not in str(caught.value)
    assert str(path) not in str(caught.value)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_sample_limit(tmp_path, limit):
    error, load = api()
    with pytest.raises(error):
        load(write_manifest(tmp_path, [row()]), max_samples=limit)


def test_read_errors_do_not_disclose_paths(tmp_path):
    error, load = api()
    with pytest.raises(error) as caught:
        load(tmp_path / "missing-secret.jsonl")
    assert "missing-secret" not in str(caught.value)
    assert str(tmp_path) not in str(caught.value)


@pytest.mark.parametrize("relative", ["NUL", "html/CON.html", "aux.txt", "COM1",
    "lpt9.html", "html/trailing. ", "html/wild*.html", "html/question?.html"])
def test_windows_device_names_and_aliasing_paths_are_rejected(tmp_path, relative):
    error, load = api()
    with pytest.raises(error):
        load(write_manifest(tmp_path, [row(html_path=relative)]))


def test_duplicate_json_keys_are_not_silently_overwritten(tmp_path):
    error, load = api()
    path = tmp_path / "manifest.jsonl"
    path.write_text('{"sample_id":"A1","sample_id":"A2",'
                    '"html_path":"a.html","split":"train","source":"synthetic"}',
                    encoding="utf-8")
    with pytest.raises(error):
        load(path)


def test_lone_surrogate_metadata_cannot_break_report_encoding(tmp_path):
    error, load = api()
    with pytest.raises(error):
        load(write_manifest(tmp_path, [row(source="private\ud800")]))
