"""A contestant is a callable ``(prompt: str) -> str``. That is the whole contract.

Nothing model-specific reaches the scorer, so adding a model is adding a function here
and nothing else. Network and subprocess calls take injectable seams — the same pattern
``fetch.py`` uses — so the test suite never makes a request.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class AdapterError(RuntimeError):
    """A contestant could not be reached or answered unusably.

    Distinct from an empty answer: the runner records this against the item and keeps
    going, so one rate limit does not discard a whole run, and a failed call is never
    scored as if the model had declined to answer.
    """


def static(responses: dict[str, str] | list[str]) -> Callable[[str], str]:
    """Replay canned responses — by prompt if a dict, in order if a list."""
    if isinstance(responses, dict):
        table = dict(responses)

        def _by_prompt(prompt: str) -> str:
            if prompt not in table:
                raise AdapterError(f"static adapter has no response for: {prompt!r}")
            return table[prompt]

        return _by_prompt

    queue = list(responses)
    index = {"n": 0}

    def _in_order(_prompt: str) -> str:
        if index["n"] >= len(queue):
            raise AdapterError("static adapter exhausted")
        value = queue[index["n"]]
        index["n"] += 1
        return value

    return _in_order


def claude_cli(
    *, model: str, timeout: int = 300, runner: Callable[..., Any] = subprocess.run,
) -> Callable[[str], str]:
    """Headless ``claude -p`` — no API key needed, uses the local CLI's auth."""

    def _call(prompt: str) -> str:
        cmd = ["claude", "-p", prompt, "--model", model]
        try:
            completed = runner(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AdapterError(f"claude CLI timed out after {timeout}s") from None
        except OSError as exc:
            raise AdapterError(f"claude CLI could not be run: {exc}") from exc
        if completed.returncode != 0:
            raise AdapterError(
                f"claude CLI exited {completed.returncode}: {completed.stderr.strip()}")
        return completed.stdout.strip()

    return _call


def _urllib_post(
    url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int,
) -> Any:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AdapterError(f"OpenAI request failed: {exc}") from exc


def openai(
    *,
    model: str,
    api_key: str | None = None,
    timeout: int = 120,
    http_post: Callable[..., Any] | None = None,
    _env: dict[str, str] | None = None,
) -> Callable[[str], str]:
    """OpenAI chat completions at temperature 0, over stdlib urllib."""
    env = os.environ if _env is None else _env
    key = api_key or env.get("OPENAI_API_KEY")
    if not key:
        raise AdapterError("OPENAI_API_KEY is not set and no api_key was passed")
    post = http_post or _urllib_post

    def _call(prompt: str) -> str:
        body = post(
            _OPENAI_URL,
            {"model": model, "temperature": 0,
             "messages": [{"role": "user", "content": prompt}]},
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout,
        )
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise AdapterError(f"unexpected response shape: {body!r}") from None

    return _call


def get_adapter(spec: str) -> Callable[[str], str]:
    """``claude:<model>`` / ``openai:<model>`` / ``static:<path-to-json>``.

    The ``gold:``/``modal:``/``random:<seed>`` baselines are resolved by
    :func:`methods_graph.bench.baselines.baseline_adapter` instead — they need the item
    set and the oracle, which a spec string cannot carry.
    """
    provider, _, argument = spec.partition(":")
    if provider == "claude":
        return claude_cli(model=argument or "claude-opus-5")
    if provider == "openai":
        return openai(model=argument or "gpt-4o")
    if provider == "static":
        try:
            blob = Path(argument).read_text()
        except OSError as exc:
            # A typo'd --model must not print a stack trace.
            raise AdapterError(f"static adapter file not readable: {exc}") from exc
        try:
            return static(json.loads(blob))
        except json.JSONDecodeError as exc:
            raise AdapterError(f"static adapter file is not valid JSON: {exc}") from exc
    raise AdapterError(
        f"unknown adapter {spec!r} (expected claude:, openai:, static:, "
        f"gold:, modal: or random:<seed>)")
