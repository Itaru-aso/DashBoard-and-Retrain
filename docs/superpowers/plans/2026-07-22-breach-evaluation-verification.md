# 閾値逸脱機能の動作検証 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 閾値逸脱機能（`BreachEvaluationService`）が NG率・虚報率・見逃し率の3指標それぞれで
「逸脱→タスク作成」「非逸脱→タスク未作成」を正しく行い、ダッシュボードで確認できることを検証する。

**Architecture:** 既存の `test_breach_evaluation_service.py` に虚報率・見逃し率の逸脱／非逸脱ケースを
4件追加（`ng_rate` の既存テストと同じヘルパー・構造を再利用）。加えてローカル docker compose 環境で
`daily_metrics` に架空データを直接投入し、`POST /api/tasks/evaluate` → タスク確認 → ダッシュボード目視
確認までの一連を3指標分手動で実施する。

**Tech Stack:** pytest（`db_session` fixture・testcontainers 経由の使い捨て Postgres）、FastAPI
（`/api/tasks/evaluate`・`/api/tasks`・`/api/dashboard/threshold-overlay`）、docker compose（ローカル）。

## Global Constraints

- 自動テストは既存の意図を変えない範囲の追加のみ。`backend/src/services/breach_evaluation_service.py` /
  `backend/src/services/metrics.py` 本体は変更しない
- 架空データは `daily_metrics`（ver2 DB）へ直接投入する。`app_db`（`inspection-db`）への書き込みは行わない
- 手動E2Eはローカル docker compose 環境限定
- 各テスト・各手動確認では**対象指標の閾値のみ**を設定する（他指標の閾値は作らない）
- 固定フルタプル（手動E2E）: `color_no="TEST99", size="00", chain="TESTCHN", tape="", unit="1"`,
  `monochro_count=10`, `annotated_count=5`
- 詳細な背景・データ内訳の根拠は `docs/superpowers/specs/2026-07-22-breach-evaluation-verification-design.md` を参照

---

### Task 1: 虚報率・見逃し率の逸脱／非逸脱テストを追加

**Files:**
- Modify: `backend/tests/integration/test_breach_evaluation_service.py`（既存の `test_no_task_when_value_equals_threshold` の直後、97行目付近に追加）
- Test: 同ファイル自身

**Interfaces:**
- Consumes: 同ファイル上部で既に定義済みの `_metric_row(day_repo: object, day: date, **over: object) -> None`（19-32行目）と
  `_threshold(db: Session, metric: str, value_pct: float) -> None`（35-48行目）、`D1 = date(2026, 7, 1)`、`COLOR` 辞書。
  `BreachEvaluationService(session).evaluate(window_days: int | None, *, end_date: date | None) -> None`。
  `TaskRepository(session).list() -> list[Task]`（`task_type`・`detected_value`・`threshold_value` 属性を持つ）。
- Produces: 何も後続タスクは消費しない（テスト専用）。

- [ ] **Step 1: 4件のテストを追記する**

`backend/tests/integration/test_breach_evaluation_service.py` の `test_no_task_when_value_equals_threshold`
（80行目で終わる）の直後に以下を追加する。

```python
@pytest.mark.integration
def test_false_alarm_rate_breach_creates_task(db_session: Session) -> None:
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.repositories.task_repository import TaskRepository
    from src.services.breach_evaluation_service import BreachEvaluationService

    # false_alarm_rate = 1/10 = 10%（内訳: monochro由来0 + color由来1。全カメラ合算の確認）
    _metric_row(DailyMetricsRepository(db_session), D1, fp_num=1, annotated_count=5)
    _threshold(db_session, "false_alarm_rate", 5.0)

    BreachEvaluationService(db_session).evaluate(window_days=1, end_date=D1)

    tasks = TaskRepository(db_session).list()
    assert len(tasks) == 1
    assert tasks[0].task_type == "false_alarm_rate"
    assert float(tasks[0].detected_value) == pytest.approx(10.0)
    assert float(tasks[0].threshold_value) == pytest.approx(5.0)


@pytest.mark.integration
def test_false_alarm_rate_no_breach_no_task(db_session: Session) -> None:
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.repositories.task_repository import TaskRepository
    from src.services.breach_evaluation_service import BreachEvaluationService

    _metric_row(DailyMetricsRepository(db_session), D1, fp_num=0, annotated_count=5)
    _threshold(db_session, "false_alarm_rate", 5.0)

    BreachEvaluationService(db_session).evaluate(window_days=1, end_date=D1)

    assert TaskRepository(db_session).list() == []


@pytest.mark.integration
def test_miss_rate_breach_creates_task(db_session: Session) -> None:
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.repositories.task_repository import TaskRepository
    from src.services.breach_evaluation_service import BreachEvaluationService

    # miss_rate = 1/10 = 10%（内訳: monochro由来1 + color由来0）
    _metric_row(DailyMetricsRepository(db_session), D1, miss_num=1, annotated_count=5)
    _threshold(db_session, "miss_rate", 5.0)

    BreachEvaluationService(db_session).evaluate(window_days=1, end_date=D1)

    tasks = TaskRepository(db_session).list()
    assert len(tasks) == 1
    assert tasks[0].task_type == "miss_rate"
    assert float(tasks[0].detected_value) == pytest.approx(10.0)
    assert float(tasks[0].threshold_value) == pytest.approx(5.0)


@pytest.mark.integration
def test_miss_rate_no_breach_no_task(db_session: Session) -> None:
    from src.repositories.daily_metrics_repository import DailyMetricsRepository
    from src.repositories.task_repository import TaskRepository
    from src.services.breach_evaluation_service import BreachEvaluationService

    _metric_row(DailyMetricsRepository(db_session), D1, miss_num=0, annotated_count=5)
    _threshold(db_session, "miss_rate", 5.0)

    BreachEvaluationService(db_session).evaluate(window_days=1, end_date=D1)

    assert TaskRepository(db_session).list() == []
```

