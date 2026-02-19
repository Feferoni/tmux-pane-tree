#!/usr/bin/env bash
# Bash completion for tmux-pane-tree

_tmux_pane_tree() {
    local cur prev commands
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    
    commands="tree current neighbors find send direction nvim_exec"
    
    # Complete main commands
    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "${commands}" -- ${cur}) )
        return 0
    fi
    
    local cmd="${COMP_WORDS[1]}"
    
    case "${cmd}" in
        find)
            # Complete common process names
            if [[ ${COMP_CWORD} -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "nvim vim bash zsh python node" -- ${cur}) )
            fi
            ;;
        send|direction)
            # Complete with pane IDs
            if [[ ${prev} == "send" || ${prev} == "direction" || ${COMP_CWORD} -eq 2 ]]; then
                local panes=$(tmux list-panes -a -F '#{pane_id}' 2>/dev/null)
                COMPREPLY=( $(compgen -W "${panes}" -- ${cur}) )
            fi
            ;;
        nvim_exec)
            # Complete flags and pane IDs
            case "${prev}" in
                -p|--pane)
                    local panes=$(tmux list-panes -a -F '#{pane_id}' 2>/dev/null)
                    COMPREPLY=( $(compgen -W "${panes}" -- ${cur}) )
                    ;;
                *)
                    if [[ ${cur} == -* ]]; then
                        COMPREPLY=( $(compgen -W "-p --pane -s --switch" -- ${cur}) )
                    fi
                    ;;
            esac
            ;;
    esac
}

complete -F _tmux_pane_tree tmux-pane-tree
