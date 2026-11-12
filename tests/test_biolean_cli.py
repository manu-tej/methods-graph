import gzip
import json
import shutil
from pathlib import Path

import pytest

from methods_graph import cli, fetch
from tests.test_biolean_kernel import A, C, GOLDEN, axiom, deriv, prop, prop_step

FIX = Path(__file__).parent / "fixtures" / "biolean"


@pytest.fixture
def store_dir(tmp_path):
    shutil.copy(FIX / "go-mini.obo", tmp_path / "go-basic.obo")
    shutil.copy(FIX / "goa-mini.gaf", tmp_path / "goa_human.gaf")
    shutil.copy(FIX / "eco-mini.txt", tmp_path / "gaf-eco-mapping.txt")
    return tmp_path


def _write(tmp_path, derivation):
    p = tmp_path / "d.json"
    p.write_text(json.dumps(derivation))
    return str(p)


def _sorted_json(text):
    obj = json.loads(text)
    assert text == json.dumps(obj, sort_keys=True, indent=2) + "\n"
    return obj


def test_check_accepted_exits_0_and_prints_sorted_json(store_dir, capsys):
    path = _write(store_dir, deriv(prop(C), [axiom("s1", A), prop_step("s2", "part_of", "s1", A, C)], "s2"))
    rc = cli.main(["biolean", "check", path, "--store", str(store_dir)])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and out["verdict"] == "ACCEPTED"


def test_check_rejected_exits_3_and_render_prints_prose(store_dir, capsys):
    path = _write(store_dir, GOLDEN)
    rc = cli.main(["biolean", "check", path, "--store", str(store_dir)])
    assert rc == 3 and _sorted_json(capsys.readouterr().out)["verdict"] == "REJECTED"
    rc = cli.main(["biolean", "check", path, "--store", str(store_dir), "--render"])
    assert rc == 3 and capsys.readouterr().out.startswith("REJECTED: 9 steps")


def test_check_elaborates_before_checking(store_dir, capsys):
    path = _write(store_dir, deriv(prop("GO:0000011", subject="GA", taxon="9606"),
                                   [axiom("s1", "GO:0000011", subject="GA", taxon="9606")], "s1"))
    rc = cli.main(["biolean", "check", path, "--store", str(store_dir)])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and len(out["elaboration"]) == 6


def test_prove_found_exits_0_and_not_found_exits_3(store_dir, capsys):
    rc = cli.main(["biolean", "prove", "UniProtKB:P00008 involved_in GO:0000010", "--store", str(store_dir)])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and [s["rule"] for s in out["derivation"]["steps"]] == ["axiom", "part_of"]

    # GA has involved_in annotations, but none of them reach GO:0000060 by propagation.
    rc = cli.main(["biolean", "prove", "GA involved_in GO:0000060", "--store", str(store_dir), "--taxon", "9606"])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 3 and out["derivation"] is None and out["reason"] == "no_path"
    assert out["goal"]["subject"] == "UniProtKB:P00001" and out["goal"]["taxon"] == "NCBITaxon:9606"

    # GO:0009999 is not in the mini ontology at all.
    rc = cli.main(["biolean", "prove", "GA involved_in GO:0009999", "--store", str(store_dir)])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 3 and out["reason"] == "unknown_term"

    # GO:0000200 (MF1) is live and enables is aspect-legal for it, but GA has no enables row at all.
    rc = cli.main(["biolean", "prove", "GA enables GO:0000200", "--store", str(store_dir)])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 3 and out["reason"] == "no_direct_annotations"


def test_load_report_is_printed_to_stderr(store_dir, capsys):
    rc = cli.main(["biolean", "goals", "UniProtKB:P00008", "--store", str(store_dir)])
    captured = capsys.readouterr()
    assert rc == 0
    err = json.loads(captured.err)
    assert err["load_report"]["gaf"]["annotations"] == 24
    assert err["load_report"]["gaf"]["bad_column_count"] == 1
    _sorted_json(captured.out)          # stdout stays a single sorted JSON document


def test_goals_lists_direct_and_inferred(store_dir, capsys):
    rc = cli.main(["biolean", "goals", "UniProtKB:P00008", "--store", str(store_dir)])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 0
    assert {(g["prop"]["term"], g["direct"], g["depth"]) for g in out["goals"]} == {
        ("GO:0000030", True, 0), ("GO:0000005", False, 1), ("GO:0000010", False, 1), ("GO:0000020", False, 1)}
    assert out["report"]["skipped_negated"] == 0


def test_goals_rejects_a_malformed_subject_with_a_goals_specific_message(store_dir, capsys):
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "goals", "UniProtKB:P00001 extra", "--store", str(store_dir)])
    assert ex.value.code == 2
    assert "subject" in capsys.readouterr().err


def test_goals_resolves_a_symbol_and_reports_it(store_dir, capsys):
    rc = cli.main(["biolean", "goals", "GA", "--store", str(store_dir)])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 0
    assert out["subject"] == "UniProtKB:P00001"
    assert out["elaboration"][0]["kind"] == "SYMBOL_RESOLVED"


def test_goals_rejects_an_ambiguous_symbol_naming_all_candidates(store_dir, capsys):
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "goals", "DUP", "--store", str(store_dir)])
    assert ex.value.code == 2
    err = capsys.readouterr().err
    assert "UniProtKB:P00008" in err and "UniProtKB:P00009" in err


def test_usage_errors_exit_2(tmp_path, store_dir):
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "goals", "UniProtKB:P00008", "--store", str(tmp_path / "missing")])
    assert ex.value.code == 2
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "prove", "two parts", "--store", str(store_dir)])
    assert ex.value.code == 2
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "prove", "GA involved_in GO:0000010", "--store", str(store_dir), "--taxon", "human"])
    assert ex.value.code == 2
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "check", str(store_dir / "nope.json"), "--store", str(store_dir)])
    assert ex.value.code == 2
    bad_json = store_dir / "bad.json"
    bad_json.write_text("{not json")
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "check", str(bad_json), "--store", str(store_dir)])
    assert ex.value.code == 2


def test_fetch_uses_the_seam_and_writes_the_manifest(tmp_path, monkeypatch, capsys):
    from tests.test_biolean_fetch import _http
    calls = []
    monkeypatch.setattr(fetch, "_stdlib_http_get", _http(calls))
    rc = cli.main(["biolean", "fetch", "--out", str(tmp_path)])
    assert rc == 0 and (tmp_path / "snapshot.json").exists()
    assert "2026-04-27" in calls[1]
    out = _sorted_json(capsys.readouterr().out)
    assert set(out["sources"]) == {"goa_human", "go_basic", "gaf_eco_mapping"}
