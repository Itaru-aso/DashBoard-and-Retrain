# 閾値逸脱機能（breach evaluation）の動作検証 設計書

## 背景・目的

閾値逸脱機能（`BreachEvaluationService`）は、KPI（NG率・虚報率・見逃し率）が設定閾値を超えた場合に
保守タスクを自動起票する機能。関連する `threshold-management` / `task` / `dashboard` の各 spec は
すべて `[x]` 完了済みだが、以下2点を実際に確認したい。

1. **3指標（NG率・虚報率・見逃し率）それぞれで「逸脱→タスク作成」「非逸脱→タスク未作成」が正しく動くか**
2. **逸脱時にダッシュボードでどのように確認できるか**（閾値ラインの重ね描き・タスク一覧表示）

既存の `backend/tests/integration/test_breach_evaluation_service.py` は `ng_rate` を中心に
（逸脱／閾値と厳密一致／閾値なし／KPI NULL スキップ／冪等性／自動クローズ無し）を検証済みだが、
`false_alarm_rate`（虚報率）・`miss_rate`（見逃し率）の「逸脱→作成」「非逸脱→作成なし」の実値検証と、
ダッシュボード側の目視確認は未実施。

## スコープ

- **自動テスト追加**: `test_breach_evaluation_service.py` に虚報率・見逃し率の逸脱／非逸脱ケースを4件追加
- **手動E2E確認**: ローカル docker compose 環境で架空データを投入し、逸脱判定API実行→タスク確認→
  ダッシュボード目視確認を3指標分実施

**スコープ外**（今回は対象としない）:
- 日次集計機能（`agg` spec）の検証。`daily_metrics` へは直接データを投入し、`app_db`（`inspection-db` の
  データロード含む）からの集計パイプラインは通さない
- `breach_evaluation_service.py` / `metrics.py` 本体の変更（不具合が見つかった場合は報告のみ）

## 挿入データ内訳

共通の固定フルタプル: `color_no="TEST99"`, `size="00"`, `chain="TESTCHN"`, `tape=""`, `unit="1"`,
`monochro_count=10`, `annotated_count=5`（虚報率・見逃し率が NULL にならないよう常に 0 より大きい値を使う）。

`daily_metrics` テーブル自体はカメラ種別の列を持たず合計整数のみを保持するため、以下の「内訳」は
実際の列ではなく、**「全カメラ合算（`schema-spec-mapping.md` の規約）を意図的に踏まえたデータである」
ことを示す注記**として、テストコードのコメント・手動E2E手順書に記録する。

| 指標 | 状態 | 対象フィールド | 内訳（monochro由来 + color由来） | 率 | 閾値 |
|---|---|---|---|---|---|
| NG率（`ng_rate`） | 非逸脱 | `ng_count=0` | 0 + 0 | 0% | 5.0% |
| NG率（`ng_rate`） | 逸脱 | `ng_count=2` | monochro由来1 + color由来1 | 20% | 5.0% |
| 虚報率（`false_alarm_rate`） | 非逸脱 | `fp_num=0` | 0 + 0 | 0% | 5.0% |
| 虚報率（`false_alarm_rate`） | 逸脱 | `fp_num=1` | monochro由来0 + color由来1 | 10% | 5.0% |
| 見逃し率（`miss_rate`） | 非逸脱 | `miss_num=0` | 0 + 0 | 0% | 5.0% |
| 見逃し率（`miss_rate`） | 逸脱 | `miss_num=1` | monochro由来1 + color由来0 | 10% | 5.0% |

各テストでは**対象指標の閾値のみ**を設定する（他指標の閾値は作らない。「閾値なしは判定しない」仕様の確認も兼ねる）。

## 自動テスト追加

`backend/tests/integration/test_breach_evaluation_service.py` に既存の `_metric_row` / `_threshold`
ヘルパーを再利用し、以下4件を追加する（既存の `test_breach_creates_task` と同じ構造）。

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

## 手動E2E確認手順

### 前提

- ローカル `docker compose up -d --build` 済み。`backend` が `localhost:8000` で到達可能
- フロントエンド: `npm run dev`（Vite）でダッシュボード・タスク管理画面にアクセス可能
- 架空の色タプル: `color_no="TEST99", size="00", chain="TESTCHN", tape="", unit="1"`（実データと衝突しない値）

### 手順（NG率／虚報率／見逃し率のそれぞれで繰り返す）

1. コンテナの `today` を確認する。`POST /api/tasks/evaluate` は `end_date` を指定できず常に
   `date.today()` を評価基準にするため、投入するデータの `jst_date` をこれに合わせる必要がある。

   ```
   docker compose exec backend python -c "from datetime import date; print(date.today())"
   ```

2. 「挿入データ内訳」の表の**非逸脱データ**を `daily_metrics` に投入する（テストコードと同じ
   `DailyMetricsRepository.upsert_day` 経由。手順1で確認した日付を `<TODAY>` として使う）。

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
   "
   ```

3. 閾値管理画面（または `POST /api/thresholds`）で対象指標に閾値 5.0% を設定する
   （scope=`per_color`、フルタプルは手順2と同じ）。

4. `POST /api/tasks/evaluate`（`{"window_days": 1}`）を実行する。

5. タスク管理画面 または `GET /api/tasks?color_no=TEST99` で**タスクが無い**ことを確認する。

6. 「挿入データ内訳」の表の**逸脱データ**に更新する（`upsert_day` は delete→insert のため、
   同じ日付で手順2のコマンドを対象フィールドの値を変えて再実行するだけでよい）。

7. 再度 `POST /api/tasks/evaluate` を実行する。

8. `GET /api/tasks?color_no=TEST99` でタスクが1件作成され、`task_type`・`detected_value`（表の率）・
   `threshold_value=5.0` が期待通りであることを確認する。

9. ダッシュボード画面で `TEST99/00/TESTCHN` を選択し、対象指標のグラフに閾値ライン（5%）と
   本日のプロットが表示され、逸脱時は閾値ラインを超えていることを視覚的に確認する。
   タスク管理画面でも該当タスクが `OPEN` 状態で表示されることを確認する。

10. NG率・虚報率・見逃し率それぞれについて手順2〜9を繰り返す（各回、対象外の指標の閾値は作らない）。

### クリーンアップ

```
docker compose exec backend python -c "
from datetime import date
from src.database import SessionLocal
from src.repositories.daily_metrics_repository import DailyMetricsRepository

db = SessionLocal()
DailyMetricsRepository(db).upsert_day(date(<TODAY>), [])  # 空リスト = delete のみ
db.commit()
"
```

投入した閾値・作成されたタスクも、画面上の操作（閾値の無効化・タスク削除）で後片付けする。

## 検証基準

- **自動テスト**: 追加した4件を含め `pytest -m integration backend/tests/integration/test_breach_evaluation_service.py`
  が全件 pass する
- **手動E2E**: 3指標 × (非逸脱→タスク未作成 / 逸脱→タスク作成) の6パターンすべてで期待通りの結果になり、
  ダッシュボードのグラフ・閾値ライン・タスク一覧が目視で確認できる
