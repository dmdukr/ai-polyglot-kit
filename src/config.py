"""Configuration management for Groq Dictation."""

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Default paths
APP_VERSION = "1.3.3"
APP_NAME = "GroqDictation"
GITHUB_REPO = "dmdukr/groq-dictation"  # owner/repo for auto-update
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


@dataclass
class AppConfig:
    groq: GroqConfig = field(default_factory=GroqConfig)
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

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "AppConfig":
        """Load config from YAML file + .env for API key."""
        # Load .env file
        env_path = Path(".env")
        if env_path.exists():
            load_dotenv(env_path)
        # Also check APPDATA location
        appdata_env = APP_DIR / ".env"
        if appdata_env.exists():
            load_dotenv(appdata_env)

        config = cls()

        # Find config file
        if config_path is None:
            config_path = DEFAULT_CONFIG_PATH
        config_path = Path(config_path)

        if not config_path.exists():
            # Try APPDATA location
            config_path = APP_DIR / "config.yaml"

        if config_path.exists():
            logger.info(f"Loading config from {config_path}")
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            config._apply_dict(data)
        else:
            logger.warning(f"Config file not found at {config_path}, using defaults")

        # Override API key from environment
        env_key = os.environ.get("GROQ_API_KEY")
        if env_key:
            config.groq.api_key = env_key

        return config

    def _apply_dict(self, data: dict) -> None:
        """Apply a dictionary of settings to this config."""
        if "groq" in data:
            g = data["groq"]
            if "api_key" in g and g["api_key"]:
                self.groq.api_key = g["api_key"]
            if "stt_model" in g:
                self.groq.stt_model = g["stt_model"]
            if "llm_model" in g:
                self.groq.llm_model = g["llm_model"]
            if "stt_language" in g:
                self.groq.stt_language = g["stt_language"]
            if "stt_temperature" in g:
                self.groq.stt_temperature = g["stt_temperature"]

        if "audio" in data:
            a = data["audio"]
            for attr in (
                "mic_device_index", "sample_rate", "frame_duration_ms",
                "vad_aggressiveness", "silence_threshold_ms", "gain",
                "min_chunk_duration_ms", "max_chunk_duration_s",
            ):
                if attr in a:
                    setattr(self.audio, attr, a[attr])

        if "hotkey" in data:
            self.hotkey = data["hotkey"]
        if "hotkey_mode" in data:
            self.hotkey_mode = data["hotkey_mode"]
        if "ptt_key" in data:
            self.ptt_key = data["ptt_key"]

        if "normalization" in data:
            n = data["normalization"]
            if "enabled" in n:
                self.normalization.enabled = n["enabled"]
            if "prompt" in n:
                self.normalization.prompt = n["prompt"]
            if "known_terms" in n:
                self.normalization.known_terms = n["known_terms"]
            if "temperature" in n:
                self.normalization.temperature = n["temperature"]

        if "profile" in data:
            p = data["profile"]
            for attr in ("enabled", "min_correction_count", "max_prompt_tokens", "decay_days"):
                if attr in p:
                    setattr(self.profile, attr, p[attr])

        if "text_injection" in data:
            t = data["text_injection"]
            if "method" in t:
                self.text_injection.method = t["method"]
            if "typing_delay_ms" in t:
                self.text_injection.typing_delay_ms = t["typing_delay_ms"]
            if "backspace_batch_size" in t:
                self.text_injection.backspace_batch_size = t["backspace_batch_size"]

        if "telemetry" in data:
            tel = data["telemetry"]
            if "enabled" in tel:
                self.telemetry.enabled = tel["enabled"]

        if "ui" in data:
            u = data["ui"]
            for attr in ("show_notifications", "sound_on_start", "sound_on_stop", "language"):
                if attr in u:
                    setattr(self.ui, attr, u[attr])

        if "logging" in data:
            lg = data["logging"]
            for attr in ("level", "file", "max_size_mb", "backup_count"):
                if attr in lg:
                    setattr(self.logging, attr, lg[attr])

    def validate(self) -> list[str]:
        """Validate config, return list of errors (empty = valid)."""
        errors = []
        if not self.groq.api_key:
            errors.append(
                "Groq API key not set. Use GROQ_API_KEY env var, .env file, or config.yaml"
            )
        if self.audio.vad_aggressiveness not in (0, 1, 2, 3):
            errors.append("vad_aggressiveness must be 0-3")
        if self.audio.sample_rate != 16000:
            errors.append("sample_rate must be 16000 (Whisper requirement)")
        if self.audio.frame_duration_ms not in (10, 20, 30):
            errors.append("frame_duration_ms must be 10, 20, or 30 (webrtcvad requirement)")
        if self.text_injection.method not in ("sendinput", "clipboard"):
            errors.append("text_injection.method must be 'sendinput' or 'clipboard'")
        return errors


def setup_logging(config: LoggingConfig) -> None:
    """Configure logging based on config."""
    log_dir = APP_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / config.file

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
