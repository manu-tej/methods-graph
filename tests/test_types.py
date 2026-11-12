from methods_graph.types import MethodRecord, EdgeRecord, NodeKind, EdgeKind, Provenance


def test_method_record_roundtrips_to_dict():
    prov = Provenance(source="nfcore", source_url="https://x", ingested_at="2026-06-08")
    rec = MethodRecord(
        id="m:salmon",
        name="salmon",
        kind=NodeKind.METHOD,
        bioconda_pkg="salmon",
        biotools_id="salmon",
        properties={"version": "1.10.0"},
        provenance=prov,
    )
    d = rec.to_row()
    assert d["id"] == "m:salmon"
    assert d["bioconda_pkg"] == "salmon"
    assert d["source"] == "nfcore"


def test_edge_record_to_row():
    prov = Provenance(source="edam", source_url="https://edam", ingested_at="2026-06-08")
    e = EdgeRecord(from_id="m:salmon", to_id="op:quant",
                   kind=EdgeKind.PERFORMS, properties={}, provenance=prov)
    row = e.to_row()
    assert row["from_id"] == "m:salmon"
    assert row["to_id"] == "op:quant"
    assert row["kind"] == "PERFORMS"
