"""ver2 ORM モデル（自前テーブル・Alembic 管理）と、業者検査 DB の読み取り専用モデル。

- ver2 テーブル: `src/models/<name>.py`（`Base` に載せ Alembic 管理）。
- 業者検査 DB（app_db・読み取り専用）: `src/models/external/`（`ExternalBase`・Alembic 対象外）。
"""

from __future__ import annotations
