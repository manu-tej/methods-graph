from methods_graph.biolean.kernel import check
from methods_graph.biolean.props import Annotation, Edge, Prop, Term
from methods_graph.biolean.store import MaskedFactStore, StaticFactStore
from methods_graph.biolean.tactics import applicable, goals_for, prove
from tests.biolean_fixture import mini_store
from tests.test_biolean_kernel import A, B, C, D, MF1, MF2, P1, P2, P3, P5, P7, R, T, TAX, X, Y

STORE = mini_store()


def _p(term, subject=P1, qualifier="involved_in", negated=False):
    return Prop(subject, qualifier, term, TAX, negated)


def _goal_terms(subject, **kw):
    goals, _ = goals_for(subject, STORE, **kw)
    return {(g["prop"]["term"], g["direct"], g["depth"]) for g in goals}


def test_goals_are_the_upward_closure_with_direct_flag_and_shortest_depth():
    goals = _goal_terms(P2)
    assert goals == {(X, True, 0), (Y, True, 0), (T, True, 0)}
    goals = _goal_terms(P7)
    assert (R, True, 0) in goals and (C, False, 1) not in goals   # regulates does not lift


def test_goals_exclude_negated_annotations():
    goals, report = goals_for(P2, STORE)
    assert all(not g["prop"]["negated"] for g in goals)
    assert report["skipped_negated"] == 1


def test_goals_skip_obsolete_term_annotations_and_count_them():
    goals, report = goals_for(P5, STORE)
    assert goals == [] and report["skipped_obsolete"] == 1
    _, report = goals_for(P7, STORE)
    assert report["skipped_unknown_term"] == 1


def test_goals_depth_is_shortest_over_the_diamond():
    goals, _ = goals_for(P1, STORE)
    depth = {g["prop"]["term"]: g["depth"] for g in goals}
    assert depth[A] == 0 and depth[C] == 0                    # C is also direct
    goals, _ = goals_for("UniProtKB:P00008", STORE)             # annotated at A only
    depth = {g["prop"]["term"]: g["depth"] for g in goals}
    assert depth == {A: 0, B: 1, C: 1, D: 1}                    # C via part_of, not via B


def test_goals_are_sorted_and_aspect_filtered():
    goals, _ = goals_for(P3, STORE, aspect="F")
    assert [g["prop"]["term"] for g in goals] == [MF1, MF2]
    assert goals_for(P3, STORE, aspect="P")[0] == []


def _two_target_diamond_store():
    """A diamond where the two targets' shortest routes go through *different* parents of the
    start (S), sorted first (X) and sorted last (P) respectively:

        S -is_a-> X -is_a-> Q1 -is_a-> T1     (S->X->Q1->T1, length 3)
        S -is_a-> P -is_a-> T1                (S->P->T1,     length 2, T1's shortest)
        S -is_a-> X -is_a-> T2                (S->X->T2,     length 2, T2's shortest)
        S -is_a-> P -is_a-> Q2 -is_a-> T2     (S->P->Q2->T2, length 3)

    A recursive (first-sorted-first) DFS would recurse fully into X before ever reaching P,
    marking T1 wrongly at depth 3 via X->Q1 before its true depth-2 route through P is seen.
    A LIFO-stack DFS instead recurses into P (sorted last, popped first) before X, marking T2
    wrongly at depth 3 via P->Q2 before its true depth-2 route through X is seen. Only a real
    multi-source-per-level BFS gets both right.
    """
    ids = {"S": "GO:1", "X": "GO:2", "P": "GO:3", "Q1": "GO:4", "Q2": "GO:5",
           "T1": "GO:6", "T2": "GO:7"}
    terms = [Term(gid, name, "biological_process", False, (), (), ()) for name, gid in ids.items()]
    edges = [
        Edge(ids["S"], "is_a", ids["X"]), Edge(ids["S"], "is_a", ids["P"]),
        Edge(ids["X"], "is_a", ids["Q1"]), Edge(ids["Q1"], "is_a", ids["T1"]),
        Edge(ids["P"], "is_a", ids["T1"]), Edge(ids["X"], "is_a", ids["T2"]),
        Edge(ids["P"], "is_a", ids["Q2"]), Edge(ids["Q2"], "is_a", ids["T2"]),
    ]
    ann = Annotation("a1", "UniProtKB:S", "S", "involved_in", False, ids["S"], ids["S"], (),
                      "IDA", "ECO:0000314", (), "P", "protein", TAX, "", "2020-01-01",
                      "UniProt", "", "")
    return StaticFactStore(terms, edges, [ann]), ids


def test_shortest_depth_and_path_beat_both_dfs_orders():
    store, ids = _two_target_diamond_store()
    goals, _ = goals_for("UniProtKB:S", store)
    depth = {g["prop"]["term"]: g["depth"] for g in goals}
    assert depth[ids["T1"]] == 2 and depth[ids["T2"]] == 2

    for target in (ids["T1"], ids["T2"]):
        d = prove(Prop("UniProtKB:S", "involved_in", target, TAX, False), store)
        assert d is not None
        assert [s["rule"] for s in d["steps"]] == ["axiom", "is_a", "is_a"], target
        assert check(d, store)["errors"] == []


