"""One test per subcommand over the fixture store: exit code, sorted JSON, refusals."""
import json
import threading
import time

import pytest

from methods_graph import cli
from tests.biolean_fixture import RELEASE, copy_store


@pytest.fixture
def store_dir(tmp_path):
    return copy_store(tmp_path / "store")


@pytest.fixture
def bench_dir(tmp_path, store_dir, capsys):
    out = tmp_path / "bench"
    rc = cli.main(["biolean", "bench", "build", "--out", str(out), "--store", str(store_dir)])
    assert rc == 0
    capsys.readouterr()
    return out


def _sorted_json(text):
    obj = json.loads(text)
    assert text == json.dumps(obj, sort_keys=True, indent=2) + "\n"
    return obj


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_build_writes_the_item_set_and_prints_the_manifest(tmp_path, store_dir, capsys):
    out = tmp_path / "b"
    rc = cli.main(["biolean", "bench", "build", "--out", str(out), "--store", str(store_dir),
                   "--per-track", "3", "--seed", "7"])
    captured = capsys.readouterr()
    assert rc == 0
    manifest = _sorted_json(captured.out)
    assert manifest == json.loads((out / "manifest.json").read_text())
    assert manifest["release"] == RELEASE and manifest["seed"] == 7 and manifest["per_track"] == 3
    assert manifest["prove"]["sampled"] == 3 and manifest["hypothesize"]["sampled"] == 3
    assert (out / "modal.json").exists() and (out / "items" / "prove.json").exists()
    assert json.loads(captured.err)["load_report"]["gaf"]["annotations"] == 24


def test_since_must_be_a_date_and_is_recorded(tmp_path, store_dir, capsys):
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "bench", "build", "--out", str(tmp_path / "x"), "--store", str(store_dir),
                  "--since", "2020"])
    assert ex.value.code == 2 and "--since" in capsys.readouterr().err
    rc = cli.main(["biolean", "bench", "build", "--out", str(tmp_path / "y"), "--store", str(store_dir),
                   "--since", "2020-01-01"])
    manifest = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and manifest["since"] == "2020-01-01"
    assert manifest["prove"]["excluded_by_since"] == 1 and manifest["hypothesize"]["excluded_by_since"] == 1


def test_coverage_prints_the_manifest_and_a_missing_item_set_exits_2(tmp_path, bench_dir, capsys):
    rc = cli.main(["biolean", "bench", "coverage", "--items", str(bench_dir)])
    out = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and out["population"]["triples"] == 13 and out["prove"]["not_rederivable"] == 7
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "bench", "coverage", "--items", str(tmp_path / "nope")])
    assert ex.value.code == 2


def test_run_gold_hits_every_prove_item_and_writes_one_row_per_item(tmp_path, store_dir, bench_dir, capsys):
    results = tmp_path / "r.jsonl"
    rc = cli.main(["biolean", "bench", "run", "--model", "gold:", "--track", "prove", "--items", str(bench_dir),
                   "--store", str(store_dir), "--out", str(results), "--db", str(tmp_path / "no.kuzu")])
    summary = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and summary["prove"]["hit_rate"] == 1.0 and summary["prove"]["n"] == 6
    assert summary["release"] == RELEASE
    rows = _rows(results)
    assert len(rows) == 6 and all(r["model"] == "gold:" and r["hit"] for r in rows)
    for line in results.read_text().splitlines():
        assert line == json.dumps(json.loads(line), sort_keys=True)
    rc = cli.main(["biolean", "bench", "run", "--model", "gold:", "--track", "prove", "--items", str(bench_dir),
                   "--store", str(store_dir), "--out", str(results), "--limit", "2", "--db", str(tmp_path / "no.kuzu")])
    assert rc == 0 and len(_rows(results)) == 2


