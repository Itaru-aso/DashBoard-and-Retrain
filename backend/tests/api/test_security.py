"""認証ゲート `src.api.security`（F5）の api テスト。

- 認証なし → 401（有効時）。
- 正しい単一共有クレデンシャル → 通過。
- 誤った資格 → 401。
- `ENABLE_BASIC_AUTH=false` → 素通り（資格不要）。

本タスクでは本物の app（task10）に依存せず、`require_auth` を載せた最小アプリで検証する。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> Iterator[TestClient]:
    """`require_auth` を適用した保護ルートを持つ最小アプリの TestClient。"""
    from src.api.security import require_auth

    app = FastAPI()

    @app.get("/protected", dependencies=[Depends(require_auth)])
    def _protected() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """単一共有クレデンシャルで Basic 認証を有効化する。"""
    from src import config

    monkeypatch.setattr(config.settings, "ENABLE_BASIC_AUTH", True)
    monkeypatch.setattr(config.settings, "BASIC_AUTH_USER", "shisui")
    monkeypatch.setattr(config.settings, "BASIC_AUTH_PASS", "secret")


@pytest.mark.api
def test_missing_credentials_returns_401(client: TestClient, auth_enabled: None) -> None:
    """有効時、資格なしは 401。"""
    res = client.get("/protected")
    assert res.status_code == 401


@pytest.mark.api
def test_correct_credentials_pass(client: TestClient, auth_enabled: None) -> None:
    """正しい単一共有クレデンシャルは通過。"""
    res = client.get("/protected", auth=("shisui", "secret"))
    assert res.status_code == 200
    assert res.json() == {"ok": True}


@pytest.mark.api
def test_wrong_credentials_returns_401(client: TestClient, auth_enabled: None) -> None:
    """誤った資格は 401。"""
    res = client.get("/protected", auth=("shisui", "wrong"))
    assert res.status_code == 401


@pytest.mark.api
def test_disabled_auth_passes_without_credentials(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ENABLE_BASIC_AUTH=false のときは資格なしで素通り。"""
    from src import config

    monkeypatch.setattr(config.settings, "ENABLE_BASIC_AUTH", False)
    res = client.get("/protected")
    assert res.status_code == 200
