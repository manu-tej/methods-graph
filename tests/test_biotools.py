"""Tests for the bio.tools EDAM enrichment connector."""
import json
import pytest
from pathlib import Path

from methods_graph.connectors.biotools import (
    _biotools_record_to_edam,
    load_biotools_edam,
)

# Path to the shared test fixtures directory
FX = Path(__file__).parent / "fixtures"


class TestBiotoolsRecordToEdam:
    def test_extracts_ops_and_topics(self):
        """Feed the salmon fixture record and assert correct sorted node ids."""
        record = json.loads((FX / "biotools" / "salmon.json").read_text())
        result = _biotools_record_to_edam(record)

        assert result["biotools_id"] == "salmon"
        # operation_2495 < operation_3800 lexicographically (sorted by full node id string)
        assert result["operations"] == ["op:operation_2495", "op:operation_3800"]
        assert result["topics"] == ["topic:topic_3170"]

    def test_robust_to_missing_keys(self):
        """Record with no function/topic keys → empty lists, no crash."""
        record = {"biotoolsID": "minimal_tool"}
        result = _biotools_record_to_edam(record)

        assert result["biotools_id"] == "minimal_tool"
        assert result["operations"] == []
        assert result["topics"] == []

    def test_robust_to_empty_lists(self):
        """Record with empty function/topic → empty lists."""
        record = {"biotoolsID": "empty_tool", "function": [], "topic": []}
        result = _biotools_record_to_edam(record)

        assert result["operations"] == []
        assert result["topics"] == []

    def test_robust_to_missing_biotools_id(self):
        """Record with no biotoolsID → empty string id, lists populated normally."""
        record = {
            "topic": [{"uri": "http://edamontology.org/topic_3170", "term": "RNA-Seq"}],
        }
        result = _biotools_record_to_edam(record)

        assert result["biotools_id"] == ""
        assert result["topics"] == ["topic:topic_3170"]

    def test_deduplicates_and_sorts(self):
        """Duplicate URIs across function blocks are deduped and sorted."""
        record = {
            "biotoolsID": "duptest",
            "function": [
                {"operation": [{"uri": "http://edamontology.org/operation_3800", "term": "A"}]},
                {"operation": [{"uri": "http://edamontology.org/operation_3800", "term": "A dup"}]},
                {"operation": [{"uri": "http://edamontology.org/operation_2495", "term": "B"}]},
            ],
            "topic": [],
        }
        result = _biotools_record_to_edam(record)

        # Should be deduped and sorted
        assert result["operations"] == ["op:operation_2495", "op:operation_3800"]

    def test_skips_non_op_topic_uris(self):
        """data_ and format_ URIs are ignored in operations/topics."""
        record = {
            "biotoolsID": "multikind",
            "function": [
                {
                    "operation": [
                        {"uri": "http://edamontology.org/operation_3798", "term": "Read summarisation"},
                        {"uri": "http://edamontology.org/data_3494", "term": "DNA sequence"},
                    ]
                }
            ],
            "topic": [
                {"uri": "http://edamontology.org/format_1930", "term": "FASTQ"},
                {"uri": "http://edamontology.org/topic_3170", "term": "RNA-Seq"},
            ],
        }
        result = _biotools_record_to_edam(record)

        # data_ in function.operation should be skipped (only op: extracted)
        assert result["operations"] == ["op:operation_3798"]
        # format_ in topic should be skipped (only topic: extracted)
        assert result["topics"] == ["topic:topic_3170"]

    def test_handles_none_values_gracefully(self):
        """Explicit None for function/topic → empty lists, no crash."""
        record = {"biotoolsID": "nulltest", "function": None, "topic": None}
        result = _biotools_record_to_edam(record)

        assert result["operations"] == []
        assert result["topics"] == []


class TestLoadBiotoolsEdam:
    def test_maps_by_lowercased_id(self, tmp_path):
        """Records keyed by lowercased biotoolsID; empty-id records are skipped."""
        # Write a record with mixed-case biotoolsID
        salmon_data = {
            "biotoolsID": "Salmon",
            "topic": [{"uri": "http://edamontology.org/topic_3170", "term": "RNA-Seq"}],
            "function": [],
        }
        (tmp_path / "Salmon.json").write_text(json.dumps(salmon_data))

        # Write a record with empty biotoolsID — should be skipped
        empty_data = {"biotoolsID": "", "function": [], "topic": []}
        (tmp_path / "empty.json").write_text(json.dumps(empty_data))

        result = load_biotools_edam(tmp_path)

        assert "salmon" in result, f"Expected 'salmon' in map; got keys: {list(result)}"
        assert "Salmon" not in result, "Key must be lowercased"
        assert "" not in result, "Empty-id records must be skipped"

        assert result["salmon"]["topics"] == ["topic:topic_3170"]
        assert result["salmon"]["operations"] == []

    def test_skips_malformed_json(self, tmp_path):
        """Malformed JSON files are skipped without crashing."""
        good_data = {
            "biotoolsID": "good_tool",
            "function": [{"operation": [{"uri": "http://edamontology.org/operation_3800", "term": "X"}]}],
            "topic": [],
        }
        (tmp_path / "good.json").write_text(json.dumps(good_data))
        (tmp_path / "bad.json").write_text("NOT VALID JSON {{{{")

        result = load_biotools_edam(tmp_path)

        assert "good_tool" in result
        assert len(result) == 1  # bad.json did not crash; was silently skipped

    def test_reads_fixture_dir(self):
        """Smoke test: the real biotools fixture directory loads correctly."""
        result = load_biotools_edam(FX / "biotools")

        assert "salmon" in result
        assert result["salmon"]["operations"] == ["op:operation_2495", "op:operation_3800"]
        assert result["salmon"]["topics"] == ["topic:topic_3170"]

    def test_empty_dir_returns_empty_map(self, tmp_path):
        """An empty directory yields an empty map without error."""
        result = load_biotools_edam(tmp_path)
        assert result == {}

    def test_deterministic_on_multiple_files(self, tmp_path):
        """Results are the same regardless of filesystem ordering."""
        for i, name in enumerate(["bwa", "star", "hisat2"]):
            data = {
                "biotoolsID": name,
                "function": [{"operation": [{"uri": f"http://edamontology.org/operation_{3800 + i}", "term": "X"}]}],
                "topic": [],
            }
            (tmp_path / f"{name}.json").write_text(json.dumps(data))

        r1 = load_biotools_edam(tmp_path)
        r2 = load_biotools_edam(tmp_path)

        assert sorted(r1.keys()) == sorted(r2.keys())
        for k in r1:
            assert r1[k] == r2[k]
