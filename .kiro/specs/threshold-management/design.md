# 閾値管理 — Design

> spec: `閾値管理 (threshold-management)` ／ 配置想定: `.kiro/specs/threshold-management/design.md`
> 上流: `requirements.md`（R1–R6）／ steering: `product.md`・`tech.md`・`structure.md`

## 概要・方針 (Overview)

閾値を単一テーブルで管理し、3層（API → Service → Repository → Model/DB）に沿って実装する。
中核は **有効閾値解決**（メトリクス・色・時点 → 有効閾値を一意に返す）。
「同一(メトリクス, スコープ)で有効期間が重複しない」を **DB の排他制約**で保証し、
解決クエリが常に 0 件または 1 件を返すようにする（R3.5 の不変条件をアプリ任せにしない）。

## レイヤ配置 (Placement — `structure.md` 準拠)

- `src/models/threshold.py` … ORM モデル `Threshold`
- `src/repositories/threshold_repository.py` … `ThresholdRepository`（CRUD・解決クエリ）
- `src/services/threshold_service.py` … `ThresholdService`（検証・解決・supersede）
- `src/schemas/threshold.py` … Pydantic 入出力スキーマ
- `src/api/threshold_endpoint.py` … FastAPI ルーター（`main.py` に登録）
- `alembic/versions/<rev>_create_threshold.py` … 補填マイグレーション

## データモデル (Data Model)

テーブル `threshold`（補填テーブル。識別子は英語、コメントは日本語）。

| カラム | 型 | 説明 |
|---|---|---|
| `id` | bigserial PK | |
| `metric` | text (enum) | `ng_rate` / `false_alarm_rate` / `miss_rate`（NG率／虚報率／見逃し率） |
| `scope` | text (enum) | `global` / `per_color` |
| `color_no` | text NULL | `per_color` 時のみ設定 |
| `size` | text NULL | `per_color` 時のみ設定 |
| `chain` | text NULL | `per_color` 時のみ設定 |
| `tape` | text NULL | `per_color` 時のみ設定（**空文字 `''` 許容**。基本空白） |
| `value_pct` | numeric(5,2) | 閾値（%・0–100・上限値） |
| `valid_from` | timestamptz NOT NULL | 有効開始（含む） |
| `valid_to` | timestamptz NULL | 有効終了（**含まない**。NULL = 無期限） |
| `created_at` | timestamptz NOT NULL | |
| `updated_at` | timestamptz NOT NULL | |

時刻はすべて **timestamptz（UTC 保持・表示時にローカル変換）**。
有効期間は **半開区間 `[valid_from, valid_to)`** とする。

### 制約 (Constraints)

- `CHECK value_pct BETWEEN 0 AND 100`（R1.5）
- `CHECK valid_to IS NULL OR valid_to > valid_from`（R1.3）
- `metric` / `scope` は許可値のみ（enum or CHECK）（R1.4）
- **スコープ整合**: `CHECK` で
  `(scope='per_color' AND color_no IS NOT NULL AND size IS NOT NULL AND chain IS NOT NULL AND tape IS NOT NULL)`
  または `(scope='global' AND color_no IS NULL AND size IS NULL AND chain IS NULL AND tape IS NULL)`。
- **期間の非重複（R1.2 / R3.5 の核）**: `btree_gist` 拡張を使った**部分排他制約**を2本。
  - per_color 用:
    `EXCLUDE USING gist (metric WITH =, color_no WITH =, size WITH =, chain WITH =, tape WITH =, tstzrange(valid_from, valid_to) WITH &&) WHERE (scope = 'per_color')`
  - global 用:
    `EXCLUDE USING gist (metric WITH =, tstzrange(valid_from, valid_to) WITH &&) WHERE (scope = 'global')`
  - ※ グローバル行は色カラムが NULL で、NULL 同士は排他等価判定に乗らないため、
    per_color と global を **分けて**部分制約にするのが必須（同一制約にまとめると global の重複を取りこぼす）。
- マイグレーション冒頭で `CREATE EXTENSION IF NOT EXISTS btree_gist;`。

索引: 解決クエリ用に `(metric, scope, color_no, size, chain, tape)` ＋ 期間。閾値は小規模のため
パーティション不要（`tech.md`）。

## 有効閾値解決ロジック (Resolution — R3 / R4)

`ThresholdService.resolve_effective(metric, color, at) -> Threshold | None`

