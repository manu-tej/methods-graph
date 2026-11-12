from methods_graph.biolean.props import (
    ASPECT_NAMESPACE, EVIDENCE_CLASS, NAMESPACE_ASPECT, PROPAGATING_RELATIONS,
    QUALIFIER_ASPECT, TAXON_RE, Prop, evidence_class, normalize_taxon)


def test_thirteen_qualifiers_cover_the_three_aspects():
    assert len(QUALIFIER_ASPECT) == 13
    assert set(QUALIFIER_ASPECT.values()) == {"F", "P", "C"}
    assert QUALIFIER_ASPECT["part_of"] == "C"          # the qualifier, not the relation
    assert QUALIFIER_ASPECT["enables"] == "F"
    assert QUALIFIER_ASPECT["acts_upstream_of_or_within_negative_effect"] == "P"


def test_namespace_tables_are_inverses():
    assert NAMESPACE_ASPECT == {"molecular_function": "F", "biological_process": "P", "cellular_component": "C"}
    assert ASPECT_NAMESPACE == {v: k for k, v in NAMESPACE_ASPECT.items()}


def test_evidence_classes_cover_every_gaf_code_and_nothing_else():
    assert evidence_class("IDA") == "experimental"
    assert evidence_class("HDA") == "high_throughput"
    assert evidence_class("IBA") == "phylogenetic"
    assert evidence_class("ISS") == "computational"
    assert evidence_class("TAS") == "author_statement"
    assert evidence_class("ND") == "curatorial"
    assert evidence_class("IEA") == "electronic"
    assert evidence_class("XYZ") == "unknown"
    assert len(EVIDENCE_CLASS) == 26


def test_regulates_family_is_not_propagating():
    assert PROPAGATING_RELATIONS == ("is_a", "part_of")


def test_normalize_taxon_accepts_three_spellings_and_rejects_words():
    assert normalize_taxon("9606") == "NCBITaxon:9606"
    assert normalize_taxon("taxon:9606") == "NCBITaxon:9606"
    assert normalize_taxon("NCBITaxon:9606") == "NCBITaxon:9606"
    assert normalize_taxon("human") is None
    assert normalize_taxon("") is None
    assert TAXON_RE.match("NCBITaxon:9606") and not TAXON_RE.match("taxon:9606")


def test_prop_from_dict_requires_exactly_five_typed_fields():
    good = {"subject": "UniProtKB:P00001", "qualifier": "involved_in",
            "term": "GO:0000010", "taxon": "NCBITaxon:9606", "negated": False}
    p = Prop.from_dict(good)
    assert p == Prop("UniProtKB:P00001", "involved_in", "GO:0000010", "NCBITaxon:9606", False)
    assert p.to_dict() == good
    assert Prop.from_dict({**good, "extra": 1}) is None
    assert Prop.from_dict({k: v for k, v in good.items() if k != "taxon"}) is None
    assert Prop.from_dict({**good, "negated": "false"}) is None
    assert Prop.from_dict("not a dict") is None
