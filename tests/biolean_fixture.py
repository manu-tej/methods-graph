"""The one fixture inventory, loaded from the three files under tests/fixtures/biolean."""
import shutil
from pathlib import Path

from methods_graph.biolean.eco import parse_eco_mapping
from methods_graph.biolean.gaf import parse_gaf
from methods_graph.biolean.obo import parse_go_basic
from methods_graph.biolean.store import StaticFactStore, load_store

FIX = Path(__file__).parent / "fixtures" / "biolean"
RELEASE = {"go_basic_data_version": "releases/2026-01-01", "goa_date_generated": "2026-01-01",
           "goa_go_version": ""}


def mini_store() -> StaticFactStore:
    store, _ = load_store(FIX, obo="go-mini.obo", gaf="goa-mini.gaf", eco="eco-mini.txt")
    return store


def mini_report() -> dict:
    _, report = load_store(FIX, obo="go-mini.obo", gaf="goa-mini.gaf", eco="eco-mini.txt")
    return report


def reversed_store() -> StaticFactStore:
    """The same facts with the GAF rows fed in reverse order: for order-independence tests."""
    terms, edges, _ = parse_go_basic((FIX / "go-mini.obo").read_text())
    eco_map, _ = parse_eco_mapping((FIX / "eco-mini.txt").read_text())
    by_id = {t.id: t for t in terms}
    alt = {a: t.id for t in terms for a in t.alt_ids}
    lines = list(reversed((FIX / "goa-mini.gaf").read_text().splitlines()))
    annotations, _ = parse_gaf(lines, eco_map, lambda g: g if g in by_id else alt.get(g), by_id.get)
    return StaticFactStore(terms, edges, annotations)


def copy_store(dest: Path) -> Path:
    """The fixture files under the names `mg biolean --store` expects (plain GAF, not gz)."""
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIX / "go-mini.obo", dest / "go-basic.obo")
    shutil.copy(FIX / "goa-mini.gaf", dest / "goa_human.gaf")
    shutil.copy(FIX / "eco-mini.txt", dest / "gaf-eco-mapping.txt")
    return dest
