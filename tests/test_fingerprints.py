"""Representations are compared with literal, hand-constructed HTML cases."""

import hashlib
import json

import pytest


def api():
    from domscope.fingerprints import FingerprintError, fingerprint, parser_metadata

    return FingerprintError, fingerprint, parser_metadata


def test_raw_hash_is_sha256_of_exact_bytes():
    _, fp, _ = api()
    data = b"<!doctype html><p>A</p>"
    result = fp(data)
    assert result["raw_hash"] == hashlib.sha256(data).hexdigest()
    assert result["raw_hash"] != fp(data + b"\n")["raw_hash"]


def test_body_and_attribute_values_are_removed_after_parsing():
    _, fp, _ = api()
    first = fp(b'<p id="first" title="Alpha">One</p>', "a.example")
    second = fp(b'<p title="Beta" id="second">Two<!-- comment --></p>', "a.example")
    assert first["raw_hash"] != second["raw_hash"]
    assert first["dom_hash"] == second["dom_hash"]
    assert first["dom_host_hash"] == second["dom_host_hash"]
    for removed in ("first", "Alpha", "One", "comment"):
        assert removed not in first["canonical"]


@pytest.mark.parametrize("first,second", [
    (b'<p id="a">', b'<p id="a" title="b">'),
    (b'<div><p></p></div>', b'<div></div><p></p>'),
    (b'<div><p></p><span></span></div>', b'<div><span></span><p></p></div>'),
    (b'<svg><a /></svg>', b'<svg></svg><a></a>'),
    (b'<svg><a href="a" /></svg>', b'<svg><a xlink:href="a" /></svg>'),
])
def test_attribute_names_tree_order_parentage_and_namespaces_affect_hash(first, second):
    _, fp, _ = api()
    assert fp(first)["dom_hash"] != fp(second)["dom_hash"]


def test_attribute_value_can_change_tree_construction():
    _, fp, _ = api()
    hidden = fp(b'<table><input type="hidden"></table>')
    text = fp(b'<table><input type="text"></table>')
    assert hidden["dom_hash"] != text["dom_hash"]


def test_namespaces_implicit_nodes_and_counts_are_preserved():
    _, fp, _ = api()
    result = fp(b'<svg><a xlink:href="secret"/></svg>')
    canonical = json.loads(result["canonical"])
    assert canonical["tag"] == "{http://www.w3.org/1999/xhtml}html"
    assert result["element_count"] == 5
    assert result["max_depth"] == 4
    assert "{http://www.w3.org/2000/svg}a" in result["canonical"]
    assert "{http://www.w3.org/1999/xlink}href" in result["canonical"]


def test_script_style_and_unknown_element_nodes_remain_without_text():
    _, fp, _ = api()
    result = fp(b'<x-widget><script>private()</script><style>.secret{}</style></x-widget>')
    assert "x-widget" in result["canonical"]
    assert "script" in result["canonical"]
    assert "style" in result["canonical"]
    assert "private" not in result["canonical"]
    assert "secret" not in result["canonical"]


@pytest.mark.parametrize("hostname,normalized", [("LOGIN.Example.", "login.example"),
    ("bücher.example", "xn--bcher-kva.example"), ("sub.a.example", "sub.a.example")])
def test_hostname_normalizes_without_dropping_subdomains(hostname, normalized):
    _, fp, _ = api()
    result = fp(b'<p>one', hostname)
    assert result["hostname"] == normalized
    assert result["hostname_status"] == "valid"
    assert result["dom_host_hash"] == fp(b'<p>two', normalized)["dom_host_hash"]
    assert result["dom_host_hash"] != fp(b'<p>one', "other.example")["dom_host_hash"]


@pytest.mark.parametrize("hostname,status", [(None, "missing"), ("", "invalid"),
    ("https://example.com", "invalid"), ("example.com:443", "invalid"),
    ("a..example", "invalid"), ("example..", "invalid"), ("a_b.example", "invalid"),
    ("-a.example", "invalid"), ("a-.example", "invalid"), ("127.0.0.1", "invalid"),
    ("[::1]", "invalid"), ("::1", "invalid"), (" a.example", "invalid"),
    ("a" * 64 + ".example", "invalid"), (5, "invalid")])
