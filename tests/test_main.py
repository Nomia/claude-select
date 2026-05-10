from __future__ import annotations

import runpy


def test_module_entrypoint_invokes_main(monkeypatch):
    called: list[bool] = []

    def fake_main() -> int:
        called.append(True)
        return 0

    monkeypatch.setattr("claude_select.cli.main", fake_main)

    try:
        runpy.run_module("claude_select", run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0

    assert called == [True]