def test_run_template_saturates_hypothesize_and_method_resolves_needs_a_graph(tmp_path, store_dir, bench_dir, capsys):
    results = tmp_path / "h.jsonl"
    base = ["biolean", "bench", "run", "--model", "template:", "--track", "hypothesize", "--items", str(bench_dir),
            "--store", str(store_dir), "--out", str(results)]
    rc = cli.main(base + ["--db", str(tmp_path / "no.kuzu")])
    summary = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and summary["hypothesize"]["n"] == 13
    assert summary["hypothesize"]["format_ok"] == {"n": 13, "rate": 1.0}
    assert summary["hypothesize"]["method_resolves"] == {"n": 0, "rate": None}     # no graph: undefined
    assert summary["hypothesize"]["n_method_resolves_none"] == 13
    assert not {"hit", "hit_rate", "accepted"} & set(summary["hypothesize"])
    oracle = tmp_path / "oracle.json"
    oracle.write_text(json.dumps({"methods": ["m:deseq2"]}))
    rc = cli.main(base + ["--db", str(tmp_path / "no.kuzu"), "--oracle-json", str(oracle)])
    summary = _sorted_json(capsys.readouterr().out)
    assert rc == 0 and summary["hypothesize"]["method_resolves"] == {"n": 13, "rate": 1.0}


def test_random_and_modal_baselines_run_end_to_end(tmp_path, store_dir, bench_dir, capsys):
    for spec, expect in (("random:0", None), ("modal:", {"AXIOM_NOT_FOUND": 6})):
        rc = cli.main(["biolean", "bench", "run", "--model", spec, "--track", "prove", "--items", str(bench_dir),
                       "--store", str(store_dir), "--out", str(tmp_path / "x.jsonl"), "--db", str(tmp_path / "no")])
        summary = _sorted_json(capsys.readouterr().out)
        assert rc == 0 and summary["prove"]["n"] == 6
        if expect is None:
            assert set(summary["prove"]["error_items"]) <= {"ROOT_MISMATCH"}
        else:
            assert summary["prove"]["error_items"] == expect and summary["prove"]["hit_rate"] == 0.0


def test_run_baseline_on_the_wrong_track_exits_2(tmp_path, store_dir, bench_dir, capsys):
    for extra in (["--model", "gold:"], ["--model", "template:", "--track", "prove"],
                  ["--model", "random:x", "--track", "prove"], ["--model", "nope:1", "--track", "prove"]):
        with pytest.raises(SystemExit) as ex:
            cli.main(["biolean", "bench", "run", *extra, "--items", str(bench_dir), "--store", str(store_dir),
                      "--out", str(tmp_path / "x.jsonl"), "--db", str(tmp_path / "no")])
        assert ex.value.code == 2, extra
        capsys.readouterr()


def test_run_and_score_refuse_a_mismatched_store_release(tmp_path, store_dir, bench_dir, capsys):
    other = copy_store(tmp_path / "other")
    obo = other / "go-basic.obo"
    obo.write_text(obo.read_text().replace("releases/2026-01-01", "releases/2026-02-02"))
    results = tmp_path / "r.jsonl"
    run = ["biolean", "bench", "run", "--model", "gold:", "--track", "prove", "--items", str(bench_dir),
           "--out", str(results), "--db", str(tmp_path / "no")]
    with pytest.raises(SystemExit) as ex:
        cli.main(run + ["--store", str(other)])
    assert ex.value.code == 2 and "release" in capsys.readouterr().err
    assert cli.main(run + ["--store", str(store_dir)]) == 0
    capsys.readouterr()
    score = ["biolean", "bench", "score", "--results", str(results), "--db", str(tmp_path / "no")]
    with pytest.raises(SystemExit) as ex:
        cli.main(score + ["--store", str(other)])
    assert ex.value.code == 2 and "release" in capsys.readouterr().err
    rescored = tmp_path / "rescored.jsonl"
    assert cli.main(score + ["--store", str(store_dir), "--out", str(rescored)]) == 0
    summary = _sorted_json(capsys.readouterr().out)
    assert summary["prove"]["hit_rate"] == 1.0 and summary["since"] is None
    assert rescored.read_text() == results.read_text()


def test_score_refuses_an_unreadable_results_file(tmp_path, store_dir, capsys):
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n")
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "bench", "score", "--results", str(bad), "--store", str(store_dir),
                  "--db", str(tmp_path / "no")])
    assert ex.value.code == 2
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "bench", "score", "--results", str(tmp_path / "missing.jsonl"),
                  "--store", str(store_dir), "--db", str(tmp_path / "no")])
    assert ex.value.code == 2


