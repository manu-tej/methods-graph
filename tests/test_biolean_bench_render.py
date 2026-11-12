from methods_graph.biolean.bench.render import (
    FORMAT_BLOCK, claim_text, organism, parse_reply, render_prompt)
from tests.test_biolean_kernel import A, deriv, prop, sorry

GOAL = {"subject": "UniProtKB:P04637", "qualifier": "involved_in", "term": "GO:0006915",
        "taxon": "NCBITaxon:9606", "negated": False}
ITEM = {"id": "prove/UniProtKB:P04637/involved_in/GO:0006915", "track": "prove", "goal": GOAL,
        "symbol": "TP53", "term_name": "apoptotic process"}


def test_claim_text_names_symbol_accession_qualifier_term_and_organism():
    assert claim_text(ITEM) == ("TP53 (UniProtKB:P04637) involved_in apoptotic process "
                                "(GO:0006915), human.")
    assert organism("NCBITaxon:9606") == "human"
    assert organism("NCBITaxon:10090") == "NCBITaxon:10090"      # never guessed


def test_prove_prompt_is_the_spec_text_plus_the_format_block():
    prompt = render_prompt(ITEM)
    assert prompt.startswith("Prove the following claim as a Biolean derivation.\nClaim: TP53 ")
    assert "The direct annotation of this gene product to this term is not available to you." in prompt
    assert "Rules: axiom, is_a, part_of, sorry. Answer with the JSON document only." in prompt
    assert prompt.endswith(FORMAT_BLOCK)
    assert '"rule": "sorry"' in FORMAT_BLOCK and '"edge"' in FORMAT_BLOCK and '"root"' in FORMAT_BLOCK


def test_hypothesize_prompt_differs_only_in_the_task_text():
    prove = render_prompt(ITEM)
    hyp = render_prompt({**ITEM, "track": "hypothesize"})
    assert hyp.startswith("No recorded annotation supports the following claim.\nClaim: TP53 ")
    assert "sorry step with provenance naming the method, the input datasets, and parameters" in hyp
    assert hyp != prove and hyp.endswith(FORMAT_BLOCK)
    assert claim_text(ITEM) in hyp


def test_render_prompt_raises_key_error_for_a_malformed_item():
    import pytest
    with pytest.raises(KeyError):
        render_prompt({"id": "x", "track": "prove", "goal": GOAL})       # no symbol / term_name
    with pytest.raises(KeyError):
        render_prompt({**ITEM, "track": "unknown"})


def test_parse_reply_finds_the_first_json_object_and_rejects_everything_else():
    doc = {"biolean": "0.1", "goal": GOAL, "steps": [], "root": "s1"}
    import json
    text = json.dumps(doc)
    assert parse_reply(text) == doc
    assert parse_reply("```json\n" + text + "\n```") == doc
    assert parse_reply("Sure, here is the derivation:\n" + text + "\nHope this helps.") == doc
    assert parse_reply("{not json} " + text) == doc                # skips the unbalanced span
    assert parse_reply('[{"a": 1}]') is None                       # the inner object has no document key
    assert parse_reply("[1, 2, 3]") is None
    assert parse_reply("I cannot help with that.") is None
    assert parse_reply("") is None
    assert parse_reply(None) is None
    assert parse_reply(42) is None
    assert parse_reply(text[:-5]) is None                           # truncated document
    assert parse_reply(text[:-1] + ",}") is None                    # trailing comma
    # A Python-style False (invalid JSON) corrupts every occurrence of the "false" literal,
    # including inside the goal and the step's conclusion, but the sorry's provenance dict
    # carries no boolean and stays independently well-formed — exactly the embedded object
    # the old implementation would have returned in place of the whole reply.
    sorry_doc = deriv(prop(A), [sorry("s1", A)], "s1")
    corrupted = json.dumps(sorry_doc).replace("false", "False")
    assert parse_reply(corrupted) is None
    stray = json.dumps({"note": 1}) + text
    assert parse_reply(stray) == doc                                # scans past the stray object
