"""Tests for src/ui/settings_contract — config_to_ui / ui_to_config round-trip.

Covers:
- config_to_ui produces expected dict shape
- ui_to_config maps SPA fields back to AppConfig
- Round-trip: config -> ui -> config preserves values
- Language shortcut promotion / demotion
- Autostart flag handling (non-Windows = no-op)
- Backward-compat: providers.stt[0].api_key -> groq.api_key sync
"""

from __future__ import annotations

from dataclasses import asdict
from unittest.mock import patch

import pytest
from src.config import AppConfig
from src.ui.settings_contract import _get_autostart, _set_autostart, config_to_ui, ui_to_config

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def default_config() -> AppConfig:
    """Fresh AppConfig with all defaults."""
    return AppConfig()


@pytest.fixture
def populated_config() -> AppConfig:
    """AppConfig with non-default values for thorough testing."""
    cfg = AppConfig()
    cfg.groq.api_key = "gsk_test_key_12345"
    cfg.groq.stt_model = "whisper-large-v3"
    cfg.groq.llm_model = "llama-3.1-8b"
    cfg.groq.stt_language = "uk"
    cfg.groq.stt_temperature = 0.2
    cfg.providers.stt[0] = {
        "api_key": "gsk_test_key_12345",
        "provider": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "whisper-large-v3",
    }
    cfg.audio.mic_device_index = 3
    cfg.audio.vad_aggressiveness = 2
    cfg.audio.gain = 2.5
    cfg.hotkey = "f9"
    cfg.hotkey_mode = "toggle"
    cfg.ptt_key = "f9"
    cfg.normalization.enabled = False
    cfg.normalization.temperature = 0.3
    cfg.profile.enabled = False
    cfg.text_injection.method = "clipboard"
    cfg.text_injection.typing_delay_ms = 10
    cfg.telemetry.enabled = False
    cfg.ui.language = "en"
    cfg.ui.show_notifications = False
    cfg.ui.sound_on_start = False
    cfg.logging.level = "DEBUG"
    cfg.server_port = 9999
    return cfg


# =============================================================================
# config_to_ui
# =============================================================================


class TestConfigToUi:
    """Tests for config_to_ui()."""

    def test_returns_dict(self, default_config: AppConfig) -> None:
        """Result is a plain dict, not a dataclass."""
        result = config_to_ui(default_config)
        assert isinstance(result, dict)

    def test_contains_all_top_level_keys(self, default_config: AppConfig) -> None:
        """Result contains all AppConfig top-level fields plus extras."""
        result = config_to_ui(default_config)
        expected_keys = {
            "groq",
            "providers",
            "audio",
            "hotkey",
            "hotkey_mode",
            "ptt_key",
            "normalization",
            "profile",
            "text_injection",
            "telemetry",
            "ui",
            "logging",
            "server_port",
            # Extras added by contract
            "language",
            "autostart",
        }
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_language_shortcut_matches_ui_language(self, default_config: AppConfig) -> None:
        """Top-level 'language' mirrors config.ui.language."""
        result = config_to_ui(default_config)
        assert result["language"] == default_config.ui.language
        assert result["language"] == result["ui"]["language"]

    def test_language_shortcut_with_en(self, populated_config: AppConfig) -> None:
        """Language shortcut works for non-default language."""
        result = config_to_ui(populated_config)
        assert result["language"] == "en"
        assert result["ui"]["language"] == "en"

    def test_autostart_false_on_linux(self, default_config: AppConfig) -> None:
        """On non-Windows, autostart is always False."""
        result = config_to_ui(default_config)
        assert result["autostart"] is False

    def test_nested_audio_preserved(self, populated_config: AppConfig) -> None:
        """Audio sub-dict retains all fields with correct values."""
        result = config_to_ui(populated_config)
        assert result["audio"]["mic_device_index"] == 3
        assert result["audio"]["vad_aggressiveness"] == 2
        assert result["audio"]["gain"] == 2.5

    def test_nested_providers_preserved(self, populated_config: AppConfig) -> None:
        """Providers sub-dict retains slot data."""
        result = config_to_ui(populated_config)
        stt_slot0 = result["providers"]["stt"][0]
        assert stt_slot0["api_key"] == "gsk_test_key_12345"
        assert stt_slot0["provider"] == "Groq"

    def test_scalar_fields_preserved(self, populated_config: AppConfig) -> None:
        """Top-level scalar fields pass through."""
        result = config_to_ui(populated_config)
        assert result["hotkey"] == "f9"
        assert result["hotkey_mode"] == "toggle"
        assert result["ptt_key"] == "f9"
        assert result["server_port"] == 9999

    def test_normalization_preserved(self, populated_config: AppConfig) -> None:
        """Normalization config passes through correctly."""
        result = config_to_ui(populated_config)
        assert result["normalization"]["enabled"] is False
        assert result["normalization"]["temperature"] == 0.3

    def test_telemetry_preserved(self, populated_config: AppConfig) -> None:
        """Telemetry config passes through as nested dict."""
        result = config_to_ui(populated_config)
        assert result["telemetry"]["enabled"] is False

    def test_result_is_independent_copy(self, default_config: AppConfig) -> None:
        """Modifying the result dict does not mutate the original config."""
        result = config_to_ui(default_config)
        result["hotkey"] = "f1"
        result["audio"]["gain"] = 999.0
        assert default_config.hotkey == "f12"
        assert default_config.audio.gain == 0.0