def test_score_refuses_pooled_rows_with_incompatible_manifests_models_or_none(tmp_path, store_dir, capsys):
    base_row = {"item": "prove/x", "track": "prove", "model": "gold:",
                "items_manifest": {"release": RELEASE, "since": None}}

    def _write(path, rows):
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    since_mismatch = tmp_path / "since.jsonl"
    _write(since_mismatch, [base_row, {**base_row, "items_manifest": {"release": RELEASE, "since": "2020-01-01"}}])
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "bench", "score", "--results", str(since_mismatch), "--store", str(store_dir),
                  "--db", str(tmp_path / "no.kuzu")])
    assert ex.value.code == 2 and "items_manifest" in capsys.readouterr().err

    model_mismatch = tmp_path / "model.jsonl"
    _write(model_mismatch, [base_row, {**base_row, "model": "openai:gpt-4o"}])
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "bench", "score", "--results", str(model_mismatch), "--store", str(store_dir),
                  "--db", str(tmp_path / "no.kuzu")])
    assert ex.value.code == 2 and "model" in capsys.readouterr().err

    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    with pytest.raises(SystemExit) as ex:
        cli.main(["biolean", "bench", "score", "--results", str(empty), "--store", str(store_dir),
                  "--db", str(tmp_path / "no.kuzu")])
    assert ex.value.code == 2 and "no rows" in capsys.readouterr().err


@pytest.mark.parametrize("case", ["negative_limit", "per_track_zero", "oracle_missing", "oracle_malformed"])
def test_bad_arguments_exit_2(tmp_path, store_dir, bench_dir, capsys, case):
    if case == "negative_limit":
        argv = ["biolean", "bench", "run", "--model", "gold:", "--track", "prove", "--items", str(bench_dir),
                "--store", str(store_dir), "--out", str(tmp_path / "r.jsonl"), "--limit", "-1",
                "--db", str(tmp_path / "no.kuzu")]
    elif case == "per_track_zero":
        argv = ["biolean", "bench", "build", "--out", str(tmp_path / "b"), "--store", str(store_dir),
                "--per-track", "0"]
    else:
        oracle = tmp_path / (f"{case}.json")
        if case == "oracle_malformed":
            oracle.write_text("{not json")
        # else: leave the path missing entirely.
        argv = ["biolean", "bench", "run", "--model", "gold:", "--items", str(bench_dir),
                "--store", str(store_dir), "--out", str(tmp_path / f"{case}.jsonl"),
                "--db", str(tmp_path / "no.kuzu"), "--oracle-json", str(oracle)]
    with pytest.raises(SystemExit) as ex:
        cli.main(argv)
    assert ex.value.code == 2, case


def test_missing_store_exits_2_for_every_store_taking_subcommand(tmp_path, bench_dir):
    missing = str(tmp_path / "nostore")
    for argv in (["build", "--out", str(tmp_path / "b")],
                 ["run", "--model", "gold:", "--items", str(bench_dir), "--out", str(tmp_path / "r")],
                 ["score", "--results", str(tmp_path / "r")]):
        with pytest.raises(SystemExit) as ex:
            cli.main(["biolean", "bench", *argv, "--store", missing])
        assert ex.value.code == 2, argv


# ---------------------------------------------------------------------------
# --workers and --resume
# ---------------------------------------------------------------------------

def _run_argv(tmp_path, store_dir, bench_dir, out, *extra):
    return ["biolean", "bench", "run", "--items", str(bench_dir), "--store", str(store_dir),
            "--out", str(out), "--db", str(tmp_path / "no.kuzu"), *extra]


def _later_items_finish_first(monkeypatch):
    """Slow every baseline call by its distance from the end, so parallel calls complete in
    reverse item order and the streamed file is out of order until the post-run rewrite."""
    from methods_graph.biolean.bench import baselines as baselines_module
    from methods_graph.biolean.bench.render import render_prompt
    real_baseline = baselines_module.baseline_adapter

    def _slowed_baseline(spec, items, *args, **kwargs):
        adapter, index = real_baseline(spec, items, *args, **kwargs), {}
        for i, item in enumerate(items):
            index[render_prompt(item)] = i

        def _slowed(prompt):
            time.sleep(0.02 * (len(items) - index[prompt]))
            return adapter(prompt)
        return _slowed
    monkeypatch.setattr(baselines_module, "baseline_adapter", _slowed_baseline)


