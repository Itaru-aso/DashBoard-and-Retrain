"""設定 `src.config`（F1）の unit テスト。

- 必須 env（DATABASE_URL / INSPECTION_DATABASE_URL）が未設定なら fail-fast（例外）。
- env から値を読み込める（既定値も含む）。
- モジュールは単一の `settings` インスタンスを公開する。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """必須 env を用意し、モジュール import 時の fail-fast を回避する。"""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@localhost:5432/ver2")
    monkeypatch.setenv("INSPECTION_DATABASE_URL", "postgresql+psycopg2://r:r@localhost:5433/app_db")


@pytest.mark.unit
def test_missing_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """必須 env 欠如でインスタンス化が失敗する（fail-fast）。"""
    from src.config import Settings

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("INSPECTION_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.unit
def test_loads_values_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """env から値を読み込み、未設定項目は既定値になる。"""
    from src.config import Settings

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@h:5432/ver2")
    monkeypatch.setenv("INSPECTION_DATABASE_URL", "postgresql+psycopg2://r:r@h:5433/app_db")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("AGG_WINDOW_DAYS", "14")
    # 既定値を検証する項目は env をクリアする（CI ジョブ env の ENVIRONMENT=test 等が漏れ込むのを防ぐ）
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("ENABLE_BASIC_AUTH", raising=False)
    monkeypatch.delenv("BREACH_EVAL_WINDOW_DAYS", raising=False)

    s = Settings(_env_file=None)

    assert s.DATABASE_URL.endswith("/ver2")
    assert s.INSPECTION_DATABASE_URL.endswith("/app_db")
    assert s.DEBUG is True
    assert s.LOG_LEVEL == "DEBUG"
    assert s.AGG_WINDOW_DAYS == 14
    # 未設定は既定値
    assert s.ENVIRONMENT == "development"
    assert s.ENABLE_BASIC_AUTH is False
    assert s.BREACH_EVAL_WINDOW_DAYS == 7


@pytest.mark.unit
def test_module_exposes_single_settings_instance() -> None:
    """モジュールは単一の `settings` インスタンスを公開する。"""
    import src.config as config

    assert isinstance(config.settings, config.Settings)
    assert config.settings.DATABASE_URL
