# tmux-pane-tree

Python library for creating tree representations of tmux sessions, windows, and panes with neighbor detection and process management.

## Features

- Tree representation of tmux sessions → windows → panes
- Find currently active pane
- Get neighbor panes (left, right, up, down)
- Determine directional relationship between panes
- Check if subprocess is running in a pane
- Send commands to panes
- Create sessions declaratively from a JSON layout file

## Usage

```python
from tmux_tree import TmuxTree

# Load all tmux data
tree = TmuxTree()

# Print tree
tree.print_tree()

# Get current pane
current = tree.get_current_pane()

# Get neighbors
neighbors = current.get_neighbors()
# Returns: {'left': '%1', 'right': '%2', ...}

# Check for process
if current.has_subprocess('nvim'):
    print("Neovim is running!")

# Get direction to another pane
other_pane = tree.find_pane('%2')
direction = current.get_direction_to(other_pane)

# Send commands
other_pane.send_keys('echo hello')
```

## CLI Usage
```bash

# Show tree
./tmux-pane-tree tree

# Show current pane info
./tmux-pane-tree current

# List neighbors
./tmux-pane-tree neighbors

# Find process in neighbors
./tmux-pane-tree find nvim

# Send keys to a pane
./tmux-pane-tree send %23 "echo hello"

# Get direction between panes
./tmux-pane-tree direction %39 %23

# Create sessions from a layout file (defaults to ~/.tmux_pane_tree_layout.json)
./tmux-pane-tree layout
./tmux-pane-tree layout my-layout.json

# Print a layout without creating anything
./tmux-pane-tree layout --print

# Replace sessions that already exist
./tmux-pane-tree layout --replace
```

## Layout files

`layout` builds tmux sessions from a JSON file. Creating a layout also prints
its tree; `--print` prints without creating.

### Structure

```
{
  "<session name>": {
    "<window name>": {
      "active": <bool, optional>,
      "left":  [ <pane>, ... ],
      "right": [ <pane>, ... ]
    }
  }
}
```

- **Sides.** A window has a `left` side and an optional `right` side, separated
  by a vertical divider. Each side is a list of panes stacked top-to-bottom
  (a horizontal divider between them). `left` only → one full-width column;
  `left` + `right` with one pane each → two panes side by side.
- **Panes.** A pane is either a command string (shorthand) or an object:
  - `cwd` (optional): working directory; passed to tmux with `-c` so the pane's
    shell starts there. `~` is expanded.
  - `cmds` (optional): list of command lines typed into the pane in order, each
    followed by Enter. Use `[]` for just a shell.
- **Active window.** At most one window in the whole file may set
  `"active": true`. After the layout is built, the tmux client moves to that
  window (and, when run inside tmux, switches to its session).

### Example

```json
{
  "dev": {
    "editor": {
      "active": true,
      "left":  [ { "cwd": "~/projects/myapp", "cmds": ["nvim ."] } ],
      "right": [
        { "cwd": "~/projects/myapp", "cmds": ["npm run dev"] },
        { "cwd": "~/projects/myapp", "cmds": ["tail -f logs/app.log"] }
      ]
    },
    "shell": {
      "left": [ { "cwd": "~/projects/myapp" } ]
    }
  }
}
```

This creates a `dev` session with two windows. `editor` has `nvim` on the left
and two stacked panes (`npm run dev`, `tail -f`) on the right, and is focused on
creation. `shell` is a single pane starting in the project directory.

Sessions are created detached unless an `active` window moves you there. Attach
with `tmux attach -t <session>`.

## Testing

Tests use `pytest` and run without a real tmux server — `run_tmux` is patched by
a fixture that records the tmux commands the library builds and returns scripted
output. They cover command-execution safety (no shell injection), tmux error
handling, output parsing, pane geometry, the neovim expr escaping, and the
layout builder.

Requires `pytest` (>= 7.0, for the `pythonpath` ini option).

```bash
python3 -m pytest -q
```

`pytest.ini` sets `pythonpath = .` so the `tmux_pane_tree` and `rpc` packages
import when running from the repository root.