```
def resolve_effective(metric, color, at):
    # color = (color_no, size, chain, tape) フルタプル
    t = repo.find_active(metric, scope='per_color', color=color, at=at)
    if t: return t                      # R3.1 / R3.3（色別優先）
    g = repo.find_active(metric, scope='global', color=None, at=at)
    if g: return g                      # R3.2
    return None                         # R3.4（閾値なし＝下流で判定・重ね描きしない）
```

`find_active` の有効判定: `valid_from <= at AND (valid_to IS NULL OR at < valid_to)`（半開区間）。
排他制約により各 `find_active` は高々1件（R3.5）。

## API 設計 (Endpoints)

- `POST /api/thresholds` … 作成（R1）。重複は 409、検証失敗は 422。
- `GET  /api/thresholds` … 一覧。filter: `metric` / `scope` / 色 / 時点・期間（R5）。ページングは任意（小規模）。
- `GET  /api/thresholds/{id}` … 個別参照。
- `PATCH /api/thresholds/{id}` … 更新・無効化（R2）。再検証は作成と同じ。
- `GET  /api/thresholds/effective` … 有効閾値解決（query: `metric, color_no, size, chain, tape, at`）。
  ダッシュボードの重ね描き用（R4）。タスク生成は `ThresholdService.resolve_effective` を内部利用（R4）。

DB セッションは `get_db`（リクエスト単位、正常 commit／例外 rollback）。

## 変更・履歴の扱い (Change & History — R2)

- **運用上の閾値変更**＝現行レコードの `valid_to` を変更時刻に設定（close）し、
  `valid_from`＝同時刻・新 `value_pct` で**新レコードを作成**（supersede）。過去レコードは保持（R2.1）。
- **未有効化レコードの誤り訂正**（`valid_from` が未来等、一度も有効になっていないもの）は in-place PATCH 可。
- **無効化**＝ `valid_to` を設定。以降は `find_active` に乗らない（R2.3）。
- 物理 DELETE は原則行わない（履歴保持）。許容するのは未有効化レコードのみ。

## バリデーション・エラー処理 (Validation & Errors)

- Pydantic スキーマで: メトリクス enum・値域(0–100)・期間逆転・スコープ整合（per_color なら色4項目必須）→ 422。
- 期間重複（排他制約違反）→ Service/Repository で捕捉し **409 Conflict**。
  ユーザ向けには事前チェックで分かりやすいエラーも返すが、**最終保証は DB 制約**。

## テスト設計 (Testing — 検証ゲートにマップ)

各 AC をテスト1本に対応させる（`tech.md` 検証ゲート: pytest cov≥80・mypy・flake8・black）。

- **unit**（schema）: メトリクス enum / 値域 / 期間逆転 / スコープ整合の検証。
- **integration**（DB 使用、conftest のトランザクション ROLLBACK fixture）:
  - R1: 作成成功／期間重複の拒否（409）／期間逆転拒否／値域拒否／メトリクス不正拒否。
  - R2: supersede で過去レコードが残る／無効化後は解決に乗らない／未有効化レコードの in-place 訂正。
  - R3: 色別優先／グローバル fallback／両方有効→色別／両方なし→None／高々1件。
  - R3 境界: `valid_from == at` は有効、`valid_to == at` は無効（半開）。
  - R3 色一致: フルタプル一致のみヒット（`color_no` 同一でも `size` 違いはヒットしない）。
- **api**（TestClient）: 各エンドポイントのステータス・レスポンス、`effective` の解決結果、Basic 認証ゲート通過。

## 依存・前提 (Dependencies)

- **棚卸し依存**: 業者 DB に閾値テーブルが「無い」前提で補填する。棚卸しで既存テーブルがあれば実スキーマに追従し本設計を調整（`structure.md`）。
- **命名の照合（棚卸し時）**: テーブル名 `threshold`・メトリクス enum 値（`ng_rate`/`false_alarm_rate`/`miss_rate`）が
  業者 DB／ver1 の命名規約と整合するか確認し、必要なら合わせる。
- `btree_gist` 拡張が利用可能であること。
- 解決の入力にはフルタプル（`tape` 含む）が必要。ダッシュボード／タスク生成は4項目を渡す。

> 設計判断は確定: 期間非重複は **DB 排他制約（btree_gist）で保証**（承認）、変更は **supersede モデル**（承認）。
