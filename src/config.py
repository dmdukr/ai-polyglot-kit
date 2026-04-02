"""Configuration management for AI Polyglot Kit."""

import os
import logging
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Default paths
APP_VERSION = "7.0.3"
APP_NAME = "AIPolyglotKit"
GITHUB_REPO = "dmdukr/ai-polyglot-kit"
APP_DIR = Path(os.environ.get("APPDATA", "")) / APP_NAME
DEFAULT_CONFIG_PATH = Path("config.yaml")


@dataclass
class GroqConfig:
    api_key: str = ""
    stt_model: str = "whisper-large-v3-turbo"
    llm_model: str = "llama-3.3-70b-versatile"
    stt_language: str | None = None
    stt_temperature: float = 0.0


@dataclass
class AudioConfig:
    mic_device_index: int | None = None
    sample_rate: int = 16000
    frame_duration_ms: int = 30
    vad_aggressiveness: int = 1
    silence_threshold_ms: int = 1500
    min_chunk_duration_ms: int = 500
    max_chunk_duration_s: int = 25
    gain: float = 0.0  # 0 = auto-gain, >0 = manual multiplier (e.g. 3.0 = 3x louder)


@dataclass
class NormalizationConfig:
    enabled: bool = True
    prompt: str = (
        "You are a text normalizer. Fix punctuation, capitalization, "
        "remove filler words (ну, ем, типа, like, uh, ehm, значит, короче, ну типа, как бы). "
        "Format numbers and dates properly. The text is multilingual (RU/UA/EN). "
        "Do NOT change the meaning or translate between languages. "
        "Return ONLY the corrected text without any explanation."
    )
    known_terms: list[str] = field(default_factory=lambda: [
        "Home Assistant", "MQTT", "Zigbee", "Groq"
    ])
    temperature: float = 0.1


@dataclass
class ProfileConfig:
    enabled: bool = True
    min_correction_count: int = 2
    max_prompt_tokens: int = 300
    decay_days: int = 90


@dataclass
class TextInjectionConfig:
    method: str = "sendinput"
    typing_delay_ms: int = 5
    backspace_batch_size: int = 50


@dataclass
class TelemetryConfig:
    enabled: bool = True  # send anonymous stats to improve recognition


@dataclass
class UIConfig:
    show_notifications: bool = True
    sound_on_start: bool = True
    sound_on_stop: bool = True
    language: str = "uk"  # UI language: "uk" or "en"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "groq-dictation.log"
    max_size_mb: int = 5
    backup_count: int = 3
    dev_logging: bool = False  # Enable DEBUG for src.context.* modules


@dataclass
class ProviderSlot:
    """One provider slot (API key + detected provider + model)."""
    api_key: str = ""
    provider: str = ""       # auto-detected or user-selected name
    base_url: str = ""       # auto-resolved or manual
    model: str = ""          # selected model ID


@dataclass
class ProvidersConfig:
    """Multi-provider slots with fallback chains."""
    stt: list = field(default_factory=lambda: [
        {"api_key": "", "provider": "", "base_url": "", "model": ""},
        {"api_key": "", "provider": "", "base_url": "", "model": ""},
        {"api_key": "", "provider": "", "base_url": "", "model": ""},
    ])
    llm: list = field(default_factory=lambda: [
        {"api_key": "", "provider": "", "base_url": "", "model": ""},
        {"api_key": "", "provider": "", "base_url": "", "model": ""},
        {"api_key": "", "provider": "", "base_url": "", "model": ""},
    ])
    translation: list = field(default_factory=lambda: [
        {"api_key": "", "provider": "", "base_url": "", "model": ""},
        {"api_key": "", "provider": "", "base_url": "", "model": ""},
        {"api_key": "", "provider": "", "base_url": "", "model": ""},
    ])


