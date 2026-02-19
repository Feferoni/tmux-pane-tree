# tmux-pane-tree

Python library for creating tree representations of tmux sessions, windows, and panes with neighbor detection and process management.

## Features

- Tree representation of tmux sessions → windows → panes
- Find currently active pane
- Get neighbor panes (left, right, up, down)
- Determine directional relationship between panes
- Check if subprocess is running in a pane
- Send commands to panes

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

## Example: Find neovim in neighbors

```python
from tmux_tree import TmuxTree, find_neovim_in_neighbors

tree = TmuxTree()
current = tree.get_current_pane()

nvim_pane, direction = find_neovim_in_neighbors(current)
if nvim_pane:
    print(f"Found neovim {direction}")
    nvim_pane.send_keys("Escape")
    nvim_pane.send_keys(":echo 'Hello!' Enter")
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
```
