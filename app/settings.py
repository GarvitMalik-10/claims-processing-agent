"""Runtime settings from environment / .env, and versioned YAML business config."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
SYNTHETIC_DIR = ROOT / "data" / "synthetic"

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    llm_model: str = field(default_factory=lambda: os.getenv("TECTO_LLM_MODEL", "claude-sonnet-5-5"))
    jev_model: str = field(default_factory=lambda: os.getenv("TECTO_JEV_MODEL", "jev-latest"))
    jev_mode: Literal["live", "replay"] = field(default_factory=lambda: os.getenv("TECTO_JEV_MODE", "live"))  # type: ignore[assignment]
    data_dir: Path = field(default_factory=lambda: ROOT / os.getenv("TECTO_DATA_DIR", "var"))

    @property
    def event_db(self) -> Path:
        return self.data_dir / "claims.sqlite"

    @property
    def checkpoint_db(self) -> Path:
        return self.data_dir / "checkpoints.sqlite"

    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"


@lru_cache
def get_settings() -> Settings:
    return Settings()


@dataclass(frozen=True)
class VersionedConfig:
    """A YAML config file plus the sha256 of its bytes, recorded on every decision that uses it."""

    name: str
    data: dict[str, Any]
    sha256: str


def load_config(name: str, config_dir: Path = CONFIG_DIR) -> VersionedConfig:
    raw = (config_dir / f"{name}.yaml").read_bytes()
    return VersionedConfig(name=name, data=yaml.safe_load(raw), sha256=hashlib.sha256(raw).hexdigest())


def config_versions(*names: str) -> dict[str, str]:
    """Short config hashes for event provenance, e.g. {"thresholds": "3f2a9c1e"}."""
    return {n: load_config(n).sha256[:12] for n in names}
