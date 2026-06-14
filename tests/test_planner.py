import json

import kuzu
from methods_graph.types import NodeRecord, MethodRecord, EdgeRecord, NodeKind, EdgeKind, Provenance
from methods_graph.graph.loader import build_graph
from methods_graph.planner import Executor, Suggestion, _candidates

P = Provenance("test", "x", "2026-06-14")


def _ds(pipelines, attestations):
    return {"pipelines": pipelines, "attestations": attestations,
            "derivation": "io_inferred", "confidence": 0.5}


def build_fixture(tmp_path):
    """A small but representative master-graph slice.

    Modules: align, sort, index, fastqc, multiqc, multi(wraps 2 methods).
    Wiring:  align -> sort (att 2), align -> index (att 1), sort -> multiqc (att 1).
    Cold start: m:star and m:fastqc both INPUT fmt:fastq.
    Popularity: HAS_MODULE so fastqc=2, align=2 pipelines.
    Executors: m:samtools has a container; m:multiqc has an inherited assumption.
    """
    nodes = [
        NodeRecord("mod:align", "STAR align", NodeKind.MODULE, {}, P),
        NodeRecord("mod:sort", "samtools sort", NodeKind.MODULE, {}, P),
        NodeRecord("mod:index", "samtools index", NodeKind.MODULE, {}, P),
        NodeRecord("mod:fastqc", "fastqc", NodeKind.MODULE, {}, P),
        NodeRecord("mod:multiqc", "multiqc", NodeKind.MODULE, {}, P),
        NodeRecord("mod:multi", "multi-wrap", NodeKind.MODULE, {}, P),
        MethodRecord("m:star", "star", NodeKind.METHOD, {}, P, bioconda_pkg="star"),
        MethodRecord("m:samtools", "samtools", NodeKind.METHOD, {}, P, bioconda_pkg="samtools"),
        MethodRecord("m:fastqc", "fastqc", NodeKind.METHOD, {}, P, bioconda_pkg="fastqc"),
        MethodRecord("m:multiqc", "multiqc", NodeKind.METHOD, {}, P, bioconda_pkg="multiqc"),
        MethodRecord("m:aaa", "aaa", NodeKind.METHOD, {}, P, bioconda_pkg="aaa"),
        MethodRecord("m:bbb", "bbb", NodeKind.METHOD, {}, P, bioconda_pkg="bbb"),
        NodeRecord("fmt:fastq", "FASTQ", NodeKind.FORMAT, {}, P),
        NodeRecord("pipe:rnaseq", "rnaseq", NodeKind.PIPELINE, {}, P),
        NodeRecord("pipe:sarek", "sarek", NodeKind.PIPELINE, {}, P),
        NodeRecord("cont:samtools", "samtools-container", NodeKind.CONTAINER,
                   {"image_name": "quay.io/biocontainers/samtools:1.17"}, P),
        NodeRecord("sm:rank", "rank test", NodeKind.STATISTICAL_METHOD, {}, P),
        NodeRecord("assum:norm", "normality", NodeKind.ASSUMPTION, {}, P),
    ]
    edges = [
        EdgeRecord("mod:align", "m:star", EdgeKind.WRAPS, {}, P),
        EdgeRecord("mod:sort", "m:samtools", EdgeKind.WRAPS, {}, P),
        EdgeRecord("mod:index", "m:samtools", EdgeKind.WRAPS, {}, P),
        EdgeRecord("mod:fastqc", "m:fastqc", EdgeKind.WRAPS, {}, P),
        EdgeRecord("mod:multiqc", "m:multiqc", EdgeKind.WRAPS, {}, P),
        EdgeRecord("mod:multi", "m:aaa", EdgeKind.WRAPS, {}, P),
        EdgeRecord("mod:multi", "m:bbb", EdgeKind.WRAPS, {}, P),
        EdgeRecord("mod:align", "mod:sort", EdgeKind.DOWNSTREAM_OF, _ds(["rnaseq", "sarek"], 2), P),
        EdgeRecord("mod:align", "mod:index", EdgeKind.DOWNSTREAM_OF, _ds(["rnaseq"], 1), P),
        EdgeRecord("mod:sort", "mod:multiqc", EdgeKind.DOWNSTREAM_OF, _ds(["rnaseq"], 1), P),
        EdgeRecord("m:star", "fmt:fastq", EdgeKind.INPUT, {}, P),
        EdgeRecord("m:fastqc", "fmt:fastq", EdgeKind.INPUT, {}, P),
        EdgeRecord("pipe:rnaseq", "mod:fastqc", EdgeKind.HAS_MODULE, {}, P),
        EdgeRecord("pipe:rnaseq", "mod:align", EdgeKind.HAS_MODULE, {}, P),
        EdgeRecord("pipe:rnaseq", "mod:sort", EdgeKind.HAS_MODULE, {}, P),
        EdgeRecord("pipe:sarek", "mod:fastqc", EdgeKind.HAS_MODULE, {}, P),
        EdgeRecord("pipe:sarek", "mod:align", EdgeKind.HAS_MODULE, {}, P),
        EdgeRecord("pipe:sarek", "mod:index", EdgeKind.HAS_MODULE, {}, P),
        EdgeRecord("m:samtools", "cont:samtools", EdgeKind.PACKAGED_AS, {}, P),
        EdgeRecord("m:multiqc", "sm:rank", EdgeKind.USES_STATISTICAL_METHOD, {"evidence": "doi:10.x"}, P),
        EdgeRecord("sm:rank", "assum:norm", EdgeKind.REQUIRES_ASSUMPTION, {"evidence": "doi:10.y"}, P),
    ]
    db = tmp_path / "mg.kuzu"
    build_graph(nodes, edges, db, staging_dir=tmp_path / "stg")
    return kuzu.Connection(kuzu.Database(str(db)))


