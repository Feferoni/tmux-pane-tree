"""Tests for tmux_pane_tree.layout."""

import pytest

import tmux_pane_tree.layout as layout
from tmux_pane_tree.layout import (create_from_layout, format_layout,
                                   load_layout_file)
from tmux_pane_tree.tmux_tree import TmuxError


# --- validation ------------------------------------------------------------

def test_root_must_be_object():
    with pytest.raises(ValueError, match="root must be a JSON object"):
        format_layout([])


def test_window_requires_left():
    spec = {"s": {"w": {"right": ["a"]}}}
    with pytest.raises(ValueError, match="must have a 'left' side"):
        format_layout(spec)


def test_left_must_be_non_empty():
    spec = {"s": {"w": {"left": []}}}
    with pytest.raises(ValueError, match="at least one pane"):
        format_layout(spec)


def test_unknown_window_key_rejected():
    spec = {"s": {"w": {"left": ["a"], "middle": ["b"]}}}
    with pytest.raises(ValueError, match="unknown keys"):
        format_layout(spec)


def test_unknown_pane_key_rejected():
    spec = {"s": {"w": {"left": [{"cwd": "/x", "bogus": 1}]}}}
    with pytest.raises(ValueError, match="unknown keys"):
        format_layout(spec)


def test_cmds_must_be_list_of_strings():
    spec = {"s": {"w": {"left": [{"cmds": "not a list"}]}}}
    with pytest.raises(ValueError, match="'cmds' must be a list"):
        format_layout(spec)


def test_only_one_active_window():
    spec = {
        "s": {
            "w1": {"active": True, "left": ["a"]},
            "w2": {"active": True, "left": ["b"]},
        }
    }
    with pytest.raises(ValueError, match="only one window may be 'active'"):
        format_layout(spec)


def test_active_must_be_bool():
    spec = {"s": {"w": {"active": "yes", "left": ["a"]}}}
    with pytest.raises(ValueError, match="'active' must be a boolean"):
        format_layout(spec)


# --- formatting ------------------------------------------------------------

def test_format_layout_shows_structure_and_active():
    spec = {
        "dev": {
            "editor": {
                "active": True,
                "left": [{"cwd": "~/p", "cmds": ["nvim ."]}],
                "right": [{"cmds": ["npm run dev"]}, "tail -f log"],
            }
        }
    }
    out = format_layout(spec)
    assert "Session: dev" in out
    assert "Window 0: editor *active*" in out
    assert "Left:" in out and "Right:" in out
    assert "$ nvim ." in out
    assert "$ npm run dev" in out
    assert "$ tail -f log" in out  # bare-string pane shorthand


# --- file loading ----------------------------------------------------------

def test_load_layout_file_roundtrip(tmp_path):
    p = tmp_path / "layout.json"
    p.write_text('{"s": {"w": {"left": ["echo hi"]}}}')
    spec = load_layout_file(str(p))
    assert spec["s"]["w"]["left"] == ["echo hi"]


def test_load_layout_file_bad_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_layout_file(str(p))


# --- builder command sequence ---------------------------------------------

def _script_builder(fake):
    counter = {"s": 0, "w": 0, "p": 0}

    def has_session(args):
        raise TmuxError("no session")  # nothing exists

    def new_session(args):
        counter["s"] += 1
        return f"${counter['s']}"

    def new_window(args):
        counter["w"] += 1
        return f"%w{counter['w']}"  # returns the new window's pane id

    def list_panes(args):
        return "%100"

    def split_window(args):
        counter["p"] += 1
        return f"%s{counter['p']}"

    def display_message(args):
        return "@active"

    (fake.on("has-session", has_session)
         .on("new-session", new_session)
         .on("new-window", new_window)
         .on("list-panes", list_panes)
         .on("split-window", split_window)
         .on("display-message", display_message))
    return fake


def test_left_only_single_pane_no_split(fake_tmux):
    _script_builder(fake_tmux)
    create_from_layout({"s": {"w": {"left": ["echo hi"]}}})
    assert fake_tmux.with_verb("split-window") == []  # one pane -> no split
    # command sent literally then Enter
    assert ["send-keys", "-t", "%100", "-l", "echo hi"] in fake_tmux.calls
    assert ["send-keys", "-t", "%100", "Enter"] in fake_tmux.calls


def test_left_right_uses_horizontal_divider(fake_tmux):
    _script_builder(fake_tmux)
    create_from_layout({"s": {"w": {"left": ["a"], "right": ["b"]}}})
    splits = fake_tmux.with_verb("split-window")
    assert len(splits) == 1
    assert "-h" in splits[0]  # vertical divider between left|right


def test_stacked_right_uses_vertical_splits(fake_tmux):
    _script_builder(fake_tmux)
    create_from_layout({"s": {"w": {"left": ["a"], "right": ["b", "c"]}}})
    splits = fake_tmux.with_verb("split-window")
    # one -h for the right column, one -v to stack the second right pane
    assert sum("-h" in s for s in splits) == 1
    assert sum("-v" in s for s in splits) == 1


def test_cwd_passed_via_dash_c(fake_tmux):
    _script_builder(fake_tmux)
    create_from_layout({"s": {"w": {"left": [{"cwd": "/tmp/x", "cmds": []}]}}})
    new_session = fake_tmux.with_verb("new-session")[0]
    assert "-c" in new_session and "/tmp/x" in new_session


def test_existing_session_without_replace_raises(fake_tmux):
    fake_tmux.on("has-session", lambda a: "")  # exists (no error)
    with pytest.raises(TmuxError, match="already exists"):
        create_from_layout({"s": {"w": {"left": ["a"]}}})


def test_replace_kills_existing(fake_tmux):
    _script_builder(fake_tmux)
    fake_tmux.on("has-session", lambda a: "")  # exists
    create_from_layout({"s": {"w": {"left": ["a"]}}}, replace=True)
    assert fake_tmux.with_verb("kill-session")


def test_active_selects_window(fake_tmux):
    _script_builder(fake_tmux)
    create_from_layout({"s": {"w": {"active": True, "left": ["a"]}}})
    assert fake_tmux.with_verb("select-window")


def test_no_active_no_select(fake_tmux):
    _script_builder(fake_tmux)
    create_from_layout({"s": {"w": {"left": ["a"]}}})
    assert fake_tmux.with_verb("select-window") == []
