from methods_graph.pipeline_merge import merge_downstream_of
from methods_graph.types import EdgeKind, EdgeRecord, Provenance

P = Provenance("nfcore_pipeline", "u", "2026-06-13")


def _dse(a, b, pipelines, conf=0.5):
    return EdgeRecord(a, b, EdgeKind.DOWNSTREAM_OF,
                      {"pipelines": pipelines, "attestations": len(pipelines),
                       "derivation": "io_inferred", "confidence": conf}, P)


def test_merge_accumulates_attestations():
    edges = [_dse("mod:a", "mod:b", ["rnaseq"], 0.5),
             _dse("mod:a", "mod:b", ["sarek"], 0.7)]
    out = merge_downstream_of(edges)
    merged = [e for e in out if e.kind == EdgeKind.DOWNSTREAM_OF]
    assert len(merged) == 1
    assert merged[0].properties["pipelines"] == ["rnaseq", "sarek"]  # sorted+deduped
    assert merged[0].properties["attestations"] == 2
    assert merged[0].properties["confidence"] == 0.7  # max


def test_merge_leaves_distinct_edges_and_non_downstream_untouched():
    other = EdgeRecord("mod:a", "m:x", EdgeKind.WRAPS, {}, P)
    edges = [_dse("mod:a", "mod:b", ["rnaseq"]),
             _dse("mod:a", "mod:c", ["rnaseq"]), other]
    out = merge_downstream_of(edges)
    dse = {(e.from_id, e.to_id) for e in out if e.kind == EdgeKind.DOWNSTREAM_OF}
    assert dse == {("mod:a", "mod:b"), ("mod:a", "mod:c")}
    assert other in out  # non-DOWNSTREAM_OF edges pass through unchanged


def test_merge_does_not_mutate_input():
    """The reducer must copy on first encounter — never mutate caller edges."""
    e1 = _dse("mod:a", "mod:b", ["rnaseq"], 0.5)
    e2 = _dse("mod:a", "mod:b", ["sarek"], 0.7)
    out = merge_downstream_of([e1, e2])
    # Inputs unchanged.
    assert e1.properties["pipelines"] == ["rnaseq"]
    assert e1.properties["attestations"] == 1
    assert e1.properties["confidence"] == 0.5
    assert e2.properties["pipelines"] == ["sarek"]
    # Output is a distinct object.
    assert out[0] is not e1 and out[0] is not e2


def test_merge_folds_three_pipelines():
    edges = [_dse("mod:a", "mod:b", ["rnaseq"], 0.4),
             _dse("mod:a", "mod:b", ["sarek"], 0.9),
             _dse("mod:a", "mod:b", ["chipseq"], 0.6)]
    out = merge_downstream_of(edges)
    merged = [e for e in out if e.kind == EdgeKind.DOWNSTREAM_OF]
    assert len(merged) == 1
    assert merged[0].properties["pipelines"] == ["chipseq", "rnaseq", "sarek"]
    assert merged[0].properties["attestations"] == 3
    assert merged[0].properties["confidence"] == 0.9


def test_merge_empty_input():
    assert merge_downstream_of([]) == []