def test_unavailable_hostname_does_not_create_joint_match(hostname, status):
    _, fp, _ = api()
    result = fp(b'<p>one', hostname)
    assert result["hostname_status"] == status
    assert result["hostname"] is None
    assert result["dom_host_hash"] is None
    assert result["dom_hash"] == fp(b'<p>one')["dom_hash"]


@pytest.mark.parametrize("data", [b"", b" \n\t", b"plain text", b"<!-- <p> -->",
    b"<!doctype html>", b"&lt;p&gt;", b"</p>"])
def test_no_explicit_start_tag_is_excluded(data):
    error, fp, _ = api()
    with pytest.raises(error) as caught:
        fp(data)
    assert caught.value.code == "no-elements"


def test_recoverable_html_has_warning_codes_without_content():
    _, fp, _ = api()
    result = fp(b'<p>PRIVATE</span><p id="one" id="two">')
    assert result["parse_warning_count"] > 0
    assert result["parse_warning_codes"]
    assert all(isinstance(code, str) for code in result["parse_warning_codes"])
    assert "PRIVATE" not in str(result["parse_warning_codes"])


@pytest.mark.parametrize("encoding,data,code", [("utf-8", b'<p>\xffSECRET', "decode-error"),
    ("no-such-codec", b'<p>SECRET', "invalid-encoding"),
    ("", b'<p>SECRET', "invalid-encoding"),
    ("base64_codec", b'<p>SECRET', "invalid-encoding")])
def test_strict_decoding_errors_are_clean(encoding, data, code):
    error, fp, _ = api()
    with pytest.raises(error) as caught:
        fp(data, encoding=encoding)
    assert caught.value.code == code
    assert "SECRET" not in str(caught.value)


def test_explicit_non_utf8_encoding_and_full_content_hash():
    _, fp, _ = api()
    result = fp('<p>café'.encode("latin-1"), encoding="latin-1")
    assert result["raw_preview"] == '<p>café'
    a = fp(('<div>' + 'x' * 4500 + '<p></p></div>').encode())
    b = fp(('<div>' + 'x' * 4500 + '<span></span></div>').encode())
    assert len(a["raw_preview"]) == 4000
    assert a["raw_preview_truncated"] is True
    assert a["raw_preview"] == b["raw_preview"]
    assert a["dom_hash"] != b["dom_hash"]


def test_large_canonical_preview_is_truncated_without_hash_truncation():
    _, fp, _ = api()
    a = fp(b'<div>' + b'<i></i>' * 200 + b'<p></p></div>')
    b = fp(b'<div>' + b'<i></i>' * 200 + b'<span></span></div>')
    assert len(a["dom_preview"]) == 4000
    assert a["dom_preview_truncated"] is True
    assert a["dom_preview"] == b["dom_preview"]
    assert a["dom_hash"] != b["dom_hash"]


def test_node_limit_is_inclusive_and_never_silently_truncates():
    error, fp, _ = api()
    assert fp(b'<p>', max_nodes=4)["element_count"] == 4
    with pytest.raises(error) as caught:
        fp(b'<p>', max_nodes=3)
    assert caught.value.code == "node-limit"


def test_deep_tree_has_nonrecursive_canonical_serialization():
    _, fp, _ = api()
    result = fp(b'<div>' * 1200 + b'</div>' * 1200)
    assert result["element_count"] == 1203
    assert result["max_depth"] == 1202
    assert result["canonical"].count('"tag"') == 1203


def test_metadata_and_repeated_runs_are_deterministic():
    _, fp, metadata = api()
    data = b'<!doctype html><title>A</title><p>One'
    assert fp(data, "a.example") == fp(data, "a.example")
    info = metadata()
    assert info["rule_version"] == "domscope-v1"
    assert info["html5lib_version"]
    assert info["python_version"]
    assert info["tree_builder"] == "etree"
    assert info["namespace_html_elements"] is True
    assert info["scripting"] is False
    assert info["idna"]


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_node_limit_is_explicit(limit):
    error, fp, _ = api()
    with pytest.raises(error) as caught:
        fp(b'<p>', max_nodes=limit)
    assert caught.value.code == "invalid-limit"


def test_invalid_input_type_is_explicit():
    error, fp, _ = api()
    with pytest.raises(error) as caught:
        fp('<p>')
    assert caught.value.code == "invalid-input"