def test_workers_gives_byte_identical_output_to_sequential(tmp_path, store_dir, bench_dir, capsys, monkeypatch):
    # Mutations checked: the CLI does not pass --workers through to run_items -> fails (the
    # recorded worker counts are [1, 1]); drop the item-order rewrite after a parallel run ->
    # fails, the file keeps the completion order the sleeps force (later items first).
    from methods_graph.biolean.bench import run as run_module
    real, workers_seen = run_module.run_items, []

    def _spy(*args, **kwargs):
        workers_seen.append(kwargs.get("workers", 1))
        return real(*args, **kwargs)
    monkeypatch.setattr(run_module, "run_items", _spy)
    _later_items_finish_first(monkeypatch)

    sequential, parallel = tmp_path / "seq.jsonl", tmp_path / "par.jsonl"
    for out, workers in ((sequential, "1"), (parallel, "3")):
        rc = cli.main(_run_argv(tmp_path, store_dir, bench_dir, out,
                                "--model", "gold:", "--track", "prove", "--workers", workers))
        summary = _sorted_json(capsys.readouterr().out)
        assert rc == 0 and summary["prove"]["hit_rate"] == 1.0 and summary["n_rows"] == 6
    assert workers_seen == [1, 3]
    assert parallel.read_bytes() == sequential.read_bytes()


@pytest.mark.parametrize("workers", ["1", "3"])
def test_resume_keeps_paid_rows_and_retries_errors(tmp_path, store_dir, bench_dir, capsys, workers):
    # --resume --workers 8 is the restart command a stopped paid run is given; with workers > 1
    # the kept rows reach the final file only through the post-run item-order rewrite.
    # Mutations checked: --resume re-runs every item (ignores the kept ids) -> fails (the
    # marked item appears twice and the file holds 8 rows, not 6); the post-run rewrite writes
    # only the new rows (`rows`, not `kept + rows`) -> the workers=3 case fails (3 rows on disk).
    from methods_graph.biolean.bench.score import failure_row
    results = tmp_path / "r.jsonl"
    base = _run_argv(tmp_path, store_dir, bench_dir, results, "--model", "gold:", "--track", "prove")
    assert cli.main(base + ["--limit", "3"]) == 0
    capsys.readouterr()
    rows = _rows(results)
    assert len(rows) == 3
    marked, errored = rows[0]["item"], rows[1]["item"]
    rows[0] = {**rows[0], "raw": rows[0]["raw"] + " "}        # proves row 0 is kept, not re-called
    item = {"id": rows[1]["item"], "track": rows[1]["track"], "goal": rows[1]["goal"],
            "hidden": rows[1]["hidden"], "hidden_classes": rows[1]["hidden_classes"],
            "gold_depth": rows[1]["gold_depth"]}
    rows[1] = {**failure_row(item, error="rate limited", render_error=None),
               "model": rows[1]["model"], "items_manifest": rows[1]["items_manifest"]}
    results.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))

    rc = cli.main(base + ["--resume", "--workers", workers])
    summary = _sorted_json(capsys.readouterr().out)
    assert rc == 0
    final = _rows(results)
    ids = [r["item"] for r in final]
    assert len(final) == 6 and len(set(ids)) == 6
    assert all(r["error"] is None and r["hit"] is True for r in final)
    assert errored in ids                                      # the error row was retried
    [kept] = [r for r in final if r["item"] == marked]
    assert kept["raw"].endswith(" ")
    assert summary["n_rows"] == 6 == len(results.read_text().splitlines())
    assert summary["prove"]["hit_rate"] == 1.0 and summary["n_errors"] == 0


def test_resume_refuses_a_different_model_or_item_set(tmp_path, store_dir, bench_dir, capsys):
    # Mutations checked: drop the model comparison -> the random:0 case exits 0 and fails;
    # drop the items_manifest comparison -> the since case exits 0 and fails.
    results = tmp_path / "r.jsonl"
    assert cli.main(_run_argv(tmp_path, store_dir, bench_dir, results, "--model", "gold:", "--track", "prove")) == 0
    capsys.readouterr()
    original = results.read_text()
    with pytest.raises(SystemExit) as ex:
        cli.main(_run_argv(tmp_path, store_dir, bench_dir, results,
                           "--model", "random:0", "--track", "prove", "--resume"))
    assert ex.value.code == 2 and "--resume" in (err := capsys.readouterr().err) and "model" in err
    assert results.read_text() == original                      # a refusal rewrites nothing

    rows = _rows(results)
    moved = [{**r, "items_manifest": {**r["items_manifest"], "since": "2020-01-01"}} for r in rows]
    results.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in moved))
    with pytest.raises(SystemExit) as ex:
        cli.main(_run_argv(tmp_path, store_dir, bench_dir, results,
                           "--model", "gold:", "--track", "prove", "--resume"))
    assert ex.value.code == 2 and "--resume" in (err := capsys.readouterr().err) and "items_manifest" in err


