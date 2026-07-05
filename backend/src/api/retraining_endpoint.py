"""モデル再学習 API・WebSocket（ver2・retraining）。

Basic 認証ゲート（`require_auth`）を通す。本タスク（task7）では WebSocket 進捗のみを提供し、
HTTP エンドポイント（起票・一覧・詳細・キャンセル・現行配信・手動配信）は task8 で追加する。

- WS `/api/retraining/jobs/{id}/progress`: `training_service.subscribe` を購読し、標準出力の各行を
  素通しで配信する。None センチネルで close（揮発）。切断・終了時は購読解除する。
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.services.training_service import get_training_service

# 注: HTTP エンドポイント（task8）の Basic 認証ゲートは各ルートに `require_auth` を付与する。
# WebSocket には HTTPBasic 依存を載せない（ハンドシェイクを壊すため。購読は接続後）。
router = APIRouter(prefix="/api/retraining", tags=["retraining"])


@router.websocket("/jobs/{job_id}/progress")
async def progress_ws(websocket: WebSocket, job_id: int) -> None:
    """進捗の WebSocket 配信（揮発）。各行を素通しし、None センチネルで close する。"""
    await websocket.accept()
    service = get_training_service()
    queue = service.subscribe(job_id)
    try:
        while True:
            line = await queue.get()
            if line is None:  # ストリーム終了
                await websocket.close()
                break
            await websocket.send_text(line)
    except WebSocketDisconnect:
        pass
    finally:
        service.unsubscribe(job_id, queue)
