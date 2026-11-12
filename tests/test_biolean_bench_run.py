"""Render, call, score, stream; rescore from rows alone; refuse a mismatched release."""
import json
import threading
import time

import pytest

from methods_graph.bench.adapters import AdapterError
from methods_graph.biolean.bench.baselines import gold_answer, template_answer
from methods_graph.biolean.bench.items import hypothesize_items, population, prove_items
from methods_graph.biolean.bench.render import render_prompt
from methods_graph.biolean.bench.run import items_manifest, release_mismatch, rescore, run_items
from methods_graph.biolean.bench.score import COMMON_KEYS, HYPOTHESIZE_KEYS, PROVE_KEYS, summarize
from tests.biolean_fixture import RELEASE, mini_store
from tests.test_biolean_kernel import B, D

STORE = mini_store()
TRIPLES, _ = population(STORE)
PROVE, _ = prove_items(STORE, TRIPLES)
HYP, _ = hypothesize_items(STORE, TRIPLES)
MANIFEST = {"release": RELEASE, "since": None}


def _gold_adapter():
    table = {}
    from methods_graph.biolean.bench.render import render_prompt
    for item in PROVE:
        table[render_prompt(item)] = json.dumps(gold_answer(item, STORE))
    for item in HYP:
        table[render_prompt(item)] = json.dumps(template_answer(item))
    return lambda prompt: table[prompt]


def _mixed_adapter():
    gold = _gold_adapter()

    def _adapter(prompt):
        if f"({B})" in prompt:
            raise AdapterError("rate limited")
        if f"({D})" in prompt:
            return "I would rather not."
        return gold(prompt)
    return _adapter


def test_rows_reconcile():
    rows = run_items(PROVE, _mixed_adapter(), STORE, model="t", items_manifest=MANIFEST)
    summary = summarize(rows)
    assert summary["n_rows"] == 6
    assert summary["n_rows"] == summary["n_errors"] + summary["n_unparsed"] + summary["n_checked"]
    assert (summary["n_errors"], summary["n_unparsed"], summary["n_checked"]) == (1, 1, 4)
    assert summary["prove"]["n"] == 5                      # the error row is in no denominator
    assert summary["prove"]["hit_rate"] == 4 / 5           # the unparsed row is a miss
    assert summary["release"] == RELEASE and summary["since"] is None


def test_adapter_error_row_is_excluded_and_counted():
    rows = run_items(PROVE, _mixed_adapter(), STORE, model="t", items_manifest=MANIFEST)
    failed = next(r for r in rows if r["goal"]["term"] == B)
    assert failed["error"] == "rate limited" and failed["raw"] is None and failed["parsed"] is False
    assert failed["hit"] is None and failed["error_codes"] is None and failed["render_error"] is None
    ok = next(r for r in rows if r["error"] is None and r["parsed"])
    assert set(failed) == set(ok) == COMMON_KEYS | PROVE_KEYS
    assert summarize(rows)["prove"]["error_items"] == {"UNPARSED": 1}      # not the error row


def test_render_failure_fails_its_own_row_and_the_run_continues():
    broken = {k: v for k, v in PROVE[0].items() if k != "symbol"}
    rows = run_items([broken, PROVE[1]], _gold_adapter(), STORE, model="t", items_manifest=MANIFEST)
    assert rows[0]["error"].startswith("render failed") and rows[0]["render_error"].startswith("KeyError")
    assert rows[0]["item"] == broken["id"]
    assert rows[1]["error"] is None and rows[1]["hit"] is True
    assert summarize(rows)["n_render_errors"] == 1


def test_rows_carry_model_and_items_manifest_and_stream_through_the_sink():
    seen = []
    rows = run_items(PROVE[:2], _gold_adapter(), STORE, model="gold:", items_manifest=MANIFEST,
                     sink=seen.append)
    assert seen == rows and [r["item"] for r in rows] == [PROVE[0]["id"], PROVE[1]["id"]]
    assert all(r["model"] == "gold:" and r["items_manifest"] == MANIFEST for r in rows)
    assert items_manifest({"release": RELEASE, "since": "2020-01-01", "seed": 0}) == \
        {"release": RELEASE, "since": "2020-01-01"}


