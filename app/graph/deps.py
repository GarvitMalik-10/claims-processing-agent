"""Dependencies shared by graph nodes (stores, model clients, reference data, versioned config)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.data.loader import SyntheticData, synthetic
from app.jev.client import Jev, JevClient
from app.llm.claude import ClaudeClient
from app.llm.fixtures import FixtureMode, FixtureStore
from app.settings import ROOT, Settings, VersionedConfig, get_settings, load_config
from app.store.blobs import LocalBlobStore
from app.store.event_store import SqliteEventStore


@dataclass
class Deps:
    store: SqliteEventStore
    blobs: LocalBlobStore
    claude: ClaudeClient
    jev: Jev
    data: SyntheticData
    thresholds: VersionedConfig
    completeness: VersionedConfig
    consistency: VersionedConfig | None = None
    risk_weights: VersionedConfig | None = None
    storm_days: VersionedConfig | None = None
    peril_clauses: VersionedConfig | None = None

    def __post_init__(self) -> None:
        for name in ("consistency", "risk_weights", "storm_days", "peril_clauses"):
            if getattr(self, name) is None:
                setattr(self, name, load_config(name))

    def config_versions(self, *names: str) -> dict[str, str]:
        return {n: getattr(self, n).sha256[:12] for n in names}


def build_deps(settings: Settings | None = None, *, fixture_mode: FixtureMode = "off",
               fixtures_root: Path = ROOT / "tests" / "fixtures") -> Deps:
    s = settings or get_settings()
    blobs = LocalBlobStore(s.blob_dir)
    jev_mode: FixtureMode = "replay" if s.jev_mode == "replay" else fixture_mode
    return Deps(
        store=SqliteEventStore(s.event_db),
        blobs=blobs,
        claude=ClaudeClient(blobs, fixtures=FixtureStore(fixtures_root / "claude", fixture_mode)),
        jev=JevClient(blobs, fixtures=FixtureStore(fixtures_root / "jev", jev_mode)),
        data=synthetic(),
        thresholds=load_config("thresholds"),
        completeness=load_config("completeness"),
    )
