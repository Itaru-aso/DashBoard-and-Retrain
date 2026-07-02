"""ロギング設定（F8）。

標準 `logging` を**プレーン形式**で初期化する。レベルは引数、未指定時は
`settings.LOG_LEVEL` に連動する。各モジュールは `logging.getLogger(__name__)` を使う。
"""

from __future__ import annotations

import logging

from src import config

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str | None = None) -> None:
    """ルートロガーをプレーン形式で初期化する。

    Args:
        level: ログレベル文字列（例: "INFO"）。None なら `settings.LOG_LEVEL` を用いる。
    """
    resolved = (level or config.settings.LOG_LEVEL).upper()
    root = logging.getLogger()
    root.setLevel(resolved)

    # 多重登録を避けるため既存ハンドラを除去してから1つだけ設定する。
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(handler)
