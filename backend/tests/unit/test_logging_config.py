"""ロギング `src.logging_config`（F8）の unit テスト。

- `configure_logging` がプレーン形式のハンドラを1つ設定する。
- 明示レベル／`settings.LOG_LEVEL` の双方がルートロガーへ反映される。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """settings の import 時 fail-fast を回避するため必須 env を用意する。"""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@localhost:5432/ver2")
    monkeypatch.setenv("INSPECTION_DATABASE_URL", "postgresql+psycopg2://r:r@localhost:5433/app_db")


@pytest.fixture(autouse=True)
def _restore_root_logger() -> Iterator[None]:
    """テストがルートロガーを汚さないよう、レベルとハンドラを復元する。"""
    root = logging.getLogger()
    old_level = root.level
    old_handlers = list(root.handlers)
    yield
    root.setLevel(old_level)
    root.handlers = old_handlers


@pytest.mark.unit
def test_configure_logging_sets_explicit_level() -> None:
    """明示レベルがルートロガーへ反映される。"""
    from src.logging_config import configure_logging

    configure_logging("DEBUG")

    assert logging.getLogger().level == logging.DEBUG


@pytest.mark.unit
def test_configure_logging_uses_settings_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """レベル未指定時は settings.LOG_LEVEL を用いる。"""
    from src import config
    from src.logging_config import configure_logging

    monkeypatch.setattr(config.settings, "LOG_LEVEL", "WARNING")
    configure_logging()

    assert logging.getLogger().level == logging.WARNING


@pytest.mark.unit
def test_configure_logging_installs_single_plain_handler() -> None:
    """プレーン形式のハンドラが1つだけ設定される（多重登録しない）。"""
    from src.logging_config import configure_logging

    configure_logging("INFO")
    configure_logging("INFO")

    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    fmt = handlers[0].formatter._fmt  # type: ignore[union-attr]
    assert "%(levelname)s" in fmt
    assert "%(message)s" in fmt
