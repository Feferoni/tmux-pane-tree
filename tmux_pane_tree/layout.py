"""Create tmux sessions from a declarative JSON layout.

A window is split into a ``left`` and an optional ``right`` side. Each side is a
list of panes; one tmux pane is created per list item and the panes are stacked
top-to-bottom within that side (a horizontal divider between them). The left and
right sides are separated by a vertical divider.

* ``left`` only              -> a single column filling the window.
* ``left`` + ``right`` (one each) -> two panes side by side.
* a side with several items  -> those panes stacked within that side.

A pane is either:

* a **string** shorthand -> a single command to run, or
* an **object** ``{"cwd": <dir>, "cmds": [<command>, ...]}`` where

  * ``cwd`` (optional) is the pane's working directory, passed to tmux via
    ``-c`` so the pane's shell starts there (``~`` is expanded).
  * ``cmds`` (optional) is a list of command lines typed into the pane in
    order, each followed by Enter.

Example (left one pane, right two stacked)::

    {
      "dev": {
        "main": {
          "left":  [{"cwd": "~/projects/myapp", "cmds": ["nvim ."]}],
          "right": [
            {"cwd": "~/projects/myapp", "cmds": ["nvm use", "npm run dev"]},
            {"cwd": "~/projects/myapp", "cmds": ["tail -f logs/app.log"]}
          ]
        }
      }
    }

Top level maps session names to windows; each window maps a name to a
``{"left": [...], "right": [...]}`` object.
"""

import json
import os
from typing import Dict, List, Optional

from .tmux_tree import TmuxError, run_tmux


class Pane:
    """A normalized pane: an optional working directory and a list of commands."""

    __slots__ = ("cwd", "cmds")

    def __init__(self, cwd: Optional[str], cmds: List[str]):
        self.cwd = cwd
        self.cmds = cmds


# Raw JSON shapes.
LayoutSpec = Dict[str, Dict[str, Dict[str, list]]]


def _session_exists(name: str) -> bool:
    try:
        run_tmux(["has-session", "-t", f"={name}"])
        return True
    except TmuxError:
        return False


def _parse_pane(raw: object, where: str) -> Pane:
    """Validate and normalize a single pane entry."""
    if isinstance(raw, str):
        return Pane(cwd=None, cmds=[raw] if raw else [])
    if isinstance(raw, dict):
        unknown = set(raw) - {"cwd", "cmds"}
        if unknown:
            raise ValueError(f"{where} has unknown keys: {sorted(unknown)}")
        cwd = raw.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError(f"{where} 'cwd' must be a string")
        cmds = raw.get("cmds", [])
        if not isinstance(cmds, list):
            raise ValueError(f"{where} 'cmds' must be a list of strings")
        for i, cmd in enumerate(cmds):
            if not isinstance(cmd, str):
                raise ValueError(f"{where} 'cmds'[{i}] must be a string")
        expanded = os.path.expanduser(cwd) if cwd else None
        return Pane(cwd=expanded, cmds=list(cmds))
    raise ValueError(f"{where} must be a command string or an object with 'cwd'/'cmds'")


def _parse_side(raw: object, where: str) -> List[Pane]:
    if not isinstance(raw, list):
        raise ValueError(f"{where} must be a list of panes")
    return [_parse_pane(p, f"{where}[{i}]") for i, p in enumerate(raw)]


