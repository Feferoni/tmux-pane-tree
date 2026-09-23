import shlex
import subprocess
from typing import List, Optional, Dict


class TmuxError(RuntimeError):
    """Raised when a tmux command fails or tmux is not available."""


def run_tmux(args: List[str]) -> str:
    """Execute a tmux command and return its stdout.

    ``args`` is the argument vector *after* ``tmux`` (e.g. ``["list-panes", "-t", pane_id]``).
    Commands run without a shell, so arguments are passed literally and are not
    subject to shell interpolation or injection.

    Raises:
        TmuxError: if the ``tmux`` binary is missing or the command exits non-zero.
    """
    try:
        result = subprocess.run(["tmux", *args], capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise TmuxError("tmux executable not found on PATH") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise TmuxError(f"tmux {' '.join(args)}: {detail}")
    return result.stdout.strip()


class Pane:

    def __init__(self, pane_id: str, window: 'Window', index: str, active: bool, width: str,
                 height: str, x: str, y: str, pid: str):
        self.id = pane_id
        self.window = window
        self.index = index
        self.active = active
        self.width = int(width)
        self.height = int(height)
        self.x = int(x)
        self.y = int(y)
        self.pid = int(pid)

    def get_process(self) -> str:
        """Get the process running in this pane."""
        return run_tmux(
            ["display-message", "-p", "-t", self.id, "#{pane_current_command}"])

    def has_subprocess(self, process_name: str) -> bool:
        """Check if a specific subprocess is running in this pane."""
        return process_name.lower() in self.get_process().lower()

    def send_keys(self, keys: str) -> None:
        """Send keys to this pane.

        ``keys`` is split with shell-style tokenization so callers can mix literal
        text and tmux key names (e.g. ``'"echo hi" Enter'``). Tokens are passed to
        tmux as separate argv items without invoking a shell.
        """
        run_tmux(["send-keys", "-t", self.id, *shlex.split(keys)])

    def run_command(self, command: str) -> None:
        """Type a shell command into this pane and press Enter.

        The command is sent literally (``send-keys -l``) so shell operators,
        spaces and quotes are preserved exactly, then Enter is sent separately
        to submit it. No shell is invoked by this library; the command runs in
        whatever shell the pane already hosts.
        """
        if command:
            run_tmux(["send-keys", "-t", self.id, "-l", command])
        run_tmux(["send-keys", "-t", self.id, "Enter"])

    def switch_to(self) -> None:
        """Switch to this pane."""
        run_tmux(["select-pane", "-t", self.id])

    def is_zoomed(self) -> bool:
        """Check if this pane's window is currently zoomed."""
        return run_tmux(
            ["display-message", "-p", "-t", self.window.id,
             "#{window_zoomed_flag}"]) == '1'

    def get_neighbors(self) -> Dict[str, str]:
        """Get neighboring panes (left, right, up, down). Falls back to pane IDs as keys."""
        neighbors = {}
        for pane in self.window.panes:
            if pane.id == self.id:
                continue

            direction = self.get_direction_to(pane)
            if direction:
                neighbors[direction] = pane.id
            else:
                neighbors[pane.id] = pane.id

        return neighbors

    def get_direction_to(self, pane: 'Pane') -> Optional[str]:
        """Determine adjacency direction of pane relative to self using geometry."""
        if (abs((pane.x + pane.width) - self.x) <= 2
                and not (pane.y + pane.height <= self.y or pane.y >= self.y + self.height)):
            return 'left'
        if (abs((self.x + self.width) - pane.x) <= 2
                and not (pane.y + pane.height <= self.y or pane.y >= self.y + self.height)):
            return 'right'
        if (abs((pane.y + pane.height) - self.y) <= 2
                and not (pane.x + pane.width <= self.x or pane.x >= self.x + self.width)):
            return 'up'
        if (abs((self.y + self.height) - pane.y) <= 2
                and not (pane.x + pane.width <= self.x or pane.x >= self.x + self.width)):
            return 'down'
        return None


class Window:

    def __init__(self, window_id: str, session: 'Session', index: str, name: str, active: bool):
        self.id = window_id
        self.session = session
        self.index = index
        self.name = name
        self.active = active
        self.panes: list[Pane] = []

    def load_panes(self) -> None:
        """Load all panes in this window."""
        cmd = ["list-panes", "-t", self.id, "-F",
               "#{pane_id}|#{pane_index}|#{pane_active}|#{pane_width}|"
               "#{pane_height}|#{pane_left}|#{pane_top}|#{pane_pid}"]
        output = run_tmux(cmd)
        for line in output.split('\n'):
            if not line:
                continue
            parts = line.split('|')
            if len(parts) != 8:
                # Skip malformed lines rather than raising IndexError. Pane
                # fields are IDs/ints/flags and never contain '|'.
                continue
            pane = Pane(parts[0], self, parts[1], parts[2] == '1', parts[3], parts[4], parts[5],
                        parts[6], parts[7])
            self.panes.append(pane)


class Session:

    def __init__(self, session_id: str, name: str, attached: bool):
        self.id = session_id
        self.name = name
        self.attached = attached
        self.windows: list[Window] = []

    def load_windows(self) -> None:
        """Load all windows in this session."""
        # window_name is placed last so a '|' in the name cannot corrupt other
        # fields; split with maxsplit lets the name absorb any '|' it contains.
        cmd = ["list-windows", "-t", self.id, "-F",
               "#{window_id}|#{window_index}|#{window_active}|#{window_name}"]
        output = run_tmux(cmd)
        for line in output.split('\n'):
            if not line:
                continue
            parts = line.split('|', 3)
            if len(parts) != 4:
                continue
            window = Window(parts[0], self, parts[1], parts[3], parts[2] == '1')
            window.load_panes()
            self.windows.append(window)


class TmuxTree:

    def __init__(self):
        self.sessions: list[Session] = []
        self.load()

    def load(self) -> None:
        """Load all tmux sessions, windows, and panes."""
        # session_name placed last so a '|' in the name cannot corrupt other fields.
        cmd = ["list-sessions", "-F",
               "#{session_id}|#{session_attached}|#{session_name}"]
        output = run_tmux(cmd)
        for line in output.split('\n'):
            if not line:
                continue
            parts = line.split('|', 2)
            if len(parts) != 3:
                continue
            session = Session(parts[0], parts[2], parts[1] != '0')
            session.load_windows()
            self.sessions.append(session)

    def get_current_pane(self) -> Optional[Pane]:
        """Get the currently active pane."""
        for session in self.sessions:
            if not session.attached:
                continue
            for window in session.windows:
                if not window.active:
                    continue
                for pane in window.panes:
                    if pane.active:
                        return pane
        return None

    def find_pane(self, pane_id: str) -> Optional[Pane]:
        """Find a pane by its ID."""
        for session in self.sessions:
            for window in session.windows:
                for pane in window.panes:
                    if pane.id == pane_id:
                        return pane
        return None

    def print_tree(self) -> None:
        """Print tree representation of sessions -> windows -> panes."""
        for session in self.sessions:
            marker = "●" if session.attached else "○"
            print(f"{marker} Session: {session.name} ({session.id})")
            for window in session.windows:
                marker = "●" if window.active else "○"
                print(f"  {marker} Window {window.index}: {window.name} ({window.id})")
                for pane in window.panes:
                    marker = "●" if pane.active else "○"
                    process = pane.get_process()
                    print(
                        f"    {marker} Pane {pane.index} ({pane.id}) - {process} [{pane.width}x{pane.height} @ {pane.x},{pane.y}]"
                    )
