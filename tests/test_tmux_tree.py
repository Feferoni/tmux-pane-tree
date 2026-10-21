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


# --- get_subprocesses: process-tree walk ----------------------------------

def _patch_ps(monkeypatch, rows):
    """Patch subprocess.run used by get_subprocesses to return (pid, ppid, args) rows."""
    stdout = "".join(f"{pid} {ppid} {args}\n" for pid, ppid, args in rows)

    def fake_run(argv, **kwargs):
        assert argv[0] == "ps"
        return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(tt.subprocess, "run", fake_run)


def test_subprocesses_returns_descendants_breadth_first(monkeypatch):
    pane = _make_pane()  # pane.pid == 123
    # 123 -> 200, 201 ; 200 -> 300 ; unrelated tree 999 -> 998
    _patch_ps(monkeypatch, [(200, 123, "nvim ."), (201, 123, "clangd --log=info"),
                            (300, 200, "node server.js"), (999, 1, "init"),
                            (998, 999, "other")])
    assert pane.get_subprocesses() == [(200, "nvim ."), (201, "clangd --log=info"),
                                       (300, "node server.js")]


def test_subprocesses_empty_when_no_children(monkeypatch):
    pane = _make_pane()  # pane.pid == 123
    _patch_ps(monkeypatch, [(1, 0, "init"), (999, 1, "x")])
    assert pane.get_subprocesses() == []


def test_subprocesses_empty_when_ps_missing(monkeypatch):
    pane = _make_pane()

    def fake_run(argv, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(tt.subprocess, "run", fake_run)
    assert pane.get_subprocesses() == []


def test_subprocesses_skips_malformed_lines(monkeypatch):
    pane = _make_pane()  # pane.pid == 123

    def fake_run(argv, **kwargs):
        return types.SimpleNamespace(
            returncode=0, stdout="200 123 vim\ngarbage\n  \nabc def ghi\n201 123\n", stderr="")

    monkeypatch.setattr(tt.subprocess, "run", fake_run)
    assert pane.get_subprocesses() == [(200, "vim"), (201, "")]


# --- print_tree: --pids table ----------------------------------------------

def _tree_with_two_panes(fake):
    fake.on("list-sessions", lambda a: "$1|1|trrc")
    fake.on("list-windows", lambda a: "@2|1|1|trrc")
    fake.on("list-panes", lambda a: "%3|1|1|215|74|0|0|100\n%4|2|0|213|37|216|0|500")
    fake.on("display-message", lambda a: "nvim" if a[3] == "%3" else "bash")
    return tt.TmuxTree()


def test_print_tree_without_pids_prints_no_table(fake_tmux, monkeypatch, capsys):
    tree = _tree_with_two_panes(fake_tmux)

    def boom(*a, **k):
        raise AssertionError("ps must not run without show_pids")

    monkeypatch.setattr(tt.subprocess, "run", boom)
    tree.print_tree()
    assert " | " not in capsys.readouterr().out


def test_print_tree_with_pids_prints_table_only_for_busy_panes(fake_tmux, monkeypatch, capsys):
    tree = _tree_with_two_panes(fake_tmux)
    _patch_ps(monkeypatch, [(123123, 100, "nvim ."), (77, 100, "clangd")])
    tree.print_tree(show_pids=True)

    assert capsys.readouterr().out.splitlines() == [
        "● Session: trrc ($1)",
        "  ● Window 1: trrc (@2)",
        "    ● Pane 1 (%3) - nvim [215x74 @ 0,0]",
        "      123123 | nvim .",
        "      77     | clangd",
        "    ○ Pane 2 (%4) - bash [213x37 @ 216,0]",
    ]


# --- print_tree: --current -------------------------------------------------

def _two_session_tree(fake):
    fake.on("list-sessions", lambda a: "$1|1|alpha\n$2|1|beta")
    fake.on("list-windows", lambda a: "@1|0|1|w" if a[2] == "$1" else "@2|0|1|w")
    fake.on("list-panes", lambda a: "%1|0|1|80|24|0|0|1" if a[2] == "@1"
            else "%2|0|1|80|24|0|0|2")
    fake.on("display-message", lambda a: "bash")
    return tt.TmuxTree()


def test_print_tree_current_uses_tmux_pane_session(fake_tmux, monkeypatch, capsys):
    tree = _two_session_tree(fake_tmux)
    monkeypatch.setenv("TMUX_PANE", "%2")
    tree.print_tree(current_only=True)
    out = capsys.readouterr().out
    assert "beta" in out and "alpha" not in out


def test_print_tree_current_falls_back_to_attached(fake_tmux, monkeypatch, capsys):
    fake_tmux.on("list-sessions", lambda a: "$1|0|alpha\n$2|1|beta")
    fake_tmux.on("list-windows", lambda a: "@1|0|1|w")
    fake_tmux.on("list-panes", lambda a: "%1|0|1|80|24|0|0|1")
    fake_tmux.on("display-message", lambda a: "bash")
    tree = tt.TmuxTree()
    monkeypatch.delenv("TMUX_PANE", raising=False)
    tree.print_tree(current_only=True)
    out = capsys.readouterr().out
    assert "beta" in out and "alpha" not in out


def test_print_tree_current_raises_without_session(fake_tmux, monkeypatch):
    fake_tmux.on("list-sessions", lambda a: "$1|0|alpha")
    fake_tmux.on("list-windows", lambda a: "@1|0|1|w")
    fake_tmux.on("list-panes", lambda a: "%1|0|1|80|24|0|0|1")
    tree = tt.TmuxTree()
    monkeypatch.delenv("TMUX_PANE", raising=False)
    with pytest.raises(TmuxError, match="no current session"):
        tree.print_tree(current_only=True)


def test_print_tree_all_sessions_by_default(fake_tmux, monkeypatch, capsys):
    tree = _two_session_tree(fake_tmux)
    monkeypatch.setenv("TMUX_PANE", "%2")
    tree.print_tree()
    out = capsys.readouterr().out
    assert "alpha" in out and "beta" in out