def test_prove_and_hypothesize_rows_share_only_the_common_vocabulary():
    rows = run_items([PROVE[0], HYP[0]], _gold_adapter(), STORE, model="t", items_manifest=MANIFEST)
    hyp, prove = sorted(rows, key=lambda r: r["track"])
    assert set(prove) == COMMON_KEYS | PROVE_KEYS
    assert set(hyp) == COMMON_KEYS | HYPOTHESIZE_KEYS
    assert set(prove) & set(hyp) == COMMON_KEYS
    assert "hit" not in hyp and hyp["format_ok"] is True
    summary = summarize(rows)
    assert summary["prove"]["n"] == 1 and summary["hypothesize"]["n"] == 1
    assert not {"hit", "hit_rate", "accepted"} & set(summary["hypothesize"])


def test_rescore_reproduces_scores_from_the_row_alone():
    resolve = lambda name: name if name == "m:deseq2" else None
    rows = run_items(PROVE + HYP, _mixed_adapter(), STORE, model="t", items_manifest=MANIFEST,
                     resolve=resolve)
    kept = ("item", "track", "goal", "hidden", "hidden_classes", "gold_depth", "raw", "model",
            "items_manifest", "error", "render_error")
    stripped = [{k: v for k, v in r.items() if k in kept} for r in rows]
    again = rescore(stripped, STORE, resolve=resolve)
    for before, after in zip(rows, again):
        if before["error"] is not None:
            assert after == {k: v for k, v in before.items() if k in kept}     # untouched
        else:
            assert after == before
    assert summarize(again)["prove"]["hit_rate"] == summarize(rows)["prove"]["hit_rate"] == 4 / 5


def test_release_mismatch_names_each_differing_key():
    assert release_mismatch(RELEASE, RELEASE) == []
    changed = {**RELEASE, "go_basic_data_version": "releases/2027-01-01"}
    lines = release_mismatch(RELEASE, changed)
    assert len(lines) == 1 and lines[0].startswith("go_basic_data_version:")
    assert "releases/2026-01-01" in lines[0] and "releases/2027-01-01" in lines[0]
    assert len(release_mismatch(None, RELEASE)) == 3
    assert len(release_mismatch({}, RELEASE)) == 3


# ---------------------------------------------------------------------------
# workers > 1: adapter calls overlap; each row is sunk as it is scored; the returned list is
# in item order; an abort keeps every answer paid for
# ---------------------------------------------------------------------------

def _indexed(items):
    return {render_prompt(item): i for i, item in enumerate(items)}


def test_parallel_rows_match_sequential_in_item_order():
    # Mutation checked: return the rows in completion order (the sink's order) -> fails,
    # because the sleeps make later items finish first.
    items = PROVE + HYP[:4]
    index, gold = _indexed(items), _gold_adapter()

    def _later_items_finish_first(prompt):
        time.sleep(0.01 * (len(items) - index[prompt]))
        return gold(prompt)

    sequential = run_items(items, gold, STORE, model="t", items_manifest=MANIFEST)
    seen = []
    parallel = run_items(items, _later_items_finish_first, STORE, model="t", items_manifest=MANIFEST,
                         sink=seen.append, workers=4)
    assert parallel == sequential
    position = {item["id"]: i for i, item in enumerate(items)}
    assert list(position) == [r["item"] for r in parallel]
    assert sorted(seen, key=lambda r: position[r["item"]]) == parallel   # the sink got each row once


def test_parallel_sink_gets_each_row_as_soon_as_its_call_finishes():
    # A row held in memory behind a slower earlier item is lost to SIGTERM, SIGHUP, SIGKILL or a
    # crash, which no except clause sees. Item 0's call waits until the sink holds items 1-3.
    # Mutation checked: sink only the contiguous item-order prefix (a reorder buffer in front of
    # the sink) -> fails: rows 1-3 are held behind item 0, which waits out its timeout.
    items = PROVE[:4]
    index, gold = _indexed(items), _gold_adapter()
    others_sunk, waited = threading.Event(), {}

    def _adapter(prompt):
        if index[prompt] == 0:
            waited["released"] = others_sunk.wait(timeout=2)
        return gold(prompt)

    seen = []

    def _sink(row):
        seen.append(row)
        if len(seen) == 3:
            others_sunk.set()

    rows = run_items(items, _adapter, STORE, model="t", items_manifest=MANIFEST, sink=_sink, workers=4)
    assert waited["released"] is True
    assert sorted(r["item"] for r in seen[:3]) == sorted(item["id"] for item in items[1:])
    assert seen[3]["item"] == items[0]["id"]
    assert [r["item"] for r in rows] == [item["id"] for item in items]


