"""The graph, reduced to the five questions the scorer asks it.

Every metric in :mod:`methods_graph.bench.score` is a pure function over sets, and this
is the only place that knows a database exists. The scorer's tests therefore run against
:class:`StaticOracle` — no Kuzu, no fixtures on disk, no N+1 queries.

Coverage is reported, never assumed. Measured over the 905-method graph: 415 methods
carry a PERFORMS edge, 49 carry an input Data node, 39 carry an output Data node. A
metric read without its denominator is a metric misread.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Protocol


class Oracle(Protocol):
    """What the scorer needs from the graph, and nothing more."""

    def has_method(self, method_id: str) -> bool: ...
    def method_for_module(self, module_id: str) -> str | None: ...
    def operations(self, method_id: str) -> frozenset[str]: ...
    def inputs(self, method_id: str) -> frozenset[str]: ...
    def outputs(self, method_id: str) -> frozenset[str]: ...
    def method_ids(self) -> list[str]: ...


class StaticOracle:
    """Dict-backed oracle. Holds the whole logic; :class:`KuzuOracle` only fills it."""

    def __init__(
        self,
        *,
        methods: Iterable[str],
        modules: dict[str, str] | None = None,
        operations: dict[str, Iterable[str]] | None = None,
        inputs: dict[str, Iterable[str]] | None = None,
        outputs: dict[str, Iterable[str]] | None = None,
        multi_wrapped: dict[str, list[str]] | None = None,
    ) -> None:
        self._methods = frozenset(methods)
        self._modules = dict(modules or {})
        self._operations = {k: frozenset(v) for k, v in (operations or {}).items()}
        self._inputs = {k: frozenset(v) for k, v in (inputs or {}).items()}
        self._outputs = {k: frozenset(v) for k, v in (outputs or {}).items()}
        self._multi_wrapped = dict(multi_wrapped or {})

    def has_method(self, method_id: str) -> bool:
        return method_id in self._methods

    def method_for_module(self, module_id: str) -> str | None:
        """The method a module wraps, or ``None`` — never a guess."""
        return self._modules.get(module_id)

    def operations(self, method_id: str) -> frozenset[str]:
        return self._operations.get(method_id, frozenset())

    def inputs(self, method_id: str) -> frozenset[str]:
        return self._inputs.get(method_id, frozenset())

    def outputs(self, method_id: str) -> frozenset[str]:
        return self._outputs.get(method_id, frozenset())

    def multi_wrapped(self) -> dict[str, list[str]]:
        """Modules wrapping more than one method, with every candidate.

        ``mod:custom_orfnormalise`` wraps six. :meth:`method_for_module` returns the
        lexicographically first so the answer key is deterministic; this exposes what
        that choice discarded rather than hiding it behind the determinism.
        """
        return dict(self._multi_wrapped)

    def method_ids(self) -> list[str]:
        """Every method the oracle knows, sorted — the random baseline's sample space."""
        return sorted(self._methods)


class KuzuOracle(StaticOracle):
    """Load the whole oracle in five queries, then answer from memory.

    Eager, not lazy: the scorer touches most of the graph anyway, and the per-method
    N+1 pattern in ``KuzuMethodsGraphProvider.get_methods`` is exactly what a scoring
    loop over thousands of items must not repeat.
    """

    def __init__(self, db_path: Path) -> None:
        import kuzu

        db = kuzu.Database(str(db_path), read_only=True)
        conn = kuzu.Connection(db)
        try:
            methods = [r[0] for r in conn.execute(
                "MATCH (m:Entity {kind:'Method'}) RETURN m.id ORDER BY m.id")]

            modules: dict[str, str] = {}
            candidates: dict[str, list[str]] = {}
            for module_id, method_id in conn.execute(
                    "MATCH (mo:Entity {kind:'Module'})-[:Rel {kind:'WRAPS'}]->"
                    "(me:Entity {kind:'Method'}) "
                    "RETURN mo.id, me.id ORDER BY mo.id, me.id"):
                modules.setdefault(module_id, method_id)
                candidates.setdefault(module_id, []).append(method_id)

            operations: dict[str, list[str]] = {}
            for method_id, op_id in conn.execute(
                    "MATCH (m:Entity {kind:'Method'})-[:Rel {kind:'PERFORMS'}]->(o:Entity) "
                    "RETURN m.id, o.id ORDER BY m.id, o.id"):
                operations.setdefault(method_id, []).append(op_id)

            io: dict[str, dict[str, list[str]]] = {"INPUT": {}, "OUTPUT": {}}
            for edge_kind in ("INPUT", "OUTPUT"):
                for method_id, data_id in conn.execute(
                        "MATCH (m:Entity {kind:'Method'})-[:Rel {kind: $k}]->"
                        "(d:Entity {kind:'Data'}) "
                        "RETURN m.id, d.id ORDER BY m.id, d.id",
                        {"k": edge_kind}):
                    io[edge_kind].setdefault(method_id, []).append(data_id)
        finally:
            conn.close()
            db.close()

        super().__init__(
            methods=methods,
            modules=modules,
            operations=operations,
            inputs=io["INPUT"],
            outputs=io["OUTPUT"],
            multi_wrapped={k: v for k, v in candidates.items() if len(v) > 1},
        )


def coverage(oracle: Oracle, module_ids: list[str]) -> dict[str, Any]:
    """How much of the graph's oracle actually backs *module_ids*.

    Both halves matter and neither substitutes for the other: how many gold steps reach
    a method at all, and how many of those methods carry the edges the metrics read.
    """
    unique_modules = sorted(set(module_ids))
    resolved = {m: oracle.method_for_module(m) for m in unique_modules}
    unresolved = sorted(m for m, method in resolved.items() if method is None)
    methods = sorted({method for method in resolved.values() if method})

    return {
        "n_modules": len(unique_modules),
        "n_resolved": len(unique_modules) - len(unresolved),
        "resolved_fraction": (
            None if not unique_modules
            else (len(unique_modules) - len(unresolved)) / len(unique_modules)),
        "unresolved": unresolved,
        "n_methods": len(methods),
        "n_with_operations": sum(1 for m in methods if oracle.operations(m)),
        "n_with_input_data": sum(1 for m in methods if oracle.inputs(m)),
        "n_with_output_data": sum(1 for m in methods if oracle.outputs(m)),
        "methods": methods,
    }
