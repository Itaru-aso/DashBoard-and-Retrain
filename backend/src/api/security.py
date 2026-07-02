"""認証ゲート（F5）。

単一共有クレデンシャルの Basic 認証。ロール制御はしない（アクセスゲートのみ）。
`ENABLE_BASIC_AUTH=false` で無効化でき、その場合は資格なしで素通りする。
ルータ単位の依存として全 API に適用し、`/health` は除外する（main.py）。
資格比較は `secrets.compare_digest` による定数時間比較でタイミング攻撃を避ける。
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from src import config

# auto_error=False: 資格が無い場合でも 401 を即時に返さず None を渡す。
# （無効化時は素通りさせたいため、判定は require_auth 側で行う）
_basic = HTTPBasic(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="認証が必要です",
    headers={"WWW-Authenticate": "Basic"},
)


def require_auth(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)],
) -> None:
    """Basic 認証を検証する依存。

    `ENABLE_BASIC_AUTH=false` なら素通り。有効時は単一共有クレデンシャルと
    定数時間比較し、不一致・欠如なら 401 を送出する。

    Raises:
        HTTPException: 認証有効時に資格が欠如、または一致しない場合（401）。
    """
    if not config.settings.ENABLE_BASIC_AUTH:
        return
    if credentials is None:
        raise _UNAUTHORIZED

    user_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        config.settings.BASIC_AUTH_USER.encode("utf-8"),
    )
    pass_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        config.settings.BASIC_AUTH_PASS.encode("utf-8"),
    )
    if not (user_ok and pass_ok):
        raise _UNAUTHORIZED