def test_parallel_calls_overlap():
    # Mutation checked: run_items ignores `workers` (always the sequential loop) -> fails.
    gold = _gold_adapter()

    def _peak(workers):
        lock, state = threading.Lock(), {"now": 0, "peak": 0}

        def _adapter(prompt):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1
            return gold(prompt)
        rows = run_items(PROVE, _adapter, STORE, model="t", items_manifest=MANIFEST, workers=workers)
        assert len(rows) == len(PROVE) == 6
        return state["peak"]

    assert _peak(4) >= 2
    assert _peak(1) == 1


def test_parallel_interrupt_from_a_call_propagates_and_is_not_a_row():
    # Mutation checked: turn any exception from a call into a failure row, as AdapterError is
    # -> fails: the KeyboardInterrupt is swallowed and item 0 gets an error row.
    items = PROVE[:4]
    index, gold = _indexed(items), _gold_adapter()
    lock, returned, others_done = threading.Lock(), {"n": 0}, threading.Event()

    def _adapter(prompt):
        if index[prompt] == 0:
            assert others_done.wait(timeout=5), "items 1-3 never returned"
            time.sleep(0.2)
            raise KeyboardInterrupt
        answer = gold(prompt)
        with lock:
            returned["n"] += 1
            if returned["n"] == 3:
                others_done.set()
        return answer

    seen = []
    with pytest.raises(KeyboardInterrupt):
        run_items(items, _adapter, STORE, model="t", items_manifest=MANIFEST, sink=seen.append, workers=4)
    assert sorted(r["item"] for r in seen) == sorted(item["id"] for item in items[1:])
    assert all(r["error"] is None and r["hit"] is True for r in seen)
    assert all(r["model"] == "t" and r["items_manifest"] == MANIFEST for r in seen)


def test_parallel_interrupt_salvages_calls_that_finish_beside_the_failing_one():
    # Mutation checked: make the interrupt path's salvage a no-op -> fails. Items 2 and 3 are
    # forced into the same completion batch as item 1's KeyboardInterrupt, which is scored
    # first (item order), so they are still unscored when it raises; only the salvage can
    # emit them.
    items = PROVE[:4]
    index, gold = _indexed(items), _gold_adapter()
    lock, returned = threading.Lock(), {"n": 0}
    first_emitted, others_done, raising = threading.Event(), threading.Event(), threading.Event()

    def _adapter(prompt):
        i = index[prompt]
        if i == 0:
            return gold(prompt)
        if i == 1:
            assert others_done.wait(timeout=5), "items 2-3 never returned"
            time.sleep(0.05)
            raising.set()
            raise KeyboardInterrupt
        assert first_emitted.wait(timeout=5), "item 0 was never emitted"
        answer = gold(prompt)
        with lock:
            returned["n"] += 1
            if returned["n"] == 2:
                others_done.set()
        return answer

    seen = []

    def _sink(row):
        seen.append(row)
        if len(seen) == 1:                       # hold the calling thread until 1-3 have all finished
            first_emitted.set()
            assert raising.wait(timeout=5), "item 1 never raised"
            time.sleep(0.2)

    with pytest.raises(KeyboardInterrupt):
        run_items(items, _adapter, STORE, model="t", items_manifest=MANIFEST, sink=_sink, workers=4)
    assert [r["item"] for r in seen] == [items[0]["id"], items[2]["id"], items[3]["id"]]
    assert all(r["error"] is None and r["hit"] is True for r in seen)


def test_parallel_calling_thread_interrupt_keeps_every_finished_row(monkeypatch):
    # The path a real Ctrl-C takes: SIGINT lands in the calling thread, blocked in wait(), not
    # in a worker (the claude -p children just exit nonzero, which is an AdapterError). Items
    # 1-3 have finished but wait() has not returned them; item 0 is still in flight and
    # answers after the interrupt.
    # Mutations checked: salvage only when a worker raised (a calling-thread interrupt just
    # cancels and re-raises) -> fails, the sink gets nothing; drop the wait for in-flight
    # calls -> fails, item 0's paid answer is lost.
    from methods_graph.biolean.bench import run as run_module
    items = PROVE[:4]
    index, gold = _indexed(items), _gold_adapter()
    interrupted = threading.Event()

    def _adapter(prompt):
        if index[prompt] == 0:
            assert interrupted.wait(timeout=5), "the interrupt never came"
            time.sleep(0.1)                      # still in flight while the interrupt is handled
        return gold(prompt)

    real_wait = run_module.wait

    def _ctrl_c_once_items_1_to_3_are_done(pending, **kwargs):
        if interrupted.is_set():                 # one Ctrl-C; the drain's waits are real
            return real_wait(pending, **kwargs)
        deadline = time.monotonic() + 5
        while sum(future.done() for future in pending) < 3:
            assert time.monotonic() < deadline, "items 1-3 never finished"
            time.sleep(0.005)
        interrupted.set()
        raise KeyboardInterrupt

    monkeypatch.setattr(run_module, "wait", _ctrl_c_once_items_1_to_3_are_done)
    seen = []
    with pytest.raises(KeyboardInterrupt):
        run_items(items, _adapter, STORE, model="t", items_manifest=MANIFEST, sink=seen.append, workers=4)
    assert [r["item"] for r in seen] == [items[1]["id"], items[2]["id"], items[3]["id"], items[0]["id"]]
    assert all(r["error"] is None and r["hit"] is True for r in seen)


