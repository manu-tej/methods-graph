import json
import subprocess

import pytest

from methods_graph.bench.adapters import (
    AdapterError, claude_cli, get_adapter, openai, static)


def test_static_replays_by_prompt():
    adapter = static({"Goal: A": '["fastqc"]', "Goal: B": '["star"]'})
    assert adapter("Goal: B") == '["star"]'


def test_static_replays_a_list_in_order():
    adapter = static(['["a"]', '["b"]'])
    assert adapter("anything") == '["a"]'
    assert adapter("anything else") == '["b"]'


def test_static_raises_when_it_runs_out_rather_than_repeating():
    adapter = static(['["a"]'])
    adapter("one")
    with pytest.raises(AdapterError, match="exhausted"):
        adapter("two")


def test_claude_cli_sends_the_prompt_and_returns_stdout():
    seen = {}

    def _runner(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout='["fastqc"]\n', stderr="")

    adapter = claude_cli(model="claude-opus-5", runner=_runner)
    assert adapter("Goal: X") == '["fastqc"]'
    assert "-p" in seen["cmd"]
    assert "Goal: X" in seen["cmd"]
    assert "claude-opus-5" in seen["cmd"]


def test_claude_cli_nonzero_exit_raises_with_stderr():
    def _runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="quota exceeded")

    with pytest.raises(AdapterError, match="quota exceeded"):
        claude_cli(model="claude-opus-5", runner=_runner)("Goal: X")


def test_claude_cli_timeout_raises_adapter_error():
    def _runner(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 300)

    with pytest.raises(AdapterError, match="timed out"):
        claude_cli(model="claude-opus-5", runner=_runner)("Goal: X")


def test_openai_posts_temperature_zero_and_returns_the_message():
    seen = {}

    def _post(url, payload, headers, timeout):
        seen.update(url=url, payload=payload, headers=headers)
        return {"choices": [{"message": {"content": '["fastqc"]'}}]}

    adapter = openai(model="gpt-4o", api_key="sk-test", http_post=_post)
    assert adapter("Goal: X") == '["fastqc"]'
    assert seen["payload"]["temperature"] == 0
    assert seen["payload"]["model"] == "gpt-4o"
    assert seen["headers"]["Authorization"] == "Bearer sk-test"


def test_openai_without_a_key_raises_before_any_request():
    with pytest.raises(AdapterError, match="OPENAI_API_KEY"):
        openai(model="gpt-4o", api_key=None, http_post=None, _env={})


def test_openai_malformed_response_raises_rather_than_returning_empty():
    with pytest.raises(AdapterError, match="unexpected response"):
        openai(model="gpt-4o", api_key="sk-test",
               http_post=lambda *a, **k: {"error": "boom"})("Goal: X")


def test_get_adapter_parses_provider_and_model():
    assert callable(get_adapter("claude:claude-opus-5"))


def test_get_adapter_parses_openai_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert callable(get_adapter("openai:gpt-4o"))


def test_get_adapter_rejects_an_unknown_provider():
    with pytest.raises(AdapterError, match="unknown adapter"):
        get_adapter("mystery:model-x")


def test_static_raises_when_prompt_not_in_dict():
    adapter = static({"Goal: A": '["fastqc"]', "Goal: B": '["star"]'})
    with pytest.raises(AdapterError, match="no response for"):
        adapter("Goal: C")


def test_claude_cli_raises_when_binary_cannot_be_run():
    def _runner(cmd, **kwargs):
        raise OSError("No such file or directory")

    with pytest.raises(AdapterError, match="could not be run"):
        claude_cli(model="claude-opus-5", runner=_runner)("Goal: X")


def test_get_adapter_loads_a_static_file(tmp_path):
    path = tmp_path / "canned.json"
    path.write_text(json.dumps({"Goal: A": '["fastqc"]'}))
    assert get_adapter(f"static:{path}")("Goal: A") == '["fastqc"]'
