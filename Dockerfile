# syntax=docker/dockerfile:1
#
# ver2 バックエンド（API＋アプリ内スケジューラ＋再学習）の Dockerfile。
#
# GPU: 開発機（RTX A5000・Ampere／driver 537.42・CUDA 12.2まで対応）向けに cu121 で構築。
#   本番（Blackwell 対応・cu128）移行時は、ベースイメージ（nvidia/cuda:<12.8+>-...）と
#   下記 torch/torchvision・training/requirements.txt の cu121 指定を差し替える。
#
# backend（Python 3.11・FastAPI 等）と training/（Python 3.10・torch cu121 等）は
# 実行系が異なるため、同一イメージ内に別々の Python 環境（venv）を持つ。
#   - /venv          : backend 用（3.11）。CMD はこちらの uvicorn を使う。
#   - /training-venv : training/ 専用（3.10・training/requirements.txt）。
#     training_service が subprocess 起動時の TRAINING_PYTHON として使う。
#
# 非 root 実行・/health ヘルスチェック・uvicorn --workers 1（スケジューラ単一所有）。

FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

# Python 3.10（training用・Ubuntu22.04標準・PPA不要）を導入。
# libgl1/libglib2.0-0 は opencv-python（cv2）の実行時依存。
# build-essential 等は Python 3.11 をソースからビルドするための一時依存（後段で削除）。
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-venv \
        libgl1 libglib2.0-0 \
        build-essential zlib1g-dev libssl-dev libffi-dev libbz2-dev \
        libreadline-dev libsqlite3-dev liblzma-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python 3.11（backend用）はソースからビルドする。
# deadsnakes 等の PPA はキーサーバ通信がプロキシ環境でブロックされ得るため使わない。
# 公式 python:3.11-slim（Debian系）からのバイナリコピーは glibc バージョン不一致（Ubuntu22.04の
# glibcより新しい）で動かないため使わない。python.org のソース tarball（純 HTTPS）を使う。
RUN curl -fsSL https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz -o /tmp/python311.tgz \
    && tar -xzf /tmp/python311.tgz -C /tmp \
    && cd /tmp/Python-3.11.9 \
    && ./configure --prefix=/usr/local/python3.11 --enable-optimizations \
    && make -j"$(nproc)" \
    && make altinstall \
    && cd / && rm -rf /tmp/Python-3.11.9 /tmp/python311.tgz

# --- training（Python 3.10・cu121） ---
# training/ 本体は docker-compose のバインドマウントで供給する（config.yaml・pipline.py 等の
# 編集を再ビルド無しで即時反映するため）。ビルド時は venv 構築に requirements.txt のみ要る。
# backend より前に置く: backend/src の変更（頻繁）で、この重い torch インストールの
# キャッシュを毎回吹き飛ばさないようにする（Docker のレイヤーキャッシュは後続に伝播するため）。
WORKDIR /training
COPY training/requirements.txt ./
RUN python3.10 -m venv /training-venv \
    && /training-venv/bin/pip install --upgrade pip \
    && /training-venv/bin/pip install -r requirements.txt

# --- backend（Python 3.11） ---
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
RUN /usr/local/python3.11/bin/python3.11 -m venv /venv \
    && /venv/bin/pip install --upgrade pip \
    && /venv/bin/pip install .

# tzdata: scheduler.py の ZoneInfo("Asia/Tokyo") 解決に必要（nvidia/cuda ベースには既定で
# 入っていない）。既存の apt-get レイヤーとは別ステップにして、他レイヤーのキャッシュを保つ。
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# 非 root ユーザで実行する。/training はバインドマウントに置き換わるため build 時の
# chown は無意味（ホスト側の権限がそのまま見える）。/training-venv・/venv は起動後に
# 書き込みが発生しないため chown 不要（大量ファイルへの chown -R は非常に遅い）。
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# ver2 DB 疎通を含む /health を叩く（失敗＝unhealthy）。
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD /venv/bin/python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').getcode()==200 else 1)"

# 単一ワーカ必須（スケジューラ・再学習キューの単一所有）。
CMD ["/venv/bin/uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