def test_resume_refuses_rows_from_another_item_sample(tmp_path, store_dir, capsys):
    # items_manifest holds only release and since, so two samples drawn from one store with
    # different seeds agree on it; the item ids are what differ.
    # Mutation checked: drop the not-in-this-item-set refusal -> fails (the resume exits 0 and
    # pools a row of sample A into sample B's summary).
    samples = {}
    for name, seed in (("A", "1"), ("B", "2")):
        assert cli.main(["biolean", "bench", "build", "--out", str(tmp_path / name), "--store", str(store_dir),
                         "--per-track", "3", "--seed", seed]) == 0
        samples[name] = {item["id"] for item in
                         json.loads((tmp_path / name / "items" / "prove.json").read_text())}
    capsys.readouterr()
    assert samples["A"] - samples["B"], "the fixture must give two different samples"
    results = tmp_path / "r.jsonl"

    def _argv(sample, *extra):
        return _run_argv(tmp_path, store_dir, tmp_path / sample, results, "--model", "gold:", "--track",
                         "prove", *extra)
    assert cli.main(_argv("A")) == 0
    capsys.readouterr()
    original = results.read_text()
    with pytest.raises(SystemExit) as ex:
        cli.main(_argv("B", "--resume"))
    err = capsys.readouterr().err
    assert ex.value.code == 2 and "not in the current --items" in err
    assert results.read_text() == original                      # a refusal rewrites nothing

    # A narrower --limit over the same set is not another sample: its extra rows are kept.
    assert cli.main(_argv("A", "--resume", "--limit", "1")) == 0
    captured = capsys.readouterr()
    resume = next(json.loads(line)["resume"] for line in captured.err.splitlines() if '"resume"' in line)
    assert resume["kept_outside_selection"] == 2 and resume["to_run"] == 0
    assert _sorted_json(captured.out)["n_rows"] == 3 and results.read_text() == original


def test_resume_keeps_the_rows_of_a_track_left_out(tmp_path, store_dir, bench_dir, capsys):
    # A both-track run resumed with --track prove is the same item set, narrowed: its
    # hypothesize rows are kept, not refused as another sample's.
    # Mutation checked: take the item-set ids after the --track filter -> fails (exit 2, "not
    # in the current --items").
    static = tmp_path / "static.json"
    static.write_text(json.dumps(["{}"] * 100))
    results = tmp_path / "r.jsonl"
    argv = _run_argv(tmp_path, store_dir, bench_dir, results, "--model", f"static:{static}")
    assert cli.main(argv) == 0
    capsys.readouterr()
    original = results.read_text()
    tracks = [r["track"] for r in _rows(results)]
    assert tracks.count("prove") and tracks.count("hypothesize")
    assert cli.main(argv + ["--resume", "--track", "prove"]) == 0
    captured = capsys.readouterr()
    resume = next(json.loads(line)["resume"] for line in captured.err.splitlines() if '"resume"' in line)
    assert resume["kept_outside_selection"] == tracks.count("hypothesize") and resume["to_run"] == 0
    assert results.read_text() == original


def test_parallel_reorder_follows_a_symlink_and_skips_a_non_file(tmp_path, store_dir, bench_dir, capsys,
                                                                 monkeypatch):
    # The item-order rewrites (post-run with --workers > 1, pre-run with --resume) stage a temp
    # file beside --out and replace it. A link must survive with its target rewritten (as
    # open() follows it), and /dev/null must not fail the run.
    # Mutations checked: drop the resolve() in _replace_atomically -> fails (the link becomes
    # a regular file); skip the post-run rewrite for a symlink -> fails (the target keeps the
    # reversed completion order the sleeps force); drop the post-run is_file() guard -> fails
    # (staging in /dev raises; the fallback warns "left in completion order"); drop the pre-run
    # --resume is_file() guard -> fails (PermissionError staging in /dev).
    _later_items_finish_first(monkeypatch)
    (tmp_path / "runs").mkdir()
    target, link = tmp_path / "runs" / "dated.jsonl", tmp_path / "latest.jsonl"
    link.symlink_to(target)
    sequential = tmp_path / "seq.jsonl"
    for out, extra in ((sequential, ["--workers", "1"]), (link, ["--workers", "3"]),
                       (link, ["--workers", "3", "--resume"]), ("/dev/null", ["--workers", "3"]),
                       ("/dev/null", ["--workers", "3", "--resume"])):
        rc = cli.main(_run_argv(tmp_path, store_dir, bench_dir, out, "--model", "gold:", "--track", "prove",
                                *extra))
        captured = capsys.readouterr()
        assert rc == 0 and _sorted_json(captured.out)["n_rows"] == 6
        assert "left in completion order" not in captured.err
        assert link.is_symlink() and link.resolve() == target.resolve()
        if out == link:
            assert target.read_bytes() == sequential.read_bytes()


