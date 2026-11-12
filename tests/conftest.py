"""Repo-wide fixtures. The ledger's verification cache defaults to ~/.cache/biolean-ledger/;
no ledger test may touch the real home directory, so HOME points at tmp_path for them."""
import pytest


@pytest.fixture(autouse=True)
def _ledger_tests_never_touch_home(request, tmp_path, monkeypatch):
    module = getattr(request, "module", None)
    if module is not None and "biolean_ledger" in module.__name__:
        monkeypatch.setenv("HOME", str(tmp_path))