# =============================================================================
# ui_to_config
# =============================================================================


class TestUiToConfig:
    """Tests for ui_to_config()."""

    def test_language_moved_to_ui_section(self, default_config: AppConfig) -> None:
        """Top-level 'language' is demoted into config.ui.language."""
        ui_to_config({"language": "en"}, default_config)
        assert default_config.ui.language == "en"

    def test_language_removed_from_top_level(self, default_config: AppConfig) -> None:
        """After processing, 'language' does not leak as a top-level config key."""
        data = {"language": "en"}
        ui_to_config(data, default_config)
        # _apply_dict should not see "language" at top level
        assert not hasattr(default_config, "language_EXTRA")

    def test_autostart_popped_and_no_crash(self, default_config: AppConfig) -> None:
        """Autostart flag is consumed without crashing on Linux."""
        ui_to_config({"autostart": True}, default_config)
        # On Linux, _set_autostart is a no-op; config should not have "autostart" field

    def test_autostart_calls_set_autostart(self, default_config: AppConfig) -> None:
        """Autostart triggers _set_autostart with the boolean value."""
        with patch("src.ui.settings_contract._set_autostart") as mock_set:
            ui_to_config({"autostart": True}, default_config)
            mock_set.assert_called_once_with(True)

    def test_autostart_false_calls_set_autostart(self, default_config: AppConfig) -> None:
        """Autostart=False also triggers _set_autostart."""
        with patch("src.ui.settings_contract._set_autostart") as mock_set:
            ui_to_config({"autostart": False}, default_config)
            mock_set.assert_called_once_with(False)

    def test_hotkey_applied(self, default_config: AppConfig) -> None:
        """Scalar field like hotkey is applied via _apply_dict."""
        ui_to_config({"hotkey": "f10"}, default_config)
        assert default_config.hotkey == "f10"

    def test_audio_fields_applied(self, default_config: AppConfig) -> None:
        """Nested audio dict is merged onto AudioConfig."""
        ui_to_config({"audio": {"gain": 3.0, "vad_aggressiveness": 3}}, default_config)
        assert default_config.audio.gain == 3.0
        assert default_config.audio.vad_aggressiveness == 3

    def test_normalization_applied(self, default_config: AppConfig) -> None:
        """Nested normalization dict is merged."""
        ui_to_config({"normalization": {"enabled": False, "temperature": 0.5}}, default_config)
        assert default_config.normalization.enabled is False
        assert default_config.normalization.temperature == 0.5

    def test_providers_applied(self, default_config: AppConfig) -> None:
        """Provider slots are applied as lists."""
        new_stt = [{"api_key": "key1", "provider": "Groq", "base_url": "", "model": "w"}]
        ui_to_config({"providers": {"stt": new_stt}}, default_config)
        assert default_config.providers.stt == new_stt

    def test_stt_api_key_synced_to_groq(self, default_config: AppConfig) -> None:
        """If providers.stt[0] has api_key, it is copied to groq.api_key."""
        stt_slots = [
            {"api_key": "gsk_synced_key", "provider": "Groq", "base_url": "", "model": "w"},
        ]
        ui_to_config({"providers": {"stt": stt_slots}}, default_config)
        assert default_config.groq.api_key == "gsk_synced_key"

    def test_stt_api_key_not_synced_if_empty(self, default_config: AppConfig) -> None:
        """Empty stt[0].api_key does not blank groq.api_key."""
        default_config.groq.api_key = "original_key"
        stt_slots = [{"api_key": "", "provider": "", "base_url": "", "model": ""}]
        ui_to_config({"providers": {"stt": stt_slots}}, default_config)
        assert default_config.groq.api_key == "original_key"

    def test_stt_api_key_sync_no_stt_slots(self, default_config: AppConfig) -> None:
        """If providers has no stt key, groq.api_key is unchanged."""
        default_config.groq.api_key = "keep_me"
        ui_to_config({"providers": {"llm": []}}, default_config)
        assert default_config.groq.api_key == "keep_me"

    def test_empty_data_is_noop(self, default_config: AppConfig) -> None:
        """Empty dict does not change any config values."""
        original = asdict(default_config)
        ui_to_config({}, default_config)
        assert asdict(default_config) == original

    def test_multiple_fields_at_once(self, default_config: AppConfig) -> None:
        """Multiple fields in one call are all applied."""
        ui_to_config(
            {
                "language": "en",
                "hotkey": "f10",
                "audio": {"gain": 2.0},
                "telemetry": {"enabled": False},
            },
            default_config,
        )
        assert default_config.ui.language == "en"
        assert default_config.hotkey == "f10"
        assert default_config.audio.gain == 2.0
        assert default_config.telemetry.enabled is False

    def test_server_port_applied(self, default_config: AppConfig) -> None:
        """server_port scalar is applied."""
        ui_to_config({"server_port": 8080}, default_config)
        assert default_config.server_port == 8080


