# methods-graph — reproducible pipeline entry points.
# PY auto-selects the local venv if present, else system python (so CI works unchanged).
PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python)
MG := $(PY) -m methods_graph.cli

.PHONY: help rebuild rebuild-check verify explain audit test

help:
	@echo "make rebuild        verify snapshots -> build -> audit gate -> lock + coverage-diff"
	@echo "make rebuild-check  rebuild and assert the graph hash matches the committed lock"
	@echo "make verify         diff the working-tree lock vs the committed lock (no rebuild)"
	@echo "make explain ARGS='--method m:scanpy'   trace a method/skill's evaluability"
	@echo "make audit          run graph invariant checks"
	@echo "make test           run the pytest suite"

rebuild:
	$(MG) rebuild

rebuild-check:
	$(MG) rebuild --check

verify:
	$(MG) rebuild --diff-only

explain:
	$(MG) explain $(ARGS)

audit:
	$(MG) audit --db data/methods.kuzu

test:
	$(PY) -m pytest -q
