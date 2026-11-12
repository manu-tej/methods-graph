"""Fixture inventory for the ledger tests: the ledger base, the two keys, helpers.

Task 8 adds the fake runner, the signed ledger copies and the append scenarios.
"""
from pathlib import Path
import shutil

from methods_graph.biolean.gaf import GAF_COLUMNS
from methods_graph.biolean.ledger.check import CheckContext
from methods_graph.biolean.store import BaseLoad, StaticFactStore, load_base

LFIX = Path(__file__).parent / "fixtures" / "biolean" / "ledger"
KEY_A, KEY_B = LFIX / "keys" / "a", LFIX / "keys" / "b"
PUB_A, PUB_B = LFIX / "keys" / "a.pub", LFIX / "keys" / "b.pub"
KEY16_A, KEY16_B = "1438014318807ad1", "778b5c6aae736dad"
DIGEST_A = "1438014318807ad1a74d1943c05793434d3cbd11009797a646bbc3cd68c7c51e"
DIGEST_B = "778b5c6aae736dad91e838b21ac186bf8590c64cf94e73db1c27c69c53de34d0"
BY_A, BY_B = "sha256:" + DIGEST_A, "sha256:" + DIGEST_B
TS = "2026-09-25T10:00:00Z"
LEDGER_ID = "0123456789abcdef0123456789abcdef"
BASE_FILES = {"obo": "ledger.obo", "gaf": "ledger.gaf", "eco": "ledger-eco.txt"}
RELEASE = {"go_basic_data_version": "releases/2026-02-02", "goa_date_generated": "2026-02-02",
           "goa_go_version": "http://purl.obolibrary.org/obo/go/releases/2026-02-02/extensions/go-plus.ofn"}


def ledger_base() -> BaseLoad:
    return load_base(LFIX, **BASE_FILES)


def ledger_store() -> StaticFactStore:
    base = ledger_base()
    return StaticFactStore(base.terms, base.edges, base.annotations)


def copy_ledger_store(dest: Path) -> Path:
    """The fixture base under the names `mg biolean --store` expects (plain GAF, not gz)."""
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(LFIX / "ledger.obo", dest / "go-basic.obo")
    shutil.copy(LFIX / "ledger.gaf", dest / "goa_human.gaf")
    shutil.copy(LFIX / "ledger-eco.txt", dest / "gaf-eco-mapping.txt")
    return dest


def context(key16: str = KEY16_A, *, store=None, sources=None, base: BaseLoad | None = None) -> CheckContext:
    base = base or ledger_base()
    return CheckContext(
        store=store if store is not None else StaticFactStore(base.terms, base.edges, base.annotations),
        eco_map=base.eco_map, primary_id=base.primary_id, term=base.term, key16=key16,
        ledger_sources=dict(sources or {}))


def new_fact(**overrides) -> list[str]:
    """A valid new fact for the fixture base (P10002 involved_in GO:0000003, cited by DOI).
    Keyword names are GAF column names; a value replaces that column."""
    row = ["UniProtKB", "P10002", "G2", "involved_in", "GO:0000003", "DOI:10.1038/s41586-026-00001-0",
           "IDA", "", "P", "", "", "protein", "taxon:9606", "20260925", "", "", ""]
    for name, value in overrides.items():
        row[GAF_COLUMNS.index(name)] = value
    return row


def base_row(n: int) -> list[str]:
    """The n-th (1-based) data row of ledger.gaf as a 17-list."""
    rows = [line.split("\t") for line in (LFIX / "ledger.gaf").read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("!")]
    return rows[n - 1]


# ---------------------------------------------------------------------------
# signing without a subprocess: content-addressed real armor (spec section 9, "No subprocess")
# ---------------------------------------------------------------------------
import hashlib
import types
from dataclasses import dataclass
from typing import Any

from methods_graph.biolean.ledger.append import AppendResult, append_entry, init_ledger
from methods_graph.biolean.sshsig import NAMESPACE, allowed_signers_line, parse_public_key_line

SIGS = LFIX / "sigs"
SIGNED = LFIX / "signed"


def fake_runner(argv, *, input, capture_output, check, **extra):
    """The `runner` seam for tests. Asserts the exact argv, returns armor real ssh-keygen made over
    exactly these bytes. A miss means make_fixtures.py must be re-run."""
    assert extra == {}, f"unexpected runner kwargs {sorted(extra)} (text= would break the armor)"
    assert argv[:4] == ["ssh-keygen", "-Y", "sign", "-f"] and argv[4:] == [argv[4], "-n", NAMESPACE] and len(argv) == 7, argv
    assert capture_output is True and check is True and isinstance(input, bytes)
    path = SIGS / (hashlib.sha256(input).hexdigest() + ".sig")
    assert path.is_file(), (f"no fixture signature for these bytes ({path.name}); the entry, base or "
                            "kernel version changed: run tests/fixtures/biolean/ledger/make_fixtures.py")
    return types.SimpleNamespace(stdout=path.read_bytes(), stderr=b"", returncode=0)


def copy_signed(dest: Path) -> Path:
    shutil.copytree(SIGNED, dest, dirs_exist_ok=True)
    return dest


def signed_store(tmp_path: Path, *, replay: bool = False) -> tuple[Path, Path]:
    """(ledger dir, store dir): a copy of signed/ beside a copy of the base. With replay=True the
    ledger is rebuilt from SIGNED_SEQUENCE through the fake runner instead of copied."""
    store = copy_ledger_store(tmp_path / "store")
    ledger = tmp_path / "ledger"
    if replay:
        build_signed(ledger, store, runner=fake_runner)
    else:
        copy_signed(ledger)
    return ledger, store


