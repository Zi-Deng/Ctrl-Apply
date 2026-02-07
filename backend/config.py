from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Paths
    base_dir: Path = Path(__file__).resolve().parent.parent
    data_dir: Path = base_dir / "data"
    profile_path: Path = data_dir / "profile.yaml"
    resume_path: Path = data_dir / "resume.pdf"
    resume_parsed_path: Path = data_dir / "resume_parsed.json"
    db_path: Path = data_dir / "jobs.duckdb"
    cover_letters_dir: Path = data_dir / "cover_letters"

    # Server
    host: str = "127.0.0.1"
    port: int = 8765

    # LLM
    llm_mode: Literal["cloud", "local"] = "cloud"
    local_model: str = "qwen3-coder"
    local_ollama_url: str = "http://localhost:11434"

    # Chrome CDP
    cdp_url: str = "http://localhost:9222"

    # Form filling
    fill_delay_min: float = 0.2
    fill_delay_max: float = 0.8
    dropdown_match_threshold: int = 70  # rapidfuzz score 0-100
    combobox_open_timeout: int = 3000  # ms to wait for ARIA listbox after clicking trigger

    # Repeatable sections
    add_button_wait: float = 1.5  # seconds to wait after clicking an Add button
    extraction_timeout: float = 10.0  # seconds to wait for extraction response from extension
    max_section_entries: int = 10  # safety limit on entries per section

    model_config = {"env_prefix": "CTRL_APPLY_"}


settings = Settings()