def test_parallel_abort_keeps_the_calls_still_in_flight():
    # A call dies with something other than AdapterError (a dropped connection) while three
    # others are mid-request. Those three are paid for; the pool finishes them whatever
    # run_items does, so they must reach the sink before it re-raises.
    # Mutation checked: re-raise right after the first salvage, without waiting for the
    # calls in flight -> fails, the sink gets nothing.
    items = PROVE[:4]
    index, gold = _indexed(items), _gold_adapter()
    lock, started, all_started, dropped = threading.Lock(), {"n": 0}, threading.Event(), threading.Event()

    def _adapter(prompt):
        if index[prompt] == 0:
            assert all_started.wait(timeout=5), "items 1-3 never started"
            dropped.set()
            raise ConnectionResetError("remote end closed connection without response")
        with lock:
            started["n"] += 1
            if started["n"] == 3:
                all_started.set()
        assert dropped.wait(timeout=5), "item 0 never failed"
        time.sleep(0.2)                          # still in flight while the abort is handled
        return gold(prompt)

    seen = []
    with pytest.raises(ConnectionResetError):
        run_items(items, _adapter, STORE, model="t", items_manifest=MANIFEST, sink=seen.append, workers=4)
    # Each is sunk as it lands (completion order), so only the set, once each, is fixed.
    assert sorted(r["item"] for r in seen) == sorted(item["id"] for item in items[1:])
    assert all(r["error"] is None and r["hit"] is True for r in seen)


def test_parallel_abort_sinks_each_in_flight_call_as_it_finishes():
    # A row that waits behind the slowest call in flight is lost to a second Ctrl-C (or
    # SIGTERM) during that wait, though it was paid for. Item 2's call is released only by
    # item 1's row reaching the sink, so it waits out its timeout unless item 1 is sunk first.
    # Mutation checked: wait for every call in flight (shutdown(wait=True)), then salvage once
    # -> fails: item 2 is never released and on_drain still reports 2.
    items = PROVE[:3]
    index, gold = _indexed(items), _gold_adapter()
    all_running, draining, item_1_sunk = threading.Barrier(3, timeout=5), threading.Event(), threading.Event()
    waited, drains = {}, []

    def _adapter(prompt):
        all_running.wait()
        if index[prompt] == 0:
            raise ConnectionResetError("remote end closed connection without response")
        if index[prompt] == 1:
            assert draining.wait(timeout=5), "on_drain was never called"
        else:
            waited["released"] = item_1_sunk.wait(timeout=2)
        return gold(prompt)

    def _on_drain(n_in_flight):
        drains.append(n_in_flight)
        draining.set()

    seen = []

    def _sink(row):
        seen.append(row)
        if row["item"] == items[1]["id"]:
            item_1_sunk.set()

    with pytest.raises(ConnectionResetError):
        run_items(items, _adapter, STORE, model="t", items_manifest=MANIFEST, sink=_sink, workers=3,
                  on_drain=_on_drain)
    assert drains == [2]
    assert waited["released"] is True
    assert [r["item"] for r in seen] == [items[1]["id"], items[2]["id"]]
    assert all(r["error"] is None and r["hit"] is True for r in seen)


