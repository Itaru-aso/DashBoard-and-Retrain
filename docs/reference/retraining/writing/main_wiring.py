"""配線の実コード例（main.py / dependencies.py）。

配置先: 下記の通り backend/src/main.py・backend/src/dependencies.py へ取り込む。
本ファイルは2モジュール分をまとめた参照（実際は2ファイルに分ける）。import パスはプロジェクトに合わせる。
"""
from __future__ import annotations

# =====================================================================
# backend/src/dependencies.py
# =====================================================================
from fastapi import Depends
from sqlalchemy.orm import Session

from database import get_db
from repositories.color_master_repository import ColorMasterRepository
from services.deployment_service import DeploymentService

# deployment_service はシングルトン（main.py の lifespan で生成して代入）
_deployment_service: DeploymentService | None = None


def set_deployment_service(svc: DeploymentService) -> None:
    global _deployment_service
    _deployment_service = svc


def get_deployment_service() -> DeploymentService:
    if _deployment_service is None:
        raise RuntimeError("DeploymentService が未初期化です（lifespan で生成してください）")
    return _deployment_service


def get_color_master_repo(db: Session = Depends(get_db)) -> ColorMasterRepository:
    # ColorMasterRepository は exists_by_tuple(color_no,size,chain,tape)->bool を備える想定（色マスター spec）
    return ColorMasterRepository(db)


# =====================================================================
# backend/src/main.py
# =====================================================================
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config import settings
from database import SessionLocal
from repositories.edge_pc_repository import EdgePcRepository
from services.deployment_service import DeploymentConfig, DeploymentService, make_auto_deploy_hook
from services.training_service import (
    TrainingConfig,
    get_training_service,
    init_training_service,
)
import dependencies

# 各機能のルーター（存在するものから登録）
from api import retraining_endpoint
# from api import dashboard_endpoint, task_endpoint, color_endpoint, threshold_endpoint
# from api import edge_endpoint, aggregation_endpoint


def _session_factory() -> SessionLocal:  # type: ignore[valid-type]
    """with/close 可能な ver2 Session を返す（training/deployment service 用）。"""
    return SessionLocal()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1) deployment_service（自前 ftplib・有効エッジPCの model_port へ配信）
    deployment_service = DeploymentService(
        session_factory=_session_factory,
        edge_pc_repo_factory=lambda db: EdgePcRepository(db),  # find_enabled() を備える想定
        config=DeploymentConfig(),
    )
    dependencies.set_deployment_service(deployment_service)

    # 2) training_service（キュー・subprocess・進捗）。COMPLETED 時に v1 自動配信
    training_service = init_training_service(
        session_factory=_session_factory,
        config=TrainingConfig(
            training_dir=settings.training_dir,
            model_dir=settings.training_model_dir,
            python_executable=settings.training_python,
        ),
        on_completed=make_auto_deploy_hook(deployment_service),
    )
    await training_service.start()  # 復旧（消えた RUNNING→FAILED・QUEUED 再投入）＋ワーカ起動

    # 3) 他機能の日次スケジューラ（集計→逸脱判定→昇格）も同 lifespan で開始する
    #    （基盤整備／日次集計基盤／保守タスク／色ライフサイクルの spec を参照）
    try:
        yield
    finally:
        await get_training_service().stop()  # 実行中はプロセスグループごと停止
        # スケジューラ等の停止もここで


def create_app() -> FastAPI:
    app = FastAPI(title="shisui app_ver2", lifespan=lifespan)

    # --- ルーター登録 ---
    app.include_router(retraining_endpoint.router)
    # app.include_router(dashboard_endpoint.router)
    # app.include_router(task_endpoint.router)
    # app.include_router(color_endpoint.router)
    # app.include_router(threshold_endpoint.router)
    # app.include_router(edge_endpoint.router)
    # app.include_router(aggregation_endpoint.router)

    # ヘルスチェック（任意）
    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()

# 起動: uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1
#       （単一ワーカ必須＝再学習キュー/スケジューラの単一所有のため）
