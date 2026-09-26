"""Hand-derived counts catch denominator and group-counting errors."""
from copy import deepcopy

import pytest

from domscope.audit import summarize


def record(sid, split, label, raw, dom, host="a.example", source="synthetic"):
    return dict(sample_id=sid, split=split, label=label, source=source,
                raw_hash=raw, dom_hash=dom, hostname=host,
                dom_host_hash=f"{dom}|{host}" if host else None)


def eight():
    return [
        record("A1", "train", 0, "R1", "D1"),
        record("A2", "train", 0, "R2", "D1", "b.example"),
        record("B1", "train", 0, "R3", "D2", "docs.example"),
        record("C1", "train", 1, "R4", "D3", "c.example"),
        record("A3", "test", 1, "R5", "D1", "other.example"),
        record("A4", "test", 0, "R1", "D1"),
        record("D1", "test", 1, "R6", "D4", "new.example"),
        record("E1", "test", 0, "R7", "D5", "help.example"),
    ]


def assert_ratio(r, n, d):
    assert r == dict(numerator=n, denominator=d, value=n / d if d else None)


def test_eight_sample_known_counts():
    result = summarize(eight())
    dom, host = result["cohorts"]["dom"], result["cohorts"]["host"]
    assert dom["size"] == host["size"] == 8
    assert_ratio(dom["representations"]["raw_hash"]["overlap"]["test_to_train"], 1, 4)
    assert_ratio(dom["representations"]["dom_hash"]["overlap"]["test_to_train"], 2, 4)
    assert_ratio(host["representations"]["dom_host_hash"]["overlap"]["test_to_train"], 1, 4)
    assert_ratio(dom["extra_dom_overlap"]["test_to_train"], 1, 3)
    conflicts = result["dom_conflicts"]["all"]
    assert conflicts["mixed_groups"] == 1
    assert_ratio(conflicts["empirical_error"], 1, 8)
    assert_ratio(conflicts["conflict_samples"], 4, 8)
    rep = dom["representations"]["dom_hash"]
    assert_ratio(rep["redundant_samples"], 3, 8)
    assert_ratio(rep["duplicate_group_samples"], 4, 8)


def test_missing_host_uses_same_cohort_for_all_three_representations():
    rows = eight()
    rows[4]["hostname"] = rows[4]["dom_host_hash"] = None
    result = summarize(rows)
    assert result["cohorts"]["dom"]["size"] == 8
    host = result["cohorts"]["host"]
    assert host["size"] == 7
    for rep in host["representations"].values():
        assert_ratio(rep["overlap"]["test_to_train"], 1, 3)


def test_training_copies_do_not_multiply_matched_test_samples():
    rows = eight()
    for i in range(5):
        clone = deepcopy(rows[0])
        clone["sample_id"] = f"copy-{i}"
        rows.append(clone)
    rep = summarize(rows)["cohorts"]["dom"]["representations"]
    assert_ratio(rep["raw_hash"]["overlap"]["test_to_train"], 1, 4)
    assert_ratio(rep["dom_hash"]["overlap"]["test_to_train"], 2, 4)


def test_conflict_denominator_excludes_unknown_labels_not_pure_groups():
    rows = []
    for group, labels in enumerate(([0, 0, 0, 1], [0, 1, 1], [0, 0])):
        for i, label in enumerate(labels):
            rows.append(record(f"{group}-{i}", "train", label, f"r{group}-{i}", str(group)))
    rows.append(record("unknown", "train", None, "r?", "0"))
    c = summarize(rows)["dom_conflicts"]["all"]
    assert c["labeled_samples"] == 9
    assert c["mixed_groups"] == 2
    assert_ratio(c["empirical_error"], 2, 9)
    assert_ratio(c["conflict_samples"], 7, 9)


def test_zero_denominator_is_null_and_scopes_do_not_share_majorities():
    result = summarize(eight())
    assert_ratio(result["cohorts"]["dom"]["extra_dom_overlap"]["val_to_train"], 0, 0)
    assert_ratio(result["dom_conflicts"]["by_split"]["train"]["empirical_error"], 0, 4)
    assert_ratio(result["dom_conflicts"]["by_split"]["test"]["empirical_error"], 1, 4)
    empty = summarize([])
    assert_ratio(empty["dom_conflicts"]["all"]["empirical_error"], 0, 0)
    assert_ratio(empty["cohorts"]["host"]["representations"]["dom_host_hash"]["overlap"]["test_to_train"], 0, 0)


def test_source_conflicts_use_only_labels_in_that_source():
    rows = [record("a", "train", 0, "a", "d", source="one"),
            record("b", "test", 1, "b", "d", source="two")]
    c = summarize(rows)["dom_conflicts"]
    assert_ratio(c["all"]["empirical_error"], 1, 2)
    assert_ratio(c["by_source"]["one"]["empirical_error"], 0, 1)
    assert_ratio(c["by_source"]["two"]["empirical_error"], 0, 1)
