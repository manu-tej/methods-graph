"""Kùzu DDL. Single Entity node table + single Rel rel table with kind discriminators."""

NODE_TABLE = """
CREATE NODE TABLE IF NOT EXISTS Entity(
    id STRING PRIMARY KEY,
    name STRING,
    kind STRING,
    properties STRING,
    bioconda_pkg STRING,
    biotools_id STRING,
    source STRING,
    source_url STRING,
    ingested_at STRING
)
"""

REL_TABLE = """
CREATE REL TABLE IF NOT EXISTS Rel(
    FROM Entity TO Entity,
    kind STRING,
    properties STRING,
    source STRING,
    source_url STRING,
    ingested_at STRING
)
"""

# Column order MUST match the Parquet files written by the loader.
NODE_COLUMNS = ["id", "name", "kind", "properties", "bioconda_pkg", "biotools_id",
                "source", "source_url", "ingested_at"]
REL_COLUMNS = ["from_id", "to_id", "kind", "properties", "source", "source_url", "ingested_at"]