@dataclass(frozen=True)
class Scenario:
    kind: str
    body: Any
    key: Path
    start: str          # "fresh" (init a new ledger with key A, list B too) or "signed" (a copy of signed/)
    ts: str = TS


def _fact(**over):
    return new_fact(**over)


# The appends that build signed/: three axioms by A, one axiom by B, one derived by A.
SIGNED_SEQUENCE: tuple[tuple[Path, str, Any], ...] = (
    (KEY_A, "axiom", _fact()),                                                                 # P10002 involved_in GO:0000003, DOI
    (KEY_A, "axiom", _fact(db_object_id="P10006", db_object_symbol="G6", db_reference="DOI:10.1000/ledger.6")),   # new subject
    (KEY_A, "axiom", _fact(db_object_id="P10001", db_object_symbol="G1", db_reference="PMID:300")),               # contested by the NOT row
    (KEY_B, "axiom", _fact(db_object_id="P10004", db_object_symbol="G4", go_id="GO:0000001", db_reference="PMID:400", evidence_code="IMP")),
    (KEY_A, "derived", {"derivation": {"biolean": "0.1",
                                       "goal": {"subject": "UniProtKB:P10003", "qualifier": "involved_in", "term": "GO:0000002", "taxon": "NCBITaxon:9606", "negated": False},
                                       "steps": [{"id": "s1", "rule": "axiom", "conclusion": {"subject": "UniProtKB:P10003", "qualifier": "involved_in", "term": "GO:0000003", "taxon": "NCBITaxon:9606", "negated": False}},
                                                 {"id": "s2", "rule": "is_a", "premises": ["s1"], "edge": ["GO:0000003", "GO:0000002"],
                                                  "conclusion": {"subject": "UniProtKB:P10003", "qualifier": "involved_in", "term": "GO:0000002", "taxon": "NCBITaxon:9606", "negated": False}}],
                                       "root": "s2"}}),
)

# Every accepted append a test performs, by name. Rejected appends never reach the runner.
SCENARIOS: dict[str, Scenario] = {
    "fresh-axiom": Scenario("axiom", _fact(), KEY_A, "fresh"),
    "fresh-axiom-object": Scenario("axiom", dict(zip(GAF_COLUMNS, _fact())), KEY_A, "fresh"),
    "signed-append-a": Scenario("axiom", _fact(db_object_id="P10005", db_object_symbol="G5", go_id="GO:0000002", db_reference="PMID:500"), KEY_A, "signed"),
    "signed-append-b": Scenario("axiom", _fact(db_object_id="P10005", db_object_symbol="G5", go_id="GO:0000002", db_reference="PMID:501"), KEY_B, "signed"),
    "signed-derived-elaborated": Scenario("derived", {"derivation": {"goal": {"subject": "G3", "qualifier": "involved_in", "term": "GO:0000002", "taxon": "taxon:9606", "negated": False},
                                                                     "steps": [{"id": "s1", "rule": "axiom", "conclusion": {"subject": "G3", "qualifier": "involved_in", "term": "GO:0000003", "taxon": "9606", "negated": False}},
                                                                               {"id": "s2", "rule": "is_a", "premises": ["s1"], "edge": ["GO:0000003", "GO:0000002"],
                                                                                "conclusion": {"subject": "UniProtKB:P10003", "qualifier": "involved_in", "term": "GO:0000002", "taxon": "NCBITaxon:9606", "negated": False}}],
                                                                     "root": "s2"}}, KEY_A, "signed"),
    "cli-fresh-axiom": Scenario("axiom", _fact(db_reference="PMID:900"), KEY_A, "fresh"),
    "cli-signed-axiom": Scenario("axiom", _fact(db_object_id="P10005", db_object_symbol="G5", go_id="GO:0000002", db_reference="PMID:502"), KEY_A, "signed"),
}


def fresh_ledger(ledger: Path, store: Path) -> Path:
    """`init` with key A (fixed ledger id), then list key B as well, as the owner would."""
    init_ledger(ledger, store_dir=store, key=PUB_A, principal="fixture-a", gaf="goa_human.gaf", ledger_id=LEDGER_ID,
                allow_fixture_keys=True)
    blob_b, comment_b = parse_public_key_line(PUB_B.read_text())
    with (ledger / "allowed_signers").open("a", encoding="utf-8") as fh:
        fh.write(allowed_signers_line("fixture-b", blob_b, comment_b))
    return ledger


def build_signed(ledger: Path, store: Path, *, runner) -> Path:
    """signed/ from SIGNED_SEQUENCE: init, then the five appends in order."""
    fresh_ledger(ledger, store)
    for key, kind, body in SIGNED_SEQUENCE:
        res = append_entry(ledger, kind=kind, body=body, key=key, ts=TS, runner=runner,
                           store_dir=store, gaf="goa_human.gaf", use_cache=False)
        assert res.verdict == "ACCEPTED", [e.to_dict() for e in res.errors]
    return ledger


def run_scenario(name: str, tmp_path: Path, *, runner=fake_runner) -> tuple[AppendResult, Path, Path]:
    scn = SCENARIOS[name]
    store = copy_ledger_store(tmp_path / "store")
    ledger = tmp_path / "ledger"
    if scn.start == "fresh":
        fresh_ledger(ledger, store)
    else:
        copy_signed(ledger)
    res = append_entry(ledger, kind=scn.kind, body=scn.body, key=scn.key, ts=scn.ts, runner=runner,
                       store_dir=store, gaf="goa_human.gaf", use_cache=False)
    return res, ledger, store