def _parse_windows(spec: object) -> Dict[str, Dict[str, Dict[str, object]]]:
    """Validate the whole spec and return a normalized structure.

    Returns ``{session: {window: {"left": [Pane], "right": [Pane], "active": bool}}}``.
    At most one window across the entire layout may set ``active: true``.
    """
    if not isinstance(spec, dict):
        raise ValueError("layout root must be a JSON object mapping session names to windows")
    result: Dict[str, Dict[str, Dict[str, object]]] = {}
    active_seen: Optional[str] = None
    for session_name, windows in spec.items():
        if not isinstance(windows, dict) or not windows:
            raise ValueError(f"session {session_name!r} must map to a non-empty object of windows")
        result[session_name] = {}
        for window_name, window in windows.items():
            where = f"{session_name!r}/{window_name!r}"
            if not isinstance(window, dict):
                raise ValueError(f"window {where} must be an object with 'left'/'right'")
            unknown = set(window) - {"left", "right", "active"}
            if unknown:
                raise ValueError(f"window {where} has unknown keys: {sorted(unknown)}")
            if "left" not in window:
                raise ValueError(f"window {where} must have a 'left' side")
            left = _parse_side(window["left"], f"window {where} 'left'")
            if not left:
                raise ValueError(f"window {where} 'left' must have at least one pane")
            right = _parse_side(window["right"], f"window {where} 'right'") \
                if "right" in window else []
            active = window.get("active", False)
            if not isinstance(active, bool):
                raise ValueError(f"window {where} 'active' must be a boolean")
            if active:
                if active_seen is not None:
                    raise ValueError(
                        f"only one window may be 'active'; both {active_seen} and "
                        f"{where} set it")
                active_seen = where
            result[session_name][window_name] = {
                "left": left, "right": right, "active": active}
    return result


def load_layout_file(path: str) -> LayoutSpec:
    """Read a layout JSON file, validating it in the process."""
    with open(path, "r", encoding="utf-8") as fh:
        try:
            spec = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    _parse_windows(spec)  # validate; raises on error
    return spec


def _select_sessions(parsed: dict, targets: Optional[List[str]]) -> List[str]:
    """Return the session names to act on, validating any explicit targets."""
    if targets is None:
        return list(parsed.keys())
    unknown = [name for name in targets if name not in parsed]
    if unknown:
        available = ", ".join(parsed) or "(none)"
        raise ValueError(
            f"unknown session(s): {', '.join(unknown)}; available: {available}")
    return list(targets)


def format_layout(spec: LayoutSpec, targets: Optional[List[str]] = None) -> str:
    """Render a layout spec as an indented tree, without touching tmux.

    If ``targets`` is given, only those sessions are rendered (in that order).
    """
    parsed = _parse_windows(spec)
    lines: List[str] = []
    for session_name in _select_sessions(parsed, targets):
        windows = parsed[session_name]
        lines.append(f"Session: {session_name}")
        for w_idx, (window_name, window) in enumerate(windows.items()):
            active = " *active*" if window["active"] else ""
            lines.append(f"  Window {w_idx}: {window_name}{active}")
            for side in ("left", "right"):
                panes = window[side]
                if not panes:
                    continue
                lines.append(f"    {side.capitalize()}:")
                for p_idx, pane in enumerate(panes):
                    cwd = f" [cwd {pane.cwd}]" if pane.cwd else ""
                    lines.append(f"      Pane {p_idx}{cwd}")
                    for cmd in pane.cmds:
                        lines.append(f"        $ {cmd}")
    return "\n".join(lines)


def print_layout(spec: LayoutSpec, targets: Optional[List[str]] = None) -> None:
    """Print the rendered layout tree to stdout (optionally filtered by targets)."""
    print(format_layout(spec, targets=targets))


def _run_cmds(pane_id: str, cmds: List[str]) -> None:
    for cmd in cmds:
        if cmd:
            run_tmux(["send-keys", "-t", pane_id, "-l", cmd])
        run_tmux(["send-keys", "-t", pane_id, "Enter"])


def _split(target_pane_id: str, direction: str, cwd: Optional[str]) -> str:
    """Split ``target_pane_id`` and return the new pane id."""
    args = ["split-window", direction, "-t", target_pane_id]
    if cwd:
        args += ["-c", cwd]
    args += ["-P", "-F", "#{pane_id}"]
    return run_tmux(args)


def _build_side(top_pane_id: str, panes: List[Pane]) -> None:
    """Fill a side. ``top_pane_id`` already exists and hosts ``panes[0]``.

    Each further pane is added below the previous one with a ``-v`` split
    (a horizontal divider), so panes stack top-to-bottom.
    """
    _run_cmds(top_pane_id, panes[0].cmds)
    current = top_pane_id
    for pane in panes[1:]:
        current = _split(current, "-v", pane.cwd)
        _run_cmds(current, pane.cmds)


