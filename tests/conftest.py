"""Shared fixtures for the tmux-pane-tree test suite.

All tests run without a real tmux server. ``run_tmux`` is patched so we can both
assert on the exact argv the library builds and simulate tmux responses.
"""

import subprocess
import types

import pytest

import tmux_pane_tree.tmux_tree as tmux_tree
import tmux_pane_tree.layout as layout


class FakeTmux:
    """Records tmux calls and returns scripted output.

    ``handler`` maps the first tmux argument (e.g. ``"new-session"``) to a
    callable ``(args) -> str``. Unhandled commands return an empty string.
    """

    def __init__(self):
        self.calls = []
        self.handlers = {}

    def on(self, verb, func):
        self.handlers[verb] = func
        return self

    def __call__(self, args):
        self.calls.append(list(args))
        handler = self.handlers.get(args[0])
        return handler(args) if handler else ""

    # Convenience queries for assertions.
    def verbs(self):
        return [c[0] for c in self.calls]

    def with_verb(self, verb):
        return [c for c in self.calls if c[0] == verb]


@pytest.fixture
def fake_tmux(monkeypatch):
    """Patch run_tmux in both modules with a FakeTmux and return it."""
    fake = FakeTmux()
    monkeypatch.setattr(tmux_tree, "run_tmux", fake)
    monkeypatch.setattr(layout, "run_tmux", fake)
    return fake
