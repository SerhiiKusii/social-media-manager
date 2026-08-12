from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


class Settings(BaseSettings):
    """Env-derived settings. Secrets and mode switches only — non-secret
    tuning knobs live in config/app.toml and config/brands/*.toml."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    apify_mode: Literal["fixture", "live"] = Field("fixture", alias="TRENDSTEALER_APIFY_MODE")
    llm_backend: Literal["fixture", "anthropic"] = Field(
        "fixture", alias="TRENDSTEALER_LLM_BACKEND"
    )
    publish_mode: Literal["dry_run", "live"] = Field("dry_run", alias="TRENDSTEALER_PUBLISH_MODE")

    anthropic_api_key: str | None = Field(None, alias="ANTHROPIC_API_KEY")
    apify_api_token: str | None = Field(None, alias="APIFY_API_TOKEN")

    review_dashboard_token: str | None = Field(None, alias="REVIEW_DASHBOARD_TOKEN")
    review_dashboard_host: str = Field("127.0.0.1", alias="REVIEW_DASHBOARD_HOST")
    review_dashboard_port: int = Field(5000, alias="REVIEW_DASHBOARD_PORT")
    flask_secret_key: str | None = Field(None, alias="FLASK_SECRET_KEY")

    upload_host_base_url: str | None = Field(None, alias="UPLOAD_HOST_BASE_URL")
    upload_host_access_key: str | None = Field(None, alias="UPLOAD_HOST_ACCESS_KEY")
    upload_host_secret_key: str | None = Field(None, alias="UPLOAD_HOST_SECRET_KEY")

    db_path: Path = Field(Path("var/db/trendstealer.db"), alias="TRENDSTEALER_DB_PATH")
    var_dir: Path = Field(Path("var"), alias="TRENDSTEALER_VAR_DIR")

    @property
    def db_path_abs(self) -> Path:
        return self.db_path if self.db_path.is_absolute() else REPO_ROOT / self.db_path

    @property
    def var_dir_abs(self) -> Path:
        return self.var_dir if self.var_dir.is_absolute() else REPO_ROOT / self.var_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()


def brand_secret(name: str, brand_id: str) -> str | None:
    """Resolve a per-brand secret env var with unsuffixed fallback.

    e.g. brand_secret("IG_ACCESS_TOKEN", "acme") checks IG_ACCESS_TOKEN__ACME
    then falls back to IG_ACCESS_TOKEN.
    """
    suffixed = f"{name}__{brand_id.upper()}"
    return os.environ.get(suffixed) or os.environ.get(name)


# --- config/app.toml sections -----------------------------------------------


class ViralityConfig(BaseModel):
    min_views: int = 100_000
    max_age_hours: int = 96
    min_views_per_follower: float = 3.0
    min_engagement_rate: float = 0.03
    min_duration_secs: int = 8
    max_duration_secs: int = 90
    max_items_per_run: int = 3


class DedupeConfig(BaseModel):
    simhash_hamming_threshold: int = 3
    simhash_window_days: int = 30
    audio_cooldown_days: int = 14


class IntelligenceConfig(BaseModel):
    llm_backend: Literal["fixture", "anthropic"] = "fixture"
    model: str = "claude-opus-5"
    max_tokens: int = 16000
    max_revisions: int = 3


class TTSConfig(BaseModel):
    backend: Literal["piper"] = "piper"
    target_lufs: float = -16.0
    sample_rate_hz: int = 48000


class RenderConfig(BaseModel):
    concurrency: str = "half-cpu"
    bundle_cache_dir: str = "var/bundle"


class PublishConfig(BaseModel):
    mode: Literal["dry_run", "live"] = "dry_run"
    max_posts_per_day: int = 2
    max_posts_per_day_ceiling: int = 3
    min_gap_minutes: int = 240


class ReviewDashboardConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 5000


class WorkerConfig(BaseModel):
    lease_ttl_seconds: int = 600


class IngestConfig(BaseModel):
    apify_monthly_cu_cap: int = 500
    scrape_actor_timeout_secs: int = 120


class AppConfig(BaseModel):
    ingest: IngestConfig = IngestConfig()
    virality: ViralityConfig = ViralityConfig()
    dedupe: DedupeConfig = DedupeConfig()
    intelligence: IntelligenceConfig = IntelligenceConfig()
    tts: TTSConfig = TTSConfig()
    render: RenderConfig = RenderConfig()
    publish: PublishConfig = PublishConfig()
    review_dashboard: ReviewDashboardConfig = ReviewDashboardConfig()
    worker: WorkerConfig = WorkerConfig()


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


@lru_cache
def load_app_config(path: Path | None = None) -> AppConfig:
    path = path or (CONFIG_DIR / "app.toml")
    return AppConfig.model_validate(_load_toml(path))


# --- config/brands/*.toml ----------------------------------------------------


class BrandIdentity(BaseModel):
    id: str
    name: str
    product_brief: str
    palette: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)


class BrandAccounts(BaseModel):
    instagram_business_account_id_env: str = "IG_BUSINESS_ACCOUNT_ID"


class BrandPostingWindows(BaseModel):
    windows: list[str] = Field(default_factory=list)
    timezone: str = "UTC"


class BrandSources(BaseModel):
    tiktok_seed_accounts: list[str] = Field(default_factory=list)
    instagram_seed_hashtags: list[str] = Field(default_factory=list)


class BrandConfig(BaseModel):
    brand: BrandIdentity
    accounts: BrandAccounts = BrandAccounts()
    posting_windows: BrandPostingWindows = BrandPostingWindows()
    sources: BrandSources = BrandSources()
    virality: ViralityConfig
    publish: PublishConfig

    @property
    def id(self) -> str:
        return self.brand.id

    def instagram_access_token(self) -> str | None:
        return brand_secret("IG_ACCESS_TOKEN", self.id)

    def instagram_business_account_id(self) -> str | None:
        return os.environ.get(self.accounts.instagram_business_account_id_env) or os.environ.get(
            "IG_BUSINESS_ACCOUNT_ID"
        )


def _merge_section(global_section: BaseModel, overrides: dict[str, Any]) -> dict[str, Any]:
    merged = global_section.model_dump()
    merged.update({k: v for k, v in overrides.items() if v is not None})
    return merged


def load_brand_config(brand_id: str, *, app_config: AppConfig | None = None) -> BrandConfig:
    app_config = app_config or load_app_config()
    path = CONFIG_DIR / "brands" / f"{brand_id}.toml"
    if not path.exists():
        raise FileNotFoundError(f"no brand config at {path}")
    raw = _load_toml(path)

    virality = _merge_section(app_config.virality, raw.get("virality", {}))
    publish = _merge_section(app_config.publish, raw.get("publish", {}))

    return BrandConfig.model_validate(
        {
            "brand": raw["brand"],
            "accounts": raw.get("accounts", {}),
            "posting_windows": raw.get("posting_windows", {}),
            "sources": raw.get("sources", {}),
            "virality": virality,
            "publish": publish,
        }
    )


def list_brand_ids() -> list[str]:
    brands_dir = CONFIG_DIR / "brands"
    return sorted(p.stem for p in brands_dir.glob("*.toml"))
