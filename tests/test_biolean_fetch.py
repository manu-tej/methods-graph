import gzip
import hashlib
import json
from pathlib import Path

import pytest

from methods_graph import fetch

GAF = ("!gaf-version: 2.2\n!generated-by: GOC\n!date-generated: 2026-05-21T08:10\n"
       "!go-version: http://purl.obolibrary.org/obo/go/releases/2026-04-27/extensions/go-plus.ofn\n"
       "UniProtKB\tP1\tG\tinvolved_in\tGO:1\tPMID:1\tIDA\t\tP\tg\t\tprotein\ttaxon:9606\t20200101\tUniProt\t\t\n")
OBO = "format-version: 1.2\ndata-version: releases/2026-04-27\n\n[Term]\nid: GO:1\nname: x\nnamespace: biological_process\n"
ECO = "# mapping\nIDA\tDefault\tECO:0000314\n"


def _http(calls):
    def http_get(url):
        calls.append(url)
        if url.endswith("goa_human.gaf.gz"):
            return gzip.compress(GAF.encode()), {}
        if url.endswith("go-basic.obo"):
            return OBO.encode(), {}
        if url.endswith("gaf-eco-mapping.txt"):
            return ECO.encode(), {}
        raise AssertionError(url)
    return http_get


def test_gaf_header_reads_gzipped_and_plain_and_extracts_the_release():
    expect = {"date_generated": "2026-05-21T08:10",
              "go_version": "http://purl.obolibrary.org/obo/go/releases/2026-04-27/extensions/go-plus.ofn",
              "go_release": "2026-04-27"}
    assert fetch.gaf_header(gzip.compress(GAF.encode())) == expect
    assert fetch.gaf_header(GAF.encode()) == expect
    assert fetch.gaf_header(b"no header\n") == {"date_generated": "", "go_version": "", "go_release": ""}


def test_go_basic_url_is_pinned_to_the_release_or_latest():
    assert fetch.go_basic_release_url("2026-04-27") == "http://purl.obolibrary.org/obo/go/releases/2026-04-27/go-basic.obo"
    assert fetch.go_basic_release_url(None) == fetch.GO_BASIC_LATEST_URL


def test_fetch_biolean_downloads_the_obo_at_the_gaf_release_and_writes_the_manifest(tmp_path):
    calls = []
    manifest = fetch.fetch_biolean(tmp_path, fetched_at="2026-09-21T00:00:00Z", http_get=_http(calls))
    assert calls == [fetch.GOA_HUMAN_URL,
                     "http://purl.obolibrary.org/obo/go/releases/2026-04-27/go-basic.obo",
                     fetch.ECO_MAPPING_URL]
    assert (tmp_path / "goa_human.gaf.gz").exists() and (tmp_path / "go-basic.obo").read_text() == OBO
    assert (tmp_path / "gaf-eco-mapping.txt").read_text() == ECO
    on_disk = json.loads((tmp_path / "snapshot.json").read_text())
    assert on_disk == manifest
    assert set(manifest) == {"created_at", "sources"}
    assert set(manifest["sources"]) == {"goa_human", "go_basic", "gaf_eco_mapping"}
    assert manifest["sources"]["go_basic"]["version"] == {"data_version": "releases/2026-04-27", "release": "2026-04-27"}
    assert manifest["sources"]["goa_human"]["version"]["go_release"] == "2026-04-27"
    assert manifest["sources"]["go_basic"]["sha256"] == hashlib.sha256(OBO.encode()).hexdigest()
    assert manifest["created_at"] == "2026-09-21T00:00:00Z"
    text = (tmp_path / "snapshot.json").read_text()
    assert text == json.dumps(on_disk, sort_keys=True, indent=2) + "\n"


def test_fetch_biolean_falls_back_to_latest_when_the_gaf_names_no_release(tmp_path):
    calls = []
    plain = GAF.replace("!go-version: http://purl.obolibrary.org/obo/go/releases/2026-04-27/extensions/go-plus.ofn\n", "")

    def http_get(url):
        calls.append(url)
        return (gzip.compress(plain.encode()) if url.endswith(".gz") else
                OBO.encode() if url.endswith(".obo") else ECO.encode()), {}
    manifest = fetch.fetch_biolean(tmp_path, fetched_at="t", http_get=http_get)
    assert calls[1] == fetch.GO_BASIC_LATEST_URL
    assert manifest["sources"]["go_basic"]["version"]["release"] == ""


def test_http_get_defaults_resolve_at_call_time(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(fetch, "_stdlib_http_get", _http(calls))
    fetch.fetch_eco_mapping(tmp_path, fetched_at="t")
    assert calls == [fetch.ECO_MAPPING_URL]