def test_parallel_call_landing_during_the_salvage_is_still_drained(monkeypatch):
    # Ctrl-C arrives with item 1 finished and item 0 in flight; item 0 lands while the salvage
    # is still writing item 1. It was in flight when the abort began, so it must be drained;
    # and it is no longer running, so on_drain must not announce a wait for it.
    # Mutations checked: snapshot the calls in flight after the salvage instead of before ->
    # fails (item 0 is done by then, so the drain never runs and its answer is never sunk);
    # count the snapshot instead of the calls still running (`len(in_flight)`) -> fails
    # (on_drain(1)); guard on the snapshot instead of the count (`if in_flight and ...`) ->
    # fails (on_drain(0)).
    from methods_graph.biolean.bench import run as run_module
    items = PROVE[:2]
    index, gold = _indexed(items), _gold_adapter()
    release_0, interrupted, returned_0 = threading.Event(), threading.Event(), threading.Event()
    real_wait = run_module.wait

    def _adapter(prompt):
        if index[prompt] == 0:
            assert release_0.wait(timeout=5), "item 0 was never released"
            returned_0.set()
        return gold(prompt)

    def _ctrl_c_once_item_1_is_done(pending, **kwargs):
        if interrupted.is_set():
            return real_wait(pending, **kwargs)
        deadline = time.monotonic() + 5
        while not any(future.done() for future in pending):
            assert time.monotonic() < deadline, "item 1 never finished"
            time.sleep(0.005)
        interrupted.set()
        raise KeyboardInterrupt

    seen = []

    def _slow_sink(row):
        seen.append(row)
        if row["item"] == items[1]["id"]:        # item 0 lands while this write is under way
            release_0.set()
            assert returned_0.wait(timeout=5), "item 0 never returned"
            time.sleep(0.1)

    monkeypatch.setattr(run_module, "wait", _ctrl_c_once_item_1_is_done)
    drains = []
    with pytest.raises(KeyboardInterrupt):
        run_items(items, _adapter, STORE, model="t", items_manifest=MANIFEST, sink=_slow_sink, workers=2,
                  on_drain=drains.append)
    assert [r["item"] for r in seen] == [items[1]["id"], items[0]["id"]]
    assert drains == []


def test_parallel_drained_call_failing_otherwise_is_an_error_row():
    # A server resetting connections aborts the run on the first reset, and the calls in flight
    # reset too. Each of those is recorded as an error row (so --resume retries it and the
    # count is visible); only the call whose exception is re-raised gets no row.
    # Mutations checked: the salvage skips any exception but AdapterError -> fails (item 1 has
    # no row); drop the `exc is abort` skip -> fails (item 0 also gets an error row).
    items = PROVE[:3]
    index, gold = _indexed(items), _gold_adapter()
    all_running, draining = threading.Barrier(3, timeout=5), threading.Event()

    def _adapter(prompt):
        all_running.wait()
        if index[prompt] == 0:
            raise ConnectionResetError("first reset")
        assert draining.wait(timeout=5), "on_drain was never called"
        if index[prompt] == 1:
            raise ConnectionResetError("second reset")
        return gold(prompt)

    seen = []
    with pytest.raises(ConnectionResetError, match="first reset"):
        run_items(items, _adapter, STORE, model="t", items_manifest=MANIFEST, sink=seen.append, workers=3,
                  on_drain=lambda n: draining.set())
    by_item = {r["item"]: r for r in seen}
    assert sorted(by_item) == sorted(item["id"] for item in items[1:])
    assert by_item[items[1]["id"]]["error"] == "ConnectionResetError: second reset"
    assert by_item[items[1]["id"]]["raw"] is None and by_item[items[1]["id"]]["model"] == "t"
    assert by_item[items[2]["id"]]["error"] is None and by_item[items[2]["id"]]["hit"] is True


def test_parallel_failing_on_drain_does_not_stop_the_drain():
    # The CLI's on_drain prints to stderr, which raises BrokenPipeError when stderr is piped to
    # a `tee` the same Ctrl-C killed. The notice failing must not cost the calls in flight, nor
    # replace the exception being re-raised.
    # Mutation checked: call on_drain unguarded -> fails (BrokenPipeError propagates and items
    # 1-2 are never sunk).
    items = PROVE[:3]
    index, gold = _indexed(items), _gold_adapter()
    all_running, notified = threading.Barrier(3, timeout=5), threading.Event()

    def _adapter(prompt):
        all_running.wait()
        if index[prompt] == 0:
            raise ConnectionResetError("remote end closed connection without response")
        assert notified.wait(timeout=5), "on_drain was never called"
        return gold(prompt)

    def _broken_stderr(n_in_flight):
        notified.set()
        raise BrokenPipeError(32, "Broken pipe")

    seen = []
    with pytest.raises(ConnectionResetError):
        run_items(items, _adapter, STORE, model="t", items_manifest=MANIFEST, sink=seen.append, workers=3,
                  on_drain=_broken_stderr)
    assert sorted(r["item"] for r in seen) == sorted(item["id"] for item in items[1:])


