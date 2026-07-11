"""V2 scoring configuration — initial, active, and legacy V1 fallback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from operating_mode import DEFAULT_MODE, normalize_mode

INITIAL_CONFIG_PATH = Path(__file__).with_name("scoring_config_v2_initial.json")
ACTIVE_CONFIG_KEY = "active_v2_config_path"
SCORER_MODE_KEY = "scorer_mode"  # v2 | v1_legacy


def active_config_key(mode: str | None = None) -> str:
    return f"active_v2_config_path_{normalize_mode(mode)}"


def scorer_mode_key(mode: str | None = None) -> str:
    return f"scorer_mode_{normalize_mode(mode)}"


def load_v2_config(path: Path | None = None) -> dict[str, Any]:
    p = path or INITIAL_CONFIG_PATH
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def migrate_legacy_settings(store) -> None:
    """Map pre-mode settings to Open Mode; seed Box Mode with baseline V2."""
    legacy_path = store.get_setting(ACTIVE_CONFIG_KEY, "")
    legacy_scorer = store.get_setting(SCORER_MODE_KEY, "v2")
    initial = str(INITIAL_CONFIG_PATH)

    if not store.get_setting(active_config_key("open"), ""):
        store.set_setting(active_config_key("open"), legacy_path or initial)
    if not store.get_setting(active_config_key("box"), ""):
        store.set_setting(active_config_key("box"), initial)

    if not store.get_setting(scorer_mode_key("open"), ""):
        store.set_setting(scorer_mode_key("open"), legacy_scorer if legacy_scorer else "v2")
    if not store.get_setting(scorer_mode_key("box"), ""):
        store.set_setting(scorer_mode_key("box"), "v2")


def load_active_v2_config(store_getter=None, mode: str | None = None) -> dict[str, Any]:
    """Load active V2 config for the given operating mode."""
    mode = normalize_mode(mode)
    try:
        if store_getter:
            store = store_getter()
            migrate_legacy_settings(store)
            active = store.get_setting(active_config_key(mode), "")
            if active and Path(active).exists():
                return load_v2_config(Path(active))
    except Exception:
        pass
    return load_v2_config(INITIAL_CONFIG_PATH)


def get_scorer_mode(store_getter=None, mode: str | None = None) -> str:
    mode = normalize_mode(mode)
    try:
        if store_getter:
            store = store_getter()
            migrate_legacy_settings(store)
            scorer = store.get_setting(scorer_mode_key(mode), "v2")
            return scorer if scorer in ("v2", "v1_legacy") else "v2"
    except Exception:
        pass
    return "v2"


def set_active_config_path(store, path: Path, mode: str | None = None) -> None:
    migrate_legacy_settings(store)
    store.set_setting(active_config_key(mode), str(path))


def revert_to_initial_v2(store, mode: str | None = None) -> None:
    migrate_legacy_settings(store)
    store.set_setting(active_config_key(mode), str(INITIAL_CONFIG_PATH))
    store.set_setting(scorer_mode_key(mode), "v2")


def revert_to_v1_legacy(store, mode: str | None = None) -> None:
    migrate_legacy_settings(store)
    store.set_setting(scorer_mode_key(mode), "v1_legacy")
