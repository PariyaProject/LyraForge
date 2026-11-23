"""Tests for configurable global hotkeys (parsing, platform gating, API surface)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lyraforge.api import SESSION_TOKEN_HEADER, create_app
from lyraforge.errors import ErrorCode, LyraError
from lyraforge.hotkeys import MOD_ALT, MOD_CONTROL, HotkeyRegistry, parse_hotkey


def test_parse_hotkey_normalizes_and_requires_a_modifier() -> None:
    binding = parse_hotkey("ctrl + alt + f9")
    assert binding.modifiers == (MOD_CONTROL | MOD_ALT)
    assert binding.vk == 0x78
    assert binding.display == "Ctrl+Alt+F9"

    with pytest.raises(LyraError) as exc:
        parse_hotkey("F9")
    assert exc.value.code == ErrorCode.INVALID_ARGUMENT

    with pytest.raises(LyraError):
        parse_hotkey("Ctrl+Alt+NotAKey")
    with pytest.raises(LyraError):
        parse_hotkey("Ctrl+A+B")


def test_registry_reports_unsupported_platform_instead_of_failing_silently(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    registry = HotkeyRegistry({"start": lambda: None})
    errors = registry.apply({"start": "Ctrl+Alt+F9"})
    assert "_platform" in errors
    assert registry.bindings == {}


def test_hotkeys_api_lists_actions_and_accepts_empty_bindings(tmp_path: Path) -> None:
    token = "hotkey-token"
    client = TestClient(create_app(data_dir=tmp_path / "hotkeys", session_token=token))
    headers = {SESSION_TOKEN_HEADER: token}

    listing = client.get("/v1/hotkeys", headers=headers)
    assert listing.status_code == 200
    body = listing.json()
    assert {item["id"] for item in body["actions"]} >= {"start", "pause", "resume", "stop"}
    assert body["bindings"] == {}

    saved = client.post("/v1/hotkeys", headers=headers, json={"bindings": []})
    assert saved.status_code == 200
    assert saved.json()["bindings"] == {}