- [ ] **Step 2: 追加した4件がまず実行できることを確認する**

Run（`backend/` ディレクトリで実行。Docker が起動していれば testcontainers が使い捨て Postgres を自動起動する）:
```
pytest -m integration tests/integration/test_breach_evaluation_service.py -v --no-cov
```
Expected: 追加した4件を含む計10件が **PASS**（`test_false_alarm_rate_breach_creates_task`・
`test_false_alarm_rate_no_breach_no_task`・`test_miss_rate_breach_creates_task`・
`test_miss_rate_no_breach_no_task` が新規PASSし、既存6件も引き続きPASS）。

- [ ] **Step 3: 型・静的チェック**

Run:
```
black backend/tests/integration/test_breach_evaluation_service.py
flake8 backend/tests/integration/test_breach_evaluation_service.py
```
Expected: 差分無し（black）／エラー無し（flake8）。

- [ ] **Step 4: コミット**

```bash
git add backend/tests/integration/test_breach_evaluation_service.py
git commit -m "test(task): 虚報率・見逃し率の逸脱/非逸脱ケースを追加

- ng_rateに続き、false_alarm_rate/miss_rateも逸脱→タスク作成/非逸脱→タスク未作成を実値で検証
- 内訳（monochro由来/color由来）は全カメラ合算仕様(schema-spec-mapping.md)を踏まえたもの"
```

---

### Task 2: 手動E2E確認（ローカル docker compose）

**Files:** なし（コード変更ではなく実行確認。コマンド・観測結果は本タスクのステップに直接記載する）

**Interfaces:**
- Consumes: `src.database.SessionLocal`、`src.repositories.daily_metrics_repository.DailyMetricsRepository`・
  `DailyMetricRow`（Task 1 と同じ import 経路）、`POST /api/tasks/evaluate`（body: `{"window_days": 1}`）、
  `GET /api/tasks?color_no=TEST99`、`GET /api/dashboard/threshold-overlay`。
- Produces: なし（検証結果をチャットで報告する。ファイル生成は無し）。

- [ ] **Step 1: 環境起動確認**

Run:
```
docker compose up -d --build
docker compose ps
```
Expected: `ver2-db`・`inspection-db`・`backend` が `healthy`/`running`。

- [ ] **Step 2: コンテナの `today` を確認する**

Run:
```
docker compose exec backend python -c "from datetime import date; print(date.today())"
```
出力された日付を以降 `<TODAY>`（`YYYY-MM-DD`）として使う。

- [ ] **Step 3: NG率 — 非逸脱データを投入して閾値を設定する**

Run（`<TODAY>` は Step 2 の値に置き換える。例 `date(2026, 7, 22)`）:
```
docker compose exec backend python -c "
from datetime import date
from src.database import SessionLocal
from src.repositories.daily_metrics_repository import DailyMetricsRepository, DailyMetricRow

db = SessionLocal()
DailyMetricsRepository(db).upsert_day(date(<TODAY>), [DailyMetricRow(
    color_no='TEST99', size='00', chain='TESTCHN', tape='', unit='1',
    monochro_count=10, ng_count=0, fp_num=0, miss_num=0, annotated_count=5,
)])
db.commit()
print('seeded: ng_rate no-breach (0%)')
"
```

閾値を設定する（`ThresholdService` 経由。UI の閾値管理画面からでもよい）:
```
docker compose exec backend python -c "
from datetime import datetime, timezone
from src.database import SessionLocal
from src.schemas.threshold import ThresholdCreate
from src.services.threshold_service import ThresholdService

db = SessionLocal()
ThresholdService(db).create(ThresholdCreate(
    metric='ng_rate', scope='per_color',
    color_no='TEST99', size='00', chain='TESTCHN', tape='',
    value_pct=5.0, valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc), valid_to=None,
))
db.commit()
print('threshold set: ng_rate 5.0%')
"
```

- [ ] **Step 4: 逸脱判定を実行し、タスクが無いことを確認する**