@dataclass
class AppConfig:
    groq: GroqConfig = field(default_factory=GroqConfig)  # backward compat, migrated on load
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    hotkey: str = "f12"
    hotkey_mode: str = "hold"  # "toggle" = press on/off, "hold" = record while held
    ptt_key: str = "f12"  # push-to-talk key (used in "hold" mode)
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    profile: ProfileConfig = field(default_factory=ProfileConfig)
    text_injection: TextInjectionConfig = field(default_factory=TextInjectionConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    server_port: int = 19378

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "AppConfig":
        """Load config from YAML file + .env for API key."""
        # Load .env file
        env_path = Path(".env")
        if env_path.exists():
            load_dotenv(env_path)
            logger.debug("config: loaded .env — path=%s", env_path.resolve())
        else:
            logger.debug("config: .env not found — path=%s", env_path.resolve())
        # Also check APPDATA location
        appdata_env = APP_DIR / ".env"
        if appdata_env.exists():
            load_dotenv(appdata_env)
            logger.debug("config: loaded APPDATA .env — path=%s", appdata_env)
        else:
            logger.debug("config: APPDATA .env not found — path=%s", appdata_env)

        config = cls()

        # Find config file — APPDATA (user settings) takes priority over local (defaults)
        if config_path is None:
            appdata_config = APP_DIR / "config.yaml"
            if appdata_config.exists():
                config_path = appdata_config
                logger.debug("config: using APPDATA config — path=%s", appdata_config)
            else:
                config_path = DEFAULT_CONFIG_PATH
                logger.debug("config: using local default config — path=%s", DEFAULT_CONFIG_PATH)
        config_path = Path(config_path)

        if config_path.exists():
            logger.info("config: loading config file — path=%s", config_path)
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            config._apply_dict(data)
            logger.debug("config: config file loaded successfully — keys=%s", list(data.keys()))
        else:
            logger.warning("config: config file not found, using defaults — path=%s", config_path)

        # Override API key from environment
        env_key = os.environ.get("GROQ_API_KEY")
        if env_key:
            config.groq.api_key = env_key
            logger.debug("config: GROQ_API_KEY loaded from environment — key_len=%d", len(env_key))
        else:
            logger.debug("config: GROQ_API_KEY not set in environment")

        # Auto-migrate old groq config → provider slots
        config._migrate_groq_to_providers()

        logger.debug(
            "config: final config — hotkey=%s, hotkey_mode=%s, sample_rate=%d, "
            "vad_aggressiveness=%d, normalization_enabled=%s, telemetry_enabled=%s",
            config.hotkey, config.hotkey_mode, config.audio.sample_rate,
            config.audio.vad_aggressiveness, config.normalization.enabled,
            config.telemetry.enabled,
        )
        return config

    def _migrate_groq_to_providers(self) -> None:
        """If groq.api_key is set and providers are empty, auto-migrate."""
        key = self.groq.api_key
        if not key:
            return
        # Check if STT slot #1 is already populated
        if self.providers.stt[0].get("api_key", ""):
            return
        logger.info("Migrating Groq config → provider slots")
        self.providers.stt[0] = {
            "api_key": key, "provider": "Groq",
            "base_url": "https://api.groq.com/openai/v1",
            "model": self.groq.stt_model,
        }
        self.providers.llm[0] = {
            "api_key": key, "provider": "Groq",
            "base_url": "https://api.groq.com/openai/v1",
            "model": self.groq.llm_model,
        }
        self.providers.translation[0] = {
            "api_key": key, "provider": "Groq",
            "base_url": "https://api.groq.com/openai/v1",
            "model": self.groq.llm_model,
        }

    def _apply_dict(self, data: dict) -> None:
        """Apply a dictionary of settings to this config.

        Walks dataclass fields: for nested dataclasses, merges sub-dicts;
        for plain fields, sets directly. Skips keys not present in data.
        Special case: groq.api_key only overrides if non-empty (avoid blanking).
        """
        for f in fields(self):
            if f.name not in data:
                logger.debug("config: _apply_dict — using default for field=%s", f.name)
                continue
            value = data[f.name]
            attr = getattr(self, f.name)
            if hasattr(attr, "__dataclass_fields__") and isinstance(value, dict):
                # Nested dataclass — merge fields
                for sub_f in fields(attr):
                    if sub_f.name in value:
                        sub_val = value[sub_f.name]
                        # Don't blank api_key from yaml (use .env instead)
                        if f.name == "groq" and sub_f.name == "api_key" and not sub_val:
                            logger.debug("config: _apply_dict — skipping blank groq.api_key")
                            continue
                        setattr(attr, sub_f.name, sub_val)
                logger.debug("config: _apply_dict — merged nested field=%s, sub_keys=%s",
                             f.name, list(value.keys()))
            else:
                setattr(self, f.name, value)
                logger.debug("config: _apply_dict — set field=%s", f.name)

    def to_dict(self) -> dict:
        """Serialize config to a dict suitable for YAML save.

        Clears api_key (stored in .env, not yaml).
        """
        data = asdict(self)
        data.get("groq", {})["api_key"] = ""  # never save key in yaml
        logger.debug("config: to_dict — serialized config for save, top_keys=%s", list(data.keys()))
        return data

    def validate(self) -> list[str]:
        """Validate config, return list of errors (empty = valid)."""
        errors = []
        # Check for API key in providers OR legacy groq config
        has_stt_key = self.groq.api_key or any(
            s.get("api_key") for s in self.providers.stt
        )
        if not has_stt_key:
            errors.append(
                "API ключ не налаштовано. Відкрийте Налаштування → STT та додайте ключ"
            )
        if self.audio.vad_aggressiveness not in (0, 1, 2, 3):
            errors.append("vad_aggressiveness must be 0-3")
        if self.audio.sample_rate != 16000:
            errors.append("sample_rate must be 16000 (Whisper requirement)")
        if self.audio.frame_duration_ms not in (10, 20, 30):
            errors.append("frame_duration_ms must be 10, 20, or 30 (webrtcvad requirement)")
        if self.text_injection.method not in ("sendinput", "clipboard", "uiautomation"):
            errors.append("text_injection.method must be 'sendinput', 'clipboard', or 'uiautomation'")
        if errors:
            logger.info("config: validation failed — errors=%s", errors)
        else:
            logger.debug("config: validation passed — no errors")
        return errors


def setup_logging(config: LoggingConfig) -> None:
    """Configure logging based on config."""
    log_dir = APP_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / config.file
    logger.debug("config: setup_logging — level=%s, file=%s, max_size_mb=%d, backup_count=%d",
                 config.level, log_file, config.max_size_mb, config.backup_count)

    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(
        log_file,
        maxBytes=config.max_size_mb * 1024 * 1024,
        backupCount=config.backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(threadName)s] %(levelname)s %(name)s: %(message)s"
    ))

    root = logging.getLogger()
    root.setLevel(getattr(logging, config.level, logging.INFO))
    root.addHandler(handler)

    # Also log to console for development
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    root.addHandler(console)

    # Dev logging: enable DEBUG for context engine modules
    if config.dev_logging:
        for mod in [
            "src.context.engine", "src.context.keywords", "src.context.cooccurrence",
            "src.context.clusters", "src.context.threads", "src.context.dictionary",
            "src.context.corrections", "src.context.pipeline", "src.context.prompt_builder",
            "src.context.script_validator", "src.context.maintenance", "src.context.db",
        ]:
            logging.getLogger(mod).setLevel(logging.DEBUG)
        logging.getLogger("src.context").setLevel(logging.DEBUG)
        logger.info("Dev logging enabled for src.context.* (DEBUG level)")

    # Better Stack remote logging
    try:
        from src.betterstack_handler import BetterStackHandler  # noqa: PLC0415

        bs_handler = BetterStackHandler()
        bs_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(threadName)s] %(levelname)s %(name)s: %(message)s"
        ))
        root.addHandler(bs_handler)
        logger.info("Better Stack remote logging enabled")
    except Exception:
        pass  # Better Stack optional
