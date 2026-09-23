"""Tests for rpc.nvim_rpc."""

import subprocess
import types

import pytest

import rpc.nvim_rpc as nvim_rpc


def _capture_expr(monkeypatch, cmd, returncode=0):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["expr"] = argv[argv.index("--remote-expr") + 1]
        return types.SimpleNamespace(returncode=returncode, stdout="", stderr="")

    monkeypatch.setattr(nvim_rpc.subprocess, "run", fake_run)
    ok = nvim_rpc.nvim_exec("/tmp/sock", cmd)
    return ok, captured["expr"]


def test_plain_command_wrapped_in_execute(monkeypatch):
    ok, expr = _capture_expr(monkeypatch, "w")
    assert ok is True
    assert expr == 'execute("w")'


def test_quotes_are_escaped(monkeypatch):
    _, expr = _capture_expr(monkeypatch, 'echo "hi"')
    assert expr == 'execute("echo \\"hi\\"")'


def test_injection_attempt_stays_inside_string(monkeypatch):
    payload = 'x") | call system("evil")|echo("'
    _, expr = _capture_expr(monkeypatch, payload)
    assert expr.startswith('execute("') and expr.endswith('")')
    inner = expr[len('execute("'):-2]
    # No unescaped double quote survives inside the literal.
    assert '"' not in inner.replace('\\"', "")


def test_backslash_escaped_before_quote(monkeypatch):
    _, expr = _capture_expr(monkeypatch, 'a\\b')
    assert expr == 'execute("a\\\\b")'


def test_nonzero_returncode_is_false(monkeypatch):
    ok, _ = _capture_expr(monkeypatch, "w", returncode=1)
    assert ok is False


def test_subprocess_error_returns_false(monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd="nvim", timeout=2)

    monkeypatch.setattr(nvim_rpc.subprocess, "run", fake_run)
    assert nvim_rpc.nvim_exec("/tmp/sock", "w") is False


def test_keyboardinterrupt_propagates(monkeypatch):
    def fake_run(argv, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(nvim_rpc.subprocess, "run", fake_run)
    with pytest.raises(KeyboardInterrupt):
        nvim_rpc.nvim_exec("/tmp/sock", "w")
