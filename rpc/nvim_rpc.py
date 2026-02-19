import os
import glob
import subprocess


def find_nvim_socket(pane_pid):
    """Find nvim socket for a given pane PID."""
    # Find nvim listening sockets
    xdg_runtime = os.environ.get('XDG_RUNTIME_DIR')
    if xdg_runtime:
        sockets = glob.glob(f"{xdg_runtime}/nvim.*.0")
    else:
        user = os.environ.get('USER', '*')
        sockets = glob.glob(f"/tmp/nvim.{user}/nvim.*.0")
    
    # Get nvim process PID from pane
    cpid_cmd = f"pgrep -P {pane_pid} nvim"
    cpid_result = subprocess.run(cpid_cmd, shell=True, capture_output=True, text=True)
    if not cpid_result.stdout.strip():
        return None
    
    cpid = cpid_result.stdout.strip().split('\n')[0]
    
    # Get parent nvim RPC process
    ppid_cmd = f"pgrep -P {cpid} nvim"
    ppid_result = subprocess.run(ppid_cmd, shell=True, capture_output=True, text=True)
    ppid = ppid_result.stdout.strip()
    
    if not ppid:
        return None
    
    # Find matching socket
    for sock in sockets:
        if f"nvim.{ppid}." in sock:
            return sock
    
    return None


def nvim_exec(socket, cmd):
    """Execute command in neovim via socket."""
    try:
        result = subprocess.run(
            ['nvim', '--server', socket, '--remote-expr', f'execute("{cmd}")'],
            capture_output=True, timeout=2, text=True
        )
        return result.returncode == 0
    except:
        return False
