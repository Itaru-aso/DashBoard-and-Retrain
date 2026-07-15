"""アプリ設定（F1）。

`pydantic-settings` の `BaseSettings` で `.env` / 環境変数から設定を読み込む。
必須（`DATABASE_URL` / `INSPECTION_DATABASE_URL`）が未設定の場合は
インスタンス化時に `ValidationError` を送出する（fail-fast）。
各所からは単一の `settings` インスタンスを参照する。

変数の意味は `.kiro/steering/tech.md`「環境変数」を参照。
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """`.env` / 環境変数から読み込むアプリ設定。

    Attributes:
        DATABASE_URL: ver2 DB（自前・読み書き）の接続文字列（必須）。
        INSPECTION_DATABASE_URL: 業者検査 DB（外部・読み取り専用）の接続文字列（必須）。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- DB 接続（2エンジン: ver2=読み書き / 業者検査 DB=読み取り専用。必須） ---
    DATABASE_URL: str
    INSPECTION_DATABASE_URL: str

    # --- 実行モード ---
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # --- Basic 認証（単一共有クレデンシャル） ---
    ENABLE_BASIC_AUTH: bool = False
    BASIC_AUTH_USER: str = "shisui"
    BASIC_AUTH_PASS: str = ""

    # --- 再学習（training/ 連携） ---
    TRAINING_DATASET_PATH: str = ""
    TRAINING_PIPELINE_DIR: str = ""
    # training_service が subprocess 起動に使う（CWD＝TRAINING_DIR・ONNX 出力ルート＝TRAINING_MODEL_DIR）。
    TRAINING_DIR: str = ""
    TRAINING_MODEL_DIR: str = ""
    TRAINING_PYTHON: str = "python"
    # 未設定（既定 空）なら config.yaml 自身の imagenet_train_path を使う（上書きしない）。
    TRAINING_IMAGENET_PATH: str = ""
    # 未設定（既定 空）なら config.yaml 自身のパス一式（pretraining_dir 等）を使う。
    TRAINING_DATA_ROOT: str = ""

    # --- 日次集計ジョブ（アプリ内スケジューラ） ---
    AGG_RUN_TIME: str = "02:00"
    AGG_WINDOW_DAYS: int = 7

    # --- 逸脱判定ジョブ（アプリ内スケジューラ） ---
    BREACH_EVAL_ENABLED: bool = False
    BREACH_EVAL_TIME: str = "03:00"
    BREACH_EVAL_WINDOW_DAYS: int = 7


# 必須値は .env / 環境変数から供給されるため、mypy の call-arg 検査は無効化する。
settings = Settings()  # type: ignore[call-arg]
"""各モジュールが参照する単一の設定インスタンス（起動時に fail-fast）。"""