def test_parallel_on_drain_counts_only_calls_running():
    # Mutations checked: count the unfinished futures before cancelling the queue -> fails
    # (queued calls that never start are reported: 11 or 10, not <= 2); drop the `running`
    # guard -> fails (on_drain(0) when the failing call was the last in flight).
    items, workers = (PROVE + HYP)[:12], 2
    index, gold = _indexed(items), _gold_adapter()
    both_running, draining = threading.Barrier(2, timeout=5), threading.Event()

    def _adapter(prompt):
        if index[prompt] == 0:
            both_running.wait()
            raise ConnectionResetError("remote end closed connection without response")
        if index[prompt] == 1:
            both_running.wait()
        # Every other call blocks too: an instant one would let the worker item 0 freed drain
        # the whole queue before the cancel, and the queued count would equal the running one.
        assert draining.wait(timeout=5), "on_drain was never called"
        return gold(prompt)

    drains = []

    def _on_drain(n_in_flight):
        drains.append(n_in_flight)
        draining.set()

    with pytest.raises(ConnectionResetError):
        run_items(items, _adapter, STORE, model="t", items_manifest=MANIFEST, workers=workers,
                  on_drain=_on_drain)
    assert len(drains) == 1 and 1 <= drains[0] <= workers      # item 1, maybe one freshly started

    # Nothing in flight at the abort: item 0 fails only after item 1's row is sunk.
    item_1_sunk, drains = threading.Event(), []

    def _last_call_fails(prompt):
        if index[prompt] == 0:
            assert item_1_sunk.wait(timeout=5), "item 1 was never sunk"
            raise ConnectionResetError("remote end closed connection without response")
        return gold(prompt)

    def _sink(row):
        if row["item"] == items[1]["id"]:
            item_1_sunk.set()

    with pytest.raises(ConnectionResetError):
        run_items(items[:2], _last_call_fails, STORE, model="t", items_manifest=MANIFEST, sink=_sink,
                  workers=2, on_drain=drains.append)
    assert drains == []


def test_parallel_failing_sink_still_cancels_queued_calls(monkeypatch):
    # A sink that fails (disk full) fails again when the salvage calls it. Queued calls must
    # already be cancelled by then, or the pool makes every remaining paid call before the
    # process can exit and throws the answers away.
    # Mutation checked: cancel after the salvage instead of first -> fails (all 12 calls made).
    from methods_graph.biolean.bench import run as run_module
    items = (PROVE + HYP)[:12]
    gold, workers = _gold_adapter(), 2
    lock, calls = threading.Lock(), {"n": 0}
    pools = []

    class _RecordingPool(run_module.ThreadPoolExecutor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            pools.append(self)

    def _adapter(prompt):
        with lock:
            calls["n"] += 1
            nth = calls["n"]
        if nth > workers:
            time.sleep(0.3)
        return gold(prompt)

    real_wait = run_module.wait

    def _first_batch_holds_two(pending, **kwargs):
        # The failing row and one more finished row arrive together, so the salvage has a
        # row to sink and calls the failing sink a second time.
        deadline = time.monotonic() + 5
        while sum(future.done() for future in pending) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        return real_wait(pending, **kwargs)

    def _disk_full(row):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(run_module, "ThreadPoolExecutor", _RecordingPool)
    monkeypatch.setattr(run_module, "wait", _first_batch_holds_two)
    with pytest.raises(OSError):
        run_items(items, _adapter, STORE, model="t", items_manifest=MANIFEST, sink=_disk_full,
                  workers=workers)
    for pool in pools:
        pool.shutdown(wait=True)                 # let anything still queued run, as exit would
    assert calls["n"] <= 2 * workers < len(items)  # the first two, and at most two already in flight


def test_parallel_adapter_error_is_a_failure_row():
    # Mutation checked: the parallel path lets AdapterError propagate like any other
    # exception -> fails (raises instead of recording the row).
    sequential = run_items(PROVE, _mixed_adapter(), STORE, model="t", items_manifest=MANIFEST)
    parallel = run_items(PROVE, _mixed_adapter(), STORE, model="t", items_manifest=MANIFEST, workers=3)
    assert len(parallel) == len(PROVE) == 6
    failed = [r for r in parallel if r["error"] is not None]
    assert len(failed) == 1 and failed[0]["goal"]["term"] == B and failed[0]["error"] == "rate limited"
    assert failed[0]["raw"] is None and failed[0]["render_error"] is None
    assert parallel == sequential