def test_applicable_lists_axiom_and_child_fragments_and_never_regulates():
    frags = applicable(_p(C), STORE)
    rules = sorted((f["rule"], f.get("edge", [None])[0]) for f in frags)
    assert ("axiom", None) in rules
    assert ("is_a", B) in rules and ("is_a", D) in rules and ("part_of", A) in rules
    assert not any(f["rule"] == "regulates" for f in frags)
    assert frags == [
        {"rule": "axiom", "conclusion": _p(C).to_dict()},
        {"rule": "is_a", "edge": [B, C], "conclusion": _p(C).to_dict()},
        {"rule": "is_a", "edge": [D, C], "conclusion": _p(C).to_dict()},
        {"rule": "part_of", "edge": [A, C], "conclusion": _p(C).to_dict()},
    ]
    assert applicable(_p(C, subject=P7), STORE) == []          # P00007 sits at R only


def test_applicable_is_empty_for_a_negated_prop():
    assert applicable(_p(C, negated=True), STORE) == []


def test_prove_returns_the_shortest_derivation():
    d = prove(_p(C, subject="UniProtKB:P00008"), STORE)
    assert d is not None
    assert [s["rule"] for s in d["steps"]] == ["axiom", "part_of"]
    assert d["steps"][1]["edge"] == [A, C]
    assert check(d, STORE)["errors"] == []


def test_prove_is_shortest_over_all_direct_annotations():
    d = prove(_p(T, subject=P2), STORE)
    assert [s["rule"] for s in d["steps"]] == ["axiom"] or d["steps"][0]["conclusion"]["term"] == T
    hidden = MaskedFactStore(STORE, frozenset(a.id for a in STORE.annotations(P2) if a.term == T))
    d = prove(_p(T, subject=P2), hidden)
    assert d["steps"][0]["conclusion"]["term"] == Y                # not X, though X sorts first
    assert len(d["steps"]) == 2 and check(d, hidden)["errors"] == []


def test_prove_tie_break_is_sorted_term_id():
    d = prove(_p(C, subject=P1), STORE)
    assert [s["rule"] for s in d["steps"]] == ["axiom"]           # direct wins
    masked = MaskedFactStore(
        STORE, frozenset(a.id for a in STORE.annotations(P1) if a.term == C and not a.negated))
    d = prove(_p(C, subject=P1), masked)
    # depth-1 routes: B is_a C, D is_a C, A part_of C — starting terms sorted: B < D < A
    assert d["steps"][0]["conclusion"]["term"] == B and d["steps"][1]["rule"] == "is_a"


def test_prove_returns_none_when_nothing_reaches_the_target():
    assert prove(_p(C, subject=P7), STORE) is None
    assert prove(_p(C, negated=True), STORE) is None
    assert prove(_p("GO:0009999"), STORE) is None


def test_tactics_skip_aspect_illegal_rows():
    """A loaded pair can be release-skewed (§1): a row's qualifier can be illegal for its
    term's aspect even though the loader faithfully kept it. Every tactic here must skip
    such a row rather than hand it back as a goal, a `prove` starting point, or an
    `applicable` fragment the kernel would refuse."""
    terms = [Term(id="GO:1", name="one", namespace="biological_process", obsolete=False,
                  replaced_by=(), consider=(), alt_ids=())]
    annotations = [
        # located_in is a C-aspect qualifier; GO:1 is biological_process (P aspect): illegal.
        Annotation(id="a1", subject="UniProtKB:X", symbol="X", qualifier="located_in",
                   negated=False, term="GO:1", term_raw="GO:1", references=("PMID:1",),
                   code="IDA", eco="ECO:0000314", with_from=(), aspect="C",
                   object_type="protein", taxon=TAX, interacting_taxon="",
                   date="2020-01-01", assigned_by="UniProt", extension="", form=""),
        # involved_in is P-aspect: legal at this same term.
        Annotation(id="a2", subject="UniProtKB:X", symbol="X", qualifier="involved_in",
                   negated=False, term="GO:1", term_raw="GO:1", references=("PMID:2",),
                   code="IDA", eco="ECO:0000314", with_from=(), aspect="P",
                   object_type="protein", taxon=TAX, interacting_taxon="",
                   date="2020-01-01", assigned_by="UniProt", extension="", form=""),
    ]
    store = StaticFactStore(terms, [], annotations)

    goals, report = goals_for("UniProtKB:X", store)
    assert [g["prop"]["qualifier"] for g in goals] == ["involved_in"]
    assert report["skipped_aspect_mismatch"] == 1

    assert prove(Prop("UniProtKB:X", "located_in", "GO:1", TAX, False), store) is None
    assert applicable(Prop("UniProtKB:X", "located_in", "GO:1", TAX, False), store) == []

    d = prove(Prop("UniProtKB:X", "involved_in", "GO:1", TAX, False), store)
    assert d is not None and check(d, store)["errors"] == []


def test_prove_output_is_accepted_by_the_kernel():
    for subject, term, qualifier in ((P1, B, "involved_in"), (P2, T, "involved_in"),
                                     (P3, MF1, "enables"), ("UniProtKB:P00004", "GO:0000300", "located_in")):
        d = prove(Prop(subject, qualifier, term, TAX, False), STORE)
        assert d is not None and check(d, STORE)["errors"] == [], (subject, term)
        assert d["goal"] == Prop(subject, qualifier, term, TAX, False).to_dict()


def test_applicable_is_empty_at_an_obsolete_or_unknown_target_even_with_a_row():
    """P00005 has a real IDA row at the obsolete term GO:0000110; the kernel would still refuse
    an axiom there (OBSOLETE_TERM), so `applicable` must not offer it."""
    assert STORE.matching(_p("GO:0000110", subject=P5)) != ()
    assert applicable(_p("GO:0000110", subject=P5), STORE) == []
    assert applicable(_p("GO:0009999", subject=P7), STORE) == []
