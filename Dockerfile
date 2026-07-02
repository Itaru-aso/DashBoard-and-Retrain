# syntax=docker/dockerfile:1
#
# ver2 バックエンド（API＋アプリ内スケジューラ＋再学習）の Dockerfile。
#
# NOTE: ベースイメージと GPU/CUDA(PyTorch cu128 系・Blackwell 対応) は後日確定する
#   （tech.md）。本タスクはランタイム骨組みのため python:3.11-slim を用い、torch/CUDA は
#   含めない。GPU 確定後に base を nvidia/cuda:<12.8+>-runtime-ubuntu22.04 + Python3.11 +
#   PyTorch(cu128) へ差し替え、docker-compose の deploy.resources で GPU を渡す。
#
# 非 root 実行・/health ヘルスチェック・uvicorn --workers 1（スケジューラ単一所有）。

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 依存＋アプリ（src パッケージ）を pip でインストールする。
COPY backend/pyproject.toml ./
COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
RUN pip install --upgrade pip && pip install .

# 非 root ユーザで実行する。
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# ver2 DB 疎通を含む /health を叩く（失敗＝unhealthy）。
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').getcode()==200 else 1)"

# 単一ワーカ必須（スケジューラ・再学習キューの単一所有）。
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
