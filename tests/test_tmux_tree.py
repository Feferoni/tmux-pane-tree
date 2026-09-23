"""Tests for tmux_pane_tree.tmux_tree."""

import subprocess
import types

import pytest

import tmux_pane_tree.tmux_tree as tt
from tmux_pane_tree.tmux_tree import Pane, TmuxError, run_tmux


# --- run_tmux: no shell, error handling -----------------------------------

def test_run_tmux_uses_argv_not_shell(monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return types.SimpleNamespace(returncode=0, stdout="  out  \n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = run_tmux(["list-sessions", "-F", "x"])

    assert out == "out"  # stripped
    assert captured["argv"] == ["tmux", "list-sessions", "-F", "x"]
    assert captured["kwargs"].get("shell") in (None, False)  # never shell=True


def test_run_tmux_missing_binary_raises(monkeypatch):
    def fake_run(argv, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(TmuxError, match="not found"):
        run_tmux(["list-sessions"])


def test_run_tmux_nonzero_exit_raises_with_stderr(monkeypatch):
    def fake_run(argv, **kwargs):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="no server running\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(TmuxError, match="no server running"):
        run_tmux(["list-sessions"])


# --- injection safety ------------------------------------------------------

def _make_pane(pane_id="%1"):
    window = types.SimpleNamespace(id="@0")
    return Pane(pane_id, window, "0", True, "80", "24", "0", "0", "123")


def test_send_keys_payload_stays_literal_argv(fake_tmux):
    pane = _make_pane()
    pane.send_keys("; rm -rf ~")
    # The dangerous tokens are separate argv items, not a shell string.
    assert fake_tmux.calls[-1] == ["send-keys", "-t", "%1", ";", "rm", "-rf", "~"]


def test_run_command_sends_literal_then_enter(fake_tmux):
    pane = _make_pane()
    pane.run_command("cd /repo && . utils/setup")
    assert fake_tmux.calls == [
        ["send-keys", "-t", "%1", "-l", "cd /repo && . utils/setup"],
        ["send-keys", "-t", "%1", "Enter"],
    ]


def test_run_command_empty_only_sends_enter(fake_tmux):
    pane = _make_pane()
    pane.run_command("")
    assert fake_tmux.calls == [["send-keys", "-t", "%1", "Enter"]]


# --- parsing: pipes in names, malformed lines ------------------------------

def _script_tmux(fake):
    def sessions(args):
        return "$1|1|my|weird|session\nBADLINE"

    def windows(args):
        return "@1|0|1|edit|split\n@2|1|0|plain"

    def panes(args):
        return "%1|0|1|80|24|0|0|100\nSHORT|LINE"

    fake.on("list-sessions", sessions)
    fake.on("list-windows", windows)
    fake.on("list-panes", panes)
    fake.on("display-message", lambda a: "")
    return fake


def test_pipe_in_names_and_malformed_lines(fake_tmux):
    _script_tmux(fake_tmux)
    tree = tt.TmuxTree()

    assert len(tree.sessions) == 1  # malformed session skipped
    s = tree.sessions[0]
    assert s.name == "my|weird|session"
    assert s.attached is True

    w0, w1 = s.windows
    assert w0.name == "edit|split" and w0.active is True
    assert w1.name == "plain" and w1.active is False

    assert len(w0.panes) == 1 and w0.panes[0].id == "%1"  # SHORT|LINE skipped


# --- geometry: get_direction_to -------------------------------------------

def _geo_pane(x, y, w=80, h=24):
    window = types.SimpleNamespace(id="@0")
    return Pane("%x", window, "0", True, str(w), str(h), str(x), str(y), "1")


def test_direction_right_and_left():
    left = _geo_pane(0, 0)
    right = _geo_pane(80, 0)  # starts where left ends
    assert left.get_direction_to(right) == "right"
    assert right.get_direction_to(left) == "left"


def test_direction_up_and_down():
    top = _geo_pane(0, 0)
    bottom = _geo_pane(0, 24)
    assert top.get_direction_to(bottom) == "down"
    assert bottom.get_direction_to(top) == "up"


def test_direction_none_when_not_adjacent():
    a = _geo_pane(0, 0)
    far = _geo_pane(500, 500)
    assert a.get_direction_to(far) is None