def _build_window(first_pane_id: str, window: Dict[str, object]) -> None:
    """Realise a window's panes starting from its single default pane."""
    left = window["left"]  # type: ignore[assignment]
    right = window["right"]  # type: ignore[assignment]

    if right:
        # Vertical divider: create the right column, starting in its own cwd.
        right_top = _split(first_pane_id, "-h", right[0].cwd)
        _build_side(first_pane_id, left)
        _build_side(right_top, right)
    else:
        _build_side(first_pane_id, left)


def create_session(session_name: str, windows: Dict[str, Dict[str, object]],
                   replace: bool = False) -> "tuple[str, Optional[str]]":
    """Create a single tmux session with its windows.

    Returns ``(session_id, active_window_id)`` where ``active_window_id`` is the
    tmux window id marked ``active`` in this session, or ``None`` if none is.
    """
    if _session_exists(session_name):
        if not replace:
            raise TmuxError(
                f"session {session_name!r} already exists (use replace=True to overwrite)")
        run_tmux(["kill-session", "-t", f"={session_name}"])

    window_items = list(windows.items())
    first_window_name, first_window = window_items[0]
    active_window_id: Optional[str] = None

    # The session's first pane hosts left[0]; start it in that pane's cwd.
    first_cwd = first_window["left"][0].cwd  # type: ignore[index]
    new_session = ["new-session", "-d", "-s", session_name, "-n", first_window_name]
    if first_cwd:
        new_session += ["-c", first_cwd]
    new_session += ["-P", "-F", "#{session_id}"]
    session_id = run_tmux(new_session)

    first_pane = run_tmux(
        ["list-panes", "-t", session_id, "-F", "#{pane_id}"]).split("\n")[0]
    _build_window(first_pane, first_window)
    if first_window["active"]:
        active_window_id = run_tmux(
            ["display-message", "-p", "-t", first_pane, "#{window_id}"])

    for window_name, window in window_items[1:]:
        win_cwd = window["left"][0].cwd  # type: ignore[index]
        new_window = ["new-window", "-t", session_id, "-n", window_name]
        if win_cwd:
            new_window += ["-c", win_cwd]
        new_window += ["-P", "-F", "#{pane_id}"]
        new_pane = run_tmux(new_window)
        _build_window(new_pane, window)
        if window["active"]:
            active_window_id = run_tmux(
                ["display-message", "-p", "-t", new_pane, "#{window_id}"])

    return session_id, active_window_id


def _goto_window(window_id: str) -> None:
    """Make ``window_id`` current, moving the attached client there if inside tmux."""
    run_tmux(["select-window", "-t", window_id])
    # If we're running inside a tmux client, move that client to this session.
    if os.environ.get("TMUX"):
        run_tmux(["switch-client", "-t", window_id])


def create_from_layout(spec: LayoutSpec, replace: bool = False,
                       targets: Optional[List[str]] = None) -> List[str]:
    """Create sessions declared in ``spec``.

    Args:
        spec: the parsed/raw layout mapping.
        replace: kill and recreate a session if it already exists.
        targets: if given, only these session names are created (in the given
            order). Names not present in ``spec`` raise ``ValueError``. If
            ``None``, every session in ``spec`` is created in declaration order.

    If a window marked ``active`` belongs to one of the created sessions, the
    current tmux client is moved to it after building. Returns the created
    session ids.
    """
    parsed = _parse_windows(spec)

    selected = _select_sessions(parsed, targets)

    session_ids = []
    active_window_id: Optional[str] = None
    for session_name in selected:
        session_id, active = create_session(
            session_name, parsed[session_name], replace=replace)
        session_ids.append(session_id)
        if active is not None:
            active_window_id = active
    if active_window_id is not None:
        _goto_window(active_window_id)
    return session_ids