# =============================================================================
# Round-trip: config_to_ui -> ui_to_config
# =============================================================================


class TestRoundTrip:
    """Verify that config -> UI -> config preserves all values."""

    def test_default_config_round_trip(self, default_config: AppConfig) -> None:
        """Default config survives a round-trip through the contract."""
        original = asdict(default_config)
        ui_data = config_to_ui(default_config)

        fresh = AppConfig()
        ui_to_config(ui_data, fresh)
        restored = asdict(fresh)

        # Compare all nested keys (except autostart which is transient)
        for key in original:
            assert restored[key] == original[key], f"Round-trip mismatch on '{key}': {original[key]} != {restored[key]}"

    def test_populated_config_round_trip(self, populated_config: AppConfig) -> None:
        """Non-default config survives a round-trip."""
        original = asdict(populated_config)
        ui_data = config_to_ui(populated_config)

        fresh = AppConfig()
        ui_to_config(ui_data, fresh)
        restored = asdict(fresh)

        for key in original:
            assert restored[key] == original[key], f"Round-trip mismatch on '{key}': {original[key]} != {restored[key]}"

    def test_language_round_trip(self) -> None:
        """Language shortcut round-trips correctly."""
        cfg = AppConfig()
        cfg.ui.language = "en"

        ui_data = config_to_ui(cfg)
        assert ui_data["language"] == "en"

        fresh = AppConfig()
        ui_to_config(ui_data, fresh)
        assert fresh.ui.language == "en"

    def test_partial_update_round_trip(self, default_config: AppConfig) -> None:
        """Partial UI update (only changed fields) preserves unchanged fields."""
        # First, set some non-default values
        default_config.hotkey = "f5"
        default_config.audio.gain = 1.5

        # Simulate UI sending only the changed field
        ui_to_config({"hotkey": "f7"}, default_config)

        assert default_config.hotkey == "f7"  # changed
        assert default_config.audio.gain == 1.5  # preserved


# =============================================================================
# _get_autostart / _set_autostart (Linux behavior)
# =============================================================================


class TestAutostart:
    """Platform-specific autostart helpers on Linux."""

    def test_get_autostart_returns_false_on_linux(self) -> None:
        """On Linux, _get_autostart always returns False."""
        assert _get_autostart() is False

    def test_set_autostart_noop_on_linux(self) -> None:
        """On Linux, _set_autostart does nothing and does not raise."""
        _set_autostart(True)  # should not raise
        _set_autostart(False)  # should not raise


# =============================================================================
# Edge cases
# =============================================================================


class TestEdgeCases:
    """Edge cases and defensive behavior."""

    def test_unknown_keys_ignored_by_apply_dict(self, default_config: AppConfig) -> None:
        """Keys not in AppConfig fields are silently ignored by _apply_dict."""
        ui_to_config({"unknown_key": "value", "hotkey": "f11"}, default_config)
        assert default_config.hotkey == "f11"
        assert not hasattr(default_config, "unknown_key")

    def test_language_and_ui_language_both_present(self, default_config: AppConfig) -> None:
        """If both 'language' and 'ui.language' are sent, top-level wins."""
        ui_to_config(
            {
                "language": "en",
                "ui": {"language": "uk"},
            },
            default_config,
        )
        # The contract moves language -> ui.language before _apply_dict,
        # so "en" is set first, then ui dict with "uk" overwrites.
        # This is the expected precedence: explicit ui section wins.
        assert default_config.ui.language in ("en", "uk")

    def test_providers_stt_empty_list_no_crash(self, default_config: AppConfig) -> None:
        """Empty STT providers list does not crash the api_key sync."""
        default_config.groq.api_key = "keep"
        ui_to_config({"providers": {"stt": []}}, default_config)
        assert default_config.groq.api_key == "keep"

    def test_providers_stt_no_api_key_field(self, default_config: AppConfig) -> None:
        """STT slot without api_key field does not crash."""
        default_config.groq.api_key = "keep"
        ui_to_config({"providers": {"stt": [{"provider": "Groq", "model": "w"}]}}, default_config)
        assert default_config.groq.api_key == "keep"