def test_candidates_continue_ranks_by_attestation(tmp_path):
    conn = build_fixture(tmp_path)
    cands = _candidates(conn, ["mod:align"], set())
    ids = [c.module_id for c in cands]
    assert ids == ["mod:sort", "mod:index"]            # 2 attestations before 1
    assert cands[0].kind == "downstream"
    assert cands[0].count == 2
    assert cands[0].evidence == ["rnaseq", "sarek"]


def test_candidates_start_from_data_two_hop_ranks_by_popularity(tmp_path):
    conn = build_fixture(tmp_path)
    cands = _candidates(conn, ["fmt:fastq"], set())
    ids = [c.module_id for c in cands]
    # m:star->mod:align and m:fastqc->mod:fastqc both accept fmt:fastq (Method-level
    # INPUT, reached via WRAPS). Both have popularity 2 -> tie broken by id asc.
    assert ids == ["mod:align", "mod:fastqc"]
    assert all(c.kind == "entry" and c.count == 2 for c in cands)


def test_candidates_excludes_frontier_and_exclude(tmp_path):
    conn = build_fixture(tmp_path)
    cands = _candidates(conn, ["mod:align"], {"mod:sort"})
    assert [c.module_id for c in cands] == ["mod:index"]   # sort excluded


def test_candidates_deterministic(tmp_path):
    conn = build_fixture(tmp_path)
    a = [c.module_id for c in _candidates(conn, ["mod:align", "fmt:fastq"], set())]
    b = [c.module_id for c in _candidates(conn, ["mod:align", "fmt:fastq"], set())]
    assert a == b


def test_executor_to_dict_is_json_serializable():
    e = Executor("m:star", "star", container="quay.io/biocontainers/star:2.7")
    d = e.to_dict()
    assert d == {"method_id": "m:star", "name": "star", "container": "quay.io/biocontainers/star:2.7"}
    json.dumps(d)  # must not raise


def test_suggestion_to_dict_round_trips():
    s = Suggestion(
        module_id="mod:sort", module_name="samtools sort",
        chosen_executor=Executor("m:samtools", "samtools"),
        alternatives=[Executor("m:alt", "alt")],
        rank_signal={"kind": "downstream", "count": 2},
        evidence=["rnaseq", "sarek"],
        assumptions=[{"id": "assum:x", "name": "normality", "via": []}],
        why="after star_align, 2 pipeline(s) run samtools sort next",
    )
    d = s.to_dict()
    assert d["chosen_executor"]["container"] is None
    assert d["alternatives"][0]["method_id"] == "m:alt"
    assert d["rank_signal"]["count"] == 2
    json.dumps(d)  # must not raise
