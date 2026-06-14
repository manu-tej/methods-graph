import json
from methods_graph.planner import Executor, Suggestion


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