Run:
```
curl -s -X POST http://localhost:8000/api/tasks/evaluate -H "Content-Type: application/json" -d "{\"window_days\":1}"
curl -s "http://localhost:8000/api/tasks?color_no=TEST99"
```
Expected: 1つ目は `{"status":"completed"}`。2つ目は `[]`（NG率0% ≤ 閾値5% のためタスク無し）。

- [ ] **Step 5: NG率 — 逸脱データに更新し、タスクが作成されることを確認する**

Run（Step 3 の同じコマンドで `ng_count=0` を `ng_count=2` に変更し再実行。`upsert_day` は
delete→insert のため同日付を指定するだけで上書きされる）:
```
docker compose exec backend python -c "
from datetime import date
from src.database import SessionLocal
from src.repositories.daily_metrics_repository import DailyMetricsRepository, DailyMetricRow

db = SessionLocal()
DailyMetricsRepository(db).upsert_day(date(<TODAY>), [DailyMetricRow(
    color_no='TEST99', size='00', chain='TESTCHN', tape='', unit='1',
    monochro_count=10, ng_count=2, fp_num=0, miss_num=0, annotated_count=5,
)])
db.commit()
print('seeded: ng_rate breach (20%, monochro由来1+color由来1)')
"
curl -s -X POST http://localhost:8000/api/tasks/evaluate -H "Content-Type: application/json" -d "{\"window_days\":1}"
curl -s "http://localhost:8000/api/tasks?color_no=TEST99"
```
Expected: `GET /api/tasks` が1件返り、`task_type=="ng_rate"`, `detected_value≈20.0`, `threshold_value==5.0`,
`status=="OPEN"`。

- [ ] **Step 6: ダッシュボードで NG率の逸脱を目視確認する**

Run:
```
curl -s "http://localhost:8000/api/dashboard/threshold-overlay?metric=ng_rate&color_no=TEST99&size=00&chain=TESTCHN&tape=&from=<TODAY>&to=<TODAY>"
```
Expected: `<TODAY>` の行で算出値が閾値(5.0)を上回っている。

続けて、Vite dev server（`npm run dev`）でフロントを起動し、ダッシュボード画面で色フィルタに
`TEST99/00/TESTCHN` を指定し、NG率グラフの本日プロットが閾値ライン（5%）を超えて表示されることと、
タスク管理画面に `TEST99` のタスクが `OPEN` で1件表示されることを目視で確認する。
確認できたら次のステップに進む前に、観測結果（グラフ・タスク一覧の見え方）をチャットで報告する。

- [ ] **Step 7: 虚報率 — Step 3〜6 と同じ手順を `false_alarm_rate` で繰り返す**

Step 3〜6 の各コマンドで以下を変更して実行する:
- 非逸脱: `fp_num=0`（他は Step 3 と同じ）。閾値は `metric='false_alarm_rate', value_pct=5.0`
- 逸脱: `fp_num=1`（内訳: monochro由来0 + color由来1）→ `false_alarm_rate=10%`
- 確認項目: `task_type=="false_alarm_rate"`, `detected_value≈10.0`

Expected: 非逸脱時はタスク無し、逸脱時はタスク1件（`false_alarm_rate`, `detected_value≈10.0`,
`threshold_value==5.0`）。ダッシュボードの虚報率グラフでも同様に確認する。

- [ ] **Step 8: 見逃し率 — Step 3〜6 と同じ手順を `miss_rate` で繰り返す**

Step 3〜6 の各コマンドで以下を変更して実行する:
- 非逸脱: `miss_num=0`。閾値は `metric='miss_rate', value_pct=5.0`
- 逸脱: `miss_num=1`（内訳: monochro由来1 + color由来0）→ `miss_rate=10%`
- 確認項目: `task_type=="miss_rate"`, `detected_value≈10.0`

Expected: 非逸脱時はタスク無し、逸脱時はタスク1件（`miss_rate`, `detected_value≈10.0`,
`threshold_value==5.0`）。ダッシュボードの見逃し率グラフでも同様に確認する。

- [ ] **Step 9: クリーンアップ**

Run:
```
docker compose exec backend python -c "
from datetime import date
from src.database import SessionLocal
from src.repositories.daily_metrics_repository import DailyMetricsRepository

db = SessionLocal()
DailyMetricsRepository(db).upsert_day(date(<TODAY>), [])
db.commit()
print('cleaned up daily_metrics for <TODAY>')
"
```
続けて、タスク管理画面・閾値管理画面から `TEST99` 関連の閾値（無効化 or 削除）・タスク（削除）を
後片付けする。

Expected: `curl -s "http://localhost:8000/api/tasks?color_no=TEST99"` が `[]` に戻る（タスクを画面から
削除した場合）。`daily_metrics` に `TEST99` 行が残っていない。

- [ ] **Step 10: 結果を報告する**

3指標 × (非逸脱/逸脱) の6パターン全てについて、期待通りだったか／ズレがあったかをまとめてチャットで
報告する（Step 6・7・8 で確認したダッシュボードの見え方も含める）。ズレがあった場合は
`breach_evaluation_service.py` 等の本体コードは変更せず、まず報告する。
