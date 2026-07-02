"""アプリ骨格（F7）。

- `create_app` で FastAPI を生成する（本番 SPA 配信の分岐をテスト可能にするファクトリ）。
- lifespan でアプリ内スケジューラを起動 / 停止する（単一所有・`uvicorn --workers 1`）。
- `/health`: ver2 DB 疎通＝**必須**（失敗で 503・unhealthy）、業者検査 DB 疎通＝**参考**
  （失敗しても致命にせず結果に併記。F2.3 と整合）。
- `ENVIRONMENT=production`: フロント `dist/` を配信し、未知パスは index.html へ
  SPA フォールバックする。開発は Vite devserver＋`/api` プロキシ（本アプリは配信しない）。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from src import config, database
from src.logging_config import configure_logging
from src.scheduler import create_scheduler

logger = logging.getLogger(__name__)

# フロントのビルド成果物（本番配信）。repo_root/frontend/dist。
FRONTEND_DIST: Path = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def check_ver2_db() -> bool:
    """ver2 DB へ疎通できるか（SELECT 1）。失敗は False。"""
    try:
        with database.ver2_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("ver2 DB の疎通確認に失敗しました", exc_info=True)
        return False


def check_inspection_db() -> bool:
    """業者検査 DB へ疎通できるか（SELECT 1）。失敗は False（参考・非致命）。"""
    try:
        with database.inspection_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("業者検査 DB へ到達できません（参考のため致命にしない）", exc_info=True)
        return False


def health(
    ver2_ok: bool = Depends(check_ver2_db),
    inspection_ok: bool = Depends(check_inspection_db),
) -> JSONResponse:
    """ヘルスチェック。ver2 は必須、業者は参考（併記）。"""
    body = {
        "status": "healthy" if ver2_ok else "unhealthy",
        "ver2_db": "ok" if ver2_ok else "error",
        "inspection_db": "ok" if inspection_ok else "unavailable",
    }
    status_code = 200 if ver2_ok else 503
    return JSONResponse(body, status_code=status_code)


class _SPAStaticFiles(StaticFiles):
    """SPA 用の静的配信。存在しないパスは index.html を返す（クライアントルーティング）。"""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def _mount_frontend(app: FastAPI) -> None:
    """本番時のみ、フロント `dist/` を SPA フォールバック付きで配信する。"""
    if config.settings.ENVIRONMENT != "production" or not FRONTEND_DIST.is_dir():
        return
    app.mount("/", _SPAStaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """起動時にスケジューラを開始し、終了時に停止する（単一所有）。"""
    configure_logging()
    scheduler = create_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    """FastAPI アプリを生成する（ルーター登録の集約点）。"""
    app = FastAPI(title="shisui app_ver2", lifespan=lifespan)

    # /health は認証除外（アクセスゲートは各機能ルータに require_auth を適用する）。
    app.add_api_route("/health", health, methods=["GET"], tags=["health"])

    # 各機能ルータの登録。
    from src.api.aggregation_endpoint import router as aggregation_router

    app.include_router(aggregation_router)

    # SPA 配信は最後にマウント（API ルートを優先させる）。
    _mount_frontend(app)
    return app


app = create_app()
