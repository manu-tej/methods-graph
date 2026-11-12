"""Render, call, score, retain — one row per item, streamed — and rescore from rows alone.

Same guarantees as ``bench/run.py``: an adapter failure is recorded against its item and the
run continues; a render failure fails only its own row; ``sink`` receives each row as it is
produced so an interrupted or killed paid run keeps what it paid for; ``rescore`` re-derives
every score from the retained ``raw`` plus the row's own ``goal``/``hidden``, never from the
item files.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any, Callable

from methods_graph.bench.adapters import AdapterError
from methods_graph.biolean.bench.render import render_prompt
from methods_graph.biolean.bench.score import Resolver, failure_row, score_row
from methods_graph.biolean.store import FactStore


def items_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """What every row carries from the items' manifest: enough to refuse a mismatched store
    and to echo the live cut with every score."""
    return {"release": manifest.get("release"), "since": manifest.get("since")}


def run_items(
    items: list[dict[str, Any]], adapter: Callable[[str], str], store: FactStore, *,
    model: str, items_manifest: dict[str, Any], resolve: Resolver | None = None,
    sink: Callable[[dict[str, Any]], None] | None = None, workers: int = 1,
    on_drain: Callable[[int], None] | None = None,
) -> list[dict[str, Any]]:
    """One row per item, each passed to ``sink`` as soon as it is scored.

    ``workers > 1`` runs up to that many adapter calls at once in a thread pool; rendering and
    scoring stay in the calling thread.

    Ordering: the returned list is in item order whatever order the calls finish in, so it
    equals the sequential run's for a deterministic adapter. ``sink`` is called in completion
    order instead, each row as soon as its call is scored: a row held back behind a slower
    earlier item would be lost to SIGTERM, SIGHUP, SIGKILL or a native crash, none of which
    reaches Python's exception handling. A caller that wants item order on disk rewrites once
    the run returns (the CLI does).

    Interrupts: if a call raises anything but ``AdapterError`` (``KeyboardInterrupt``
    included), or the calling thread is interrupted while waiting, queued calls are cancelled
    first, so nothing new starts whatever the salvage below does. Then every call that already
    finished is scored and sunk, in item order. Then ``on_drain`` is told how many calls are
    still in flight (a failing ``on_drain`` is ignored: a notice must not cost answers), and
    each is sunk the moment it finishes, not after the slowest: the interpreter waits for them
    at exit whatever this function does. Every finished call gets a row except the one whose
    exception is re-raised: one that failed with anything but ``AdapterError`` (another reset
    connection) becomes an error row naming the exception, as an ``AdapterError`` does, and a
    call the interrupt reached too (a ``claude -p`` child shares the terminal's Ctrl-C)
    finishes as an ``AdapterError`` row; ``--resume`` retries both. Then the exception is
    re-raised. An interrupted parallel run keeps every answer it already has. A second
    interrupt during that wait keeps every row sunk before it and discards the calls still
    running, yet the process still waits for them at exit.
    """
    if workers > 1:
        return _run_parallel(items, adapter, store, model=model, items_manifest=items_manifest,
                             resolve=resolve, sink=sink, workers=workers, on_drain=on_drain)
    rows: list[dict[str, Any]] = []
    for item in items:
        try:
            prompt = render_prompt(item)
        except (KeyError, TypeError, ValueError) as exc:
            row = failure_row(item, error=f"render failed: {exc}",
                              render_error=f"{type(exc).__name__}: {exc}")
        else:
            try:
                raw = adapter(prompt)
            except AdapterError as exc:
                row = failure_row(item, error=str(exc), render_error=None)
            else:
                row = score_row(item, raw, store, resolve=resolve)
        row = {**row, "model": model, "items_manifest": items_manifest}
        rows.append(row)
        if sink is not None:
            sink(row)
    return rows


def _run_parallel(
    items: list[dict[str, Any]], adapter: Callable[[str], str], store: FactStore, *,
    model: str, items_manifest: dict[str, Any], resolve: Resolver | None,
    sink: Callable[[dict[str, Any]], None] | None, workers: int,
    on_drain: Callable[[int], None] | None,
) -> list[dict[str, Any]]:
    """``run_items`` with the adapter calls in a pool, sinking each row as it is scored."""
    emitted: dict[int, dict[str, Any]] = {}       # item index -> row already passed to sink

    def _stamp(row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "model": model, "items_manifest": items_manifest}

    def _emit(index: int, row: dict[str, Any]) -> None:
        emitted[index] = row                       # before sink: a failed sink is not retried
        if sink is not None:
            sink(row)

    def _finished_row(index: int, future: Future) -> dict[str, Any]:
        """The row for a completed call; any exception other than ``AdapterError`` propagates."""
        try:
            raw = future.result()
        except AdapterError as exc:
            return _stamp(failure_row(items[index], error=str(exc), render_error=None))
        return _stamp(score_row(items[index], raw, store, resolve=resolve))

    prompts: dict[int, str] = {}
    for index, item in enumerate(items):
        try:
            prompts[index] = render_prompt(item)
        except (KeyError, TypeError, ValueError) as exc:
            _emit(index, _stamp(failure_row(item, error=f"render failed: {exc}",
                                            render_error=f"{type(exc).__name__}: {exc}")))

    executor = ThreadPoolExecutor(max_workers=workers)
    futures: dict[Future, int] = {}

    def _salvage(abort: BaseException) -> None:
        """Sink, in item order, every finished call not sunk yet: the failing call may share a
        completion batch with them, or they finished while the calling thread was interrupted
        or during the drain. The call whose exception is ``abort`` is re-raised, not a row; any
        other call that failed with something but ``AdapterError`` is an error row, so nothing
        that finished goes unrecorded."""
        for future, index in sorted(futures.items(), key=lambda pair: pair[1]):
            if index in emitted or not future.done() or future.cancelled():
                continue
            exc = future.exception()
            if exc is abort:
                continue
            if exc is None or isinstance(exc, AdapterError):
                try:
                    row = _finished_row(index, future)
                except Exception:      # its scoring is what raised; that exception re-raises below
                    continue
            else:
                row = _stamp(failure_row(items[index], error=f"{type(exc).__name__}: {exc}",
                                         render_error=None))
            _emit(index, row)

    try:
        for index in sorted(prompts):
            futures[executor.submit(adapter, prompts[index])] = index
        pending = set(futures)
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in sorted(done, key=futures.__getitem__):
                _emit(futures[future], _finished_row(futures[future], future))
    except BaseException as abort:
        # Cancel first: if the salvage below raises too (the sink that failed fails again, or
        # a second Ctrl-C), queued calls must still never start. Finished futures keep results.
        executor.shutdown(wait=False, cancel_futures=True)
        # Snapshot before the salvage: a call that lands while it runs is still drained below.
        in_flight = {future for future in futures if not future.done()}
        _salvage(abort)
        # Sink each call still in flight as it lands, so none waits behind the slowest, where
        # a second interrupt would discard it.
        running = sum(not future.done() for future in in_flight)
        if running and on_drain is not None:
            try:
                on_drain(running)
            except Exception:      # e.g. stderr piped to a reader the same Ctrl-C killed
                pass
        while in_flight:
            _, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
            _salvage(abort)
        raise
    executor.shutdown(wait=True)
    return [emitted[index] for index in sorted(emitted)]


def rescore(
    rows: list[dict[str, Any]], store: FactStore, *, resolve: Resolver | None = None,
) -> list[dict[str, Any]]:
    """Re-derive every score from the retained raw output, leaving failure rows untouched.
    Keyed on ``error``, not on ``raw is None``: a null ``raw`` can be a genuine model answer."""
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("error") is not None:
            out.append(dict(row))
            continue
        item = {"id": row["item"], "track": row["track"], "goal": row["goal"], "hidden": row["hidden"],
                "hidden_classes": row.get("hidden_classes") or [], "gold_depth": row.get("gold_depth")}
        out.append({**score_row(item, row["raw"], store, resolve=resolve),
                    "model": row.get("model"), "items_manifest": row.get("items_manifest")})
    return out


def release_mismatch(items_release: dict[str, Any] | None, store_release: dict[str, Any]) -> list[str]:
    """One line per key whose value differs between the items' recorded release and the
    store's, sorted by key; empty when they agree. A missing record differs on every key."""
    recorded = items_release or {}
    out: list[str] = []
    for key in sorted(set(recorded) | set(store_release)):
        if recorded.get(key) != store_release.get(key):
            out.append(f"{key}: items {recorded.get(key)!r} vs store {store_release.get(key)!r}")
    return out