def test_interrupted_parallel_run_says_it_is_waiting_for_calls_in_flight(tmp_path, store_dir, bench_dir,
                                                                        capsys, monkeypatch):
    # Both calls must be running before item 0 fails: a call still queued at that moment is
    # cancelled, not drained, so there is nothing to wait for. On CI's runner the second worker
    # had not dequeued item 1 yet and the notice never printed.
    # Mutation checked: the CLI does not pass on_drain to run_items -> fails (no notice).
    from methods_graph.biolean.bench import baselines as baselines_module
    from methods_graph.biolean.bench.render import render_prompt
    real_baseline = baselines_module.baseline_adapter
    both_running = threading.Barrier(2, timeout=5)

    def _first_call_drops(spec, items, *args, **kwargs):
        adapter, first = real_baseline(spec, items, *args, **kwargs), render_prompt(items[0])

        def _call(prompt):
            both_running.wait()
            if prompt == first:
                raise ConnectionResetError("remote end closed connection without response")
            time.sleep(0.5)                      # still in flight when the abort is handled
            return adapter(prompt)
        return _call
    monkeypatch.setattr(baselines_module, "baseline_adapter", _first_call_drops)
    results = tmp_path / "r.jsonl"
    with pytest.raises(ConnectionResetError):
        cli.main(_run_argv(tmp_path, store_dir, bench_dir, results, "--model", "gold:", "--track", "prove",
                           "--limit", "2", "--workers", "2"))
    assert "stopping; waiting for 1 call(s) still in flight" in capsys.readouterr().err
    assert len(_rows(results)) == 1                            # the call in flight was kept


def test_parallel_failed_reorder_still_prints_the_summary(tmp_path, store_dir, bench_dir, capsys, monkeypatch):
    # The streamed file is complete when the reorder runs; an OSError there must cost neither
    # the summary nor the rows.
    # Mutation checked: let the reorder's OSError propagate -> fails (the run raises).
    def _read_only(path, text):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(cli, "_replace_atomically", _read_only)
    results = tmp_path / "r.jsonl"
    rc = cli.main(_run_argv(tmp_path, store_dir, bench_dir, results,
                            "--model", "gold:", "--track", "prove", "--workers", "3"))
    captured = capsys.readouterr()
    assert rc == 0 and _sorted_json(captured.out)["n_rows"] == 6
    assert "left in completion order" in captured.err
    assert sorted(r["item"] for r in _rows(results)) == sorted(
        item["id"] for item in json.loads((bench_dir / "items" / "prove.json").read_text()))


def test_workers_validation(tmp_path, store_dir, bench_dir, capsys):
    # Mutations checked: drop the `--workers < 1` refusal -> the 0 case runs and exits 0;
    # drop the static-in-parallel refusal -> the static case runs and exits 0.
    with pytest.raises(SystemExit) as ex:
        cli.main(_run_argv(tmp_path, store_dir, bench_dir, tmp_path / "a.jsonl",
                           "--model", "gold:", "--track", "prove", "--workers", "0"))
    assert ex.value.code == 2 and "--workers must be >= 1" in capsys.readouterr().err
    static = tmp_path / "static.json"
    static.write_text(json.dumps(["{}"] * 6))
    with pytest.raises(SystemExit) as ex:
        cli.main(_run_argv(tmp_path, store_dir, bench_dir, tmp_path / "b.jsonl",
                           "--model", f"static:{static}", "--track", "prove", "--workers", "2"))
    assert ex.value.code == 2 and "cannot replay a static: adapter" in capsys.readouterr().err
