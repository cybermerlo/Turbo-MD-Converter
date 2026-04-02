"""Application configuration management."""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class AppConfig:
    """Central configuration for the application."""

    gemini_api_key: str = ""
    langextract_api_key: str = ""
    output_directory: str = ""
    ocr_model_id: str = "gemini-3.1-flash-lite-preview"
    extraction_model_id: str = "gemini-3.1-flash-lite-preview"
    ocr_prompt: str = ""
    active_schema: str = "full_legal"
    output_formats: list[str] = field(default_factory=lambda: ["markdown"])
    extraction_passes: int = 1
    max_workers: int = 15
    max_char_buffer: int = 1000
    page_dpi: int = 200
    jpeg_quality: int = 85
    include_ocr_text_in_output: bool = True
    run_ocr: bool = True
    run_extraction: bool = False
    rename_files: bool = False
    rename_mode: str = "both"
    rename_prompt: str = ""
    use_output_subfolder: bool = False
    output_subfolder_name: str = "File MD Convertiti"
    custom_schema_prompts: dict = field(default_factory=dict)
    asked_sendto: bool = False
    smart_text_detection: bool = True


def get_config_dir() -> Path:
    """Returns the app config directory, creating it if needed."""
    config_dir = Path(os.environ.get("APPDATA", Path.home())) / "OCRLangExtract"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path() -> Path:
    """Returns the path to the config JSON file."""
    return get_config_dir() / "config.json"


def load_env_keys(project_dir: Path | None = None) -> tuple[str, str]:
    """Load API keys from .env file.

    Returns (gemini_api_key, langextract_api_key).
    """
    if project_dir:
        load_dotenv(project_dir / ".env")
    else:
        load_dotenv()

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    langextract_key = os.environ.get("LANGEXTRACT_API_KEY", gemini_key)
    return gemini_key, langextract_key


def load_config(config_path: Path | None = None,
                project_dir: Path | None = None) -> AppConfig:
    """Load config from JSON file, then override API keys from .env."""
    from config.defaults import DEFAULT_OCR_PROMPT

    path = config_path or get_config_path()
    config = AppConfig()

    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, value in data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
        except (json.JSONDecodeError, OSError):
            pass

    # Set default OCR prompt if empty
    if not config.ocr_prompt:
        config.ocr_prompt = DEFAULT_OCR_PROMPT

    # Override API keys from environment
    gemini_key, langextract_key = load_env_keys(project_dir)
    if gemini_key:
        config.gemini_api_key = gemini_key
    if langextract_key:
        config.langextract_api_key = langextract_key

    return config


def save_config(config: AppConfig, config_path: Path | None = None) -> None:
    """Save config to JSON file, compresa la chiave API."""
    path = config_path or get_config_path()
    data = asdict(config)
    # L'API key ora viene salvata nel config.json locale in AppData
    # affinché l'eseguibile ne mantenga la memoria.

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
