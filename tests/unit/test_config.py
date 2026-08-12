from pathlib import Path

import pytest

from trendstealer import config


def test_load_app_config_defaults() -> None:
    app_config = config.load_app_config()
    assert app_config.virality.min_views == 100_000
    assert app_config.intelligence.model == "claude-opus-5"
    assert app_config.publish.mode == "dry_run"


def test_load_brand_config_acme_inherits_global_defaults() -> None:
    app_config = config.load_app_config()
    brand = config.load_brand_config("acme", app_config=app_config)
    assert brand.id == "acme"
    assert brand.virality.min_views == app_config.virality.min_views
    assert brand.publish.max_posts_per_day == app_config.publish.max_posts_per_day


def test_load_brand_config_missing_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        config.load_brand_config("does-not-exist")


def test_brand_config_overrides_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    brands_dir = tmp_path / "brands"
    brands_dir.mkdir()
    (brands_dir / "testbrand.toml").write_text(
        """
[brand]
id = "testbrand"
name = "Test Brand"
product_brief = "A test brand."

[virality]
min_views = 50000

[publish]
max_posts_per_day = 1
"""
    )
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    # AppConfig() gives the same defaults load_app_config() would produce
    # from a default app.toml, without touching the real file.
    real_app_config = config.AppConfig()

    brand = config.load_brand_config("testbrand", app_config=real_app_config)

    # overridden fields take the brand value
    assert brand.virality.min_views == 50000
    assert brand.publish.max_posts_per_day == 1

    # non-overridden fields still inherit the global default
    assert brand.virality.max_age_hours == real_app_config.virality.max_age_hours
    assert brand.publish.min_gap_minutes == real_app_config.publish.min_gap_minutes


def test_brand_secret_prefers_suffixed_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IG_ACCESS_TOKEN", "unsuffixed-token")
    monkeypatch.setenv("IG_ACCESS_TOKEN__ACME", "acme-token")
    assert config.brand_secret("IG_ACCESS_TOKEN", "acme") == "acme-token"


def test_brand_secret_falls_back_to_unsuffixed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IG_ACCESS_TOKEN__ACME", raising=False)
    monkeypatch.setenv("IG_ACCESS_TOKEN", "unsuffixed-token")
    assert config.brand_secret("IG_ACCESS_TOKEN", "acme") == "unsuffixed-token"


def test_list_brand_ids_includes_acme() -> None:
    assert "acme" in config.list_brand_ids()
