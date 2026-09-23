"""Tests for rpc.nvim_rpc."""

import subprocess
import types

import pytest

import rpc.nvim_rpc as nvim_rpc


def _capture_keys(monkeypatch, cmd, returncode=0):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["keys"] = argv[argv.index("--remote-send") + 1]
        captured["argv"] = argv
        return types.SimpleNamespace(returncode=returncode, stdout="", stderr="")

    monkeypatch.setattr(nvim_rpc.subprocess, "run", fake_run)
    ok = nvim_rpc.nvim_exec("/tmp/sock", cmd)
    return ok, captured


def test_command_sent_in_commandline_mode(monkeypatch):
    ok, cap = _capture_keys(monkeypatch, "w")
    assert ok is True
    # normal-mode guard, clean command line, command, execute
    assert cap["keys"] == r'<C-\><C-N>:<C-u>w<CR>'
    assert cap["argv"][:3] == ["nvim", "--server", "/tmp/sock"]


def test_uses_remote_send_not_remote_expr(monkeypatch):
    _, cap = _capture_keys(monkeypatch, "w")
    assert "--remote-send" in cap["argv"]
    assert "--remote-expr" not in cap["argv"]


def test_angle_bracket_escaped_to_lt(monkeypatch):
    # A literal '<' must become '<lt>' so it is not parsed as a key code.
    _, cap = _capture_keys(monkeypatch, "echo a < b")
    assert "<lt>" in cap["keys"]
    assert cap["keys"] == r'<C-\><C-N>:<C-u>echo a <lt> b<CR>'


def test_quotes_pass_through_literally(monkeypatch):
    # No vimscript string context anymore, so quotes need no escaping.
    _, cap = _capture_keys(monkeypatch, 'echo "hi"')
    assert cap["keys"] == r'<C-\><C-N>:<C-u>echo "hi"<CR>'


def test_nonzero_returncode_is_false(monkeypatch):
    ok, _ = _capture_keys(monkeypatch, "w", returncode=1)
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
