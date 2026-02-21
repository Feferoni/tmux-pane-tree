import subprocess
import json
from typing import Optional


def run_tmux(cmd: str) -> str:
    """Execute tmux command and return output."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, executable='/bin/bash')
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
        cmd = f"tmux display-message -p -t '{self.id}' '#{{pane_current_command}}'"
        return run_tmux(cmd)

    def has_subprocess(self, process_name: str) -> bool:
        """Check if a specific subprocess is running in this pane."""
        return process_name.lower() in self.get_process().lower()

    def send_keys(self, keys: str) -> None:
        """Send keys to this pane. Separate literal text and special keys with spaces."""
        # Build the tmux command - keys should already be properly formatted by caller
        run_tmux(f"tmux send-keys -t '{self.id}' {keys}")

    def switch_to(self) -> None:
        """Switch to this pane."""
        run_tmux(f"tmux select-pane -t '{self.id}'")

    def get_neighbors(self) -> dict[str, str]:
        """Get neighboring panes (left, right, up, down)."""
        neighbors = {}
        # Get all panes in the same window
        for pane in self.window.panes:
            if pane.id == self.id:
                continue
            # Check if pane is to the left (adjacent horizontally, overlapping vertically)
            if (abs((pane.x + pane.width) - self.x) <= 2
                    and not (pane.y + pane.height <= self.y or pane.y >= self.y + self.height)):
                neighbors['left'] = pane.id
            # Check if pane is to the right (adjacent horizontally, overlapping vertically)
            elif (abs((self.x + self.width) - pane.x) <= 2
                  and not (pane.y + pane.height <= self.y or pane.y >= self.y + self.height)):
                neighbors['right'] = pane.id
            # Check if pane is above (adjacent vertically, overlapping horizontally)
            elif (abs((pane.y + pane.height) - self.y) <= 2
                  and not (pane.x + pane.width <= self.x or pane.x >= self.x + self.width)):
                neighbors['up'] = pane.id
            # Check if pane is below (adjacent vertically, overlapping horizontally)
            elif (abs((self.y + self.height) - pane.y) <= 2
                  and not (pane.x + pane.width <= self.x or pane.x >= self.x + self.width)):
                neighbors['down'] = pane.id
        return neighbors

    def get_direction_to(self, other_pane: 'Pane') -> Optional[str]:
        """Determine direction of other_pane relative to this pane."""
        if other_pane.x < self.x:
            return 'left'
        elif other_pane.x > self.x:
            return 'right'
        elif other_pane.y < self.y:
            return 'up'
        elif other_pane.y > self.y:
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
        cmd = f"tmux list-panes -t '{self.id}' -F '#{{pane_id}}|#{{pane_index}}|#{{pane_active}}|#{{pane_width}}|#{{pane_height}}|#{{pane_left}}|#{{pane_top}}|#{{pane_pid}}'"
        output = run_tmux(cmd)
        for line in output.split('\n'):
            if line:
                parts = line.split('|')
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
        cmd = f"tmux list-windows -t '{self.id}' -F '#{{window_id}}|#{{window_index}}|#{{window_name}}|#{{window_active}}'"
        output = run_tmux(cmd)
        for line in output.split('\n'):
            if line:
                parts = line.split('|')
                window = Window(parts[0], self, parts[1], parts[2], parts[3] == '1')
                window.load_panes()
                self.windows.append(window)


class TmuxTree:

    def __init__(self):
        self.sessions: list[Session] = []
        self.load()

    def load(self) -> None:
        """Load all tmux sessions, windows, and panes."""
        cmd = "tmux list-sessions -F '#{session_id}|#{session_name}|#{session_attached}'"
        output = run_tmux(cmd)
        for line in output.split('\n'):
            if line:
                parts = line.split('|')
                session = Session(parts[0], parts[1], parts[2] != '0')
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
