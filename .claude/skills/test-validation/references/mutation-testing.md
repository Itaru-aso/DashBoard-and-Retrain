# Mutation Testing

コードにわざとバグ（mutant）を仕込み、テストがそれを落とせるかを測る。カバレッジ数値では絶対に見えない「テストが回帰を検出できるか」を機械的に判定する手段。

## 用語

- **mutant**: コードに1箇所だけ加えた変異（`+`→`-`、`>`→`>=`、`and`→`or`、`return x`→`return None`、条件反転、定数変更 など）
- **killed**: その変異でテストが落ちた = テストが挙動変化を検出できた（良い）
- **survived**: 変異してもテストが通った = テストが検出できない空洞（要補強）
- **mutation score**: `killed / (killed + survived)`。◎層で高いほど良い

**survived mutants のリストが、そのまま「弱いテストの具体的な証拠」になる。**

## 第一選択: 同梱ランナー `scripts/mutation_runner.py`（依存ゼロ）

外部ツールを入れずに、その場で mutation を掛けられる stdlib のみのランナー。DB 非依存で速く回る対象
（純粋ロジック・Validator・utils・切り出した◎ロジック）に使う。mutmut の要インストール・Windows での
不安定さ・`.coverage` ロックを回避でき、この環境では**まず確実に完走する**のが利点。

```bash
# mutation: 1 ソースへ変異を掛け survived を列挙（project-dir は pytest を回す位置）
python <skill>/scripts/mutation_runner.py mutate \
    --source src/services/metrics.py --tests tests/unit/test_metrics.py --project-dir backend

# branch coverage: term-missing（Windows の .coverage ロックを一時ファイルへ退避）
python <skill>/scripts/mutation_runner.py cov \
    --module src.services.metrics --tests tests/unit/test_metrics.py --project-dir backend
```

変異の種類（1 候補ノード = 1 変異）: 比較演算子（`<`↔`<=`, `==`↔`!=`, `is`↔`is not` ほか）、二項演算
（`+`↔`-`, `*`↔`/` ほか）、論理演算（`and`↔`or`）、真偽定数、整数/浮動小数（`n`→`n+1`）、
`return <expr>`→`return None`。キーワード引数の定数（`frozen=True`・`extra="ignore"` 等）は等価変異に
なりやすいため除外済み。

読み方:
- `killed` = 変異でテストが落ちた（良い）／`survived` = 落ちない（回帰を検出できない＝空洞の証拠）。
- `score = killed / 実行数`。survived が 0 なら、その対象のテストは変異を検出できている＝健全。無理に欠落を作らない。
- survived の各行に **行番号＋変異内容＋該当コード**が出るので、それを検出できる境界/異常系テストを足す。

制約と使いどころ:
- **対象は DB 非依存で速いテストに限る**（1 変異ごとに pytest を1回起動するため、統合テストでは遅すぎる）。
  DB が絡む◎ロジックは判定部を純関数へ切り出してから掛ける（例 `metrics.compute_rates`）。
- ini の `addopts`（`--cov ... --cov-fail-under`）はランナーが自動で無効化する（カバレッジゲートで
  誤判定しないため）。
- 1 ファイル 1 対象。複数ファイルへ一括で掛けない（時間管理と復元の確実性のため）。
- 中断（SIGTERM/SIGINT）されてもソースは自動復元するが、大量対象を一度に流さないこと。
- **分離して実行する**: ランナーは対象ソースを一瞬だけ書き換えて復元する。同じソースを**別プロセスが同時に読む/テストする**状況（並行評価など）では、その一瞬の変異体を拾って非決定な失敗が起きる。共有ツリー上で並行作業がある時は、リポジトリのコピー上で回すか、対象ファイルへの同時アクセスを避ける。
- **score は下限であって健全の証明ではない**: 演算子・定数変異は「同型出力の取り違え（代入入替）」「フィクスチャの値衝突でマスクされる欠落」「同値クラスの抜け」を構造的に生成できない。survived 0 でも `review-checklist.md` の該当項目（相異なる値・同値クラス・配線）を必ず当てること。
- 大規模・CI 本格運用や、より多彩な変異が欲しい場合は下記 mutmut を使う。

## バックエンド（Python）: mutmut

### インストール
```bash
pip install mutmut
```

### 実行（◎層に絞るのが鉄則）

全コードに掛けると非常に重い。priority ◎ の Service/UseCase 層だけに絞る。

```bash
mutmut run --paths-to-mutate app/services/
```

`setup.cfg` / `pyproject.toml` で設定を固定してもよい:
```ini
# setup.cfg
[mutmut]
paths_to_mutate = app/services/
runner = python -m pytest -x -q
```

`-x`（最初の失敗で停止）を付けると、mutant を kill できた時点で即座に次へ進むので高速。

### 結果を読む
```bash
mutmut results          # 生存/死亡のサマリと mutant ID 一覧
mutmut show <id>        # 特定 mutant の diff（どこをどう変異させたか）
mutmut show all         # 全 survived mutant の diff
```

### survived mutant の潰し方

1. `mutmut show <id>` で「どの行をどう変えたら test が通ってしまったか」を見る
2. その変異が表す挙動変化（例: `qty > 0` → `qty >= 0`）を検出できるテストを書く
   - 上の例なら「qty がちょうど 0 のとき」の境界テストが欠けている証拠
3. テストを追加し、`mutmut run` を再実行して killed に変わることを確認

### コスト管理

- 対象を1モジュールずつに絞る（`--paths-to-mutate app/services/retrain.py`）
- テストスイートが速いほど mutation testing 全体が速い。遅い統合テストばかりだと非現実的になるので、◎層は依存を絞った単体寄りのテストを併設しておくと効く
- CIで毎回は重い。下記「CI連携」参照

## フロントエンド（TypeScript）: Stryker

### インストール
```bash
npm install --save-dev @stryker-mutator/core @stryker-mutator/vitest-runner
```

### 設定（stryker.conf.json）
```json
{
  "$schema": "https://raw.githubusercontent.com/stryker-mutator/stryker-js/master/packages/api/schema/stryker-core.json",
  "testRunner": "vitest",
  "coverageAnalysis": "perTest",
  "mutate": ["src/**/*.ts", "!src/**/*.test.ts", "!src/**/*.d.ts"]
}
```

ロジック層（hooks・純粋関数・変換）に絞ると効果的。表示コンポーネントは対象から外してよい。

### 実行
```bash
npx stryker run
```

HTMLレポート（`reports/mutation/`）で survived mutant を確認し、mutmut と同じ要領で潰す。

## 結果の解釈ガイド

- **survived が多い ◎層** → 最優先で補強。ビジネスロジックの回帰を検出できていない
- **カバレッジは高いのに survived が多い** → 典型的な空洞テスト。アサーションが弱い証拠（`references/review-checklist.md` のアサーション強度を参照）
- **境界系の mutant（`>`↔`>=`、`+1`）ばかり生存** → 境界値テストの欠落
- **条件反転の mutant が生存** → その分岐の片側（false側 or true側）にテストが無い
- **`no tests` と出る mutant** → そのコードにテストが1本も無い（カバレッジ0の裏返し）

## mutation score の目安

厳密な基準を一律に課すより、◎層で「survived を1つずつ潰していく」運用が現実的。数値目標を置くなら Service層で 80% 前後を目安にし、達成不能な mutant（等価変異＝挙動が変わらない変異）は個別に除外設定する。

## CI連携

- **全体一律のカバレッジゲートは避ける**（空洞テストを量産する誘因になる）
- mutation testing は重いので、PR毎の全実行は非現実的。以下のいずれか:
  - 変更ファイルだけに mutmut を掛ける（差分ベース）
  - 週次 / nightly で ◎層に対して実行し、mutation score を監視
  - 手動トリガー（`workflow_dispatch`）で必要時のみ
- 既存の GitHub Actions（backend: ruff/alembic/pytest 並列）に、独立ジョブとして nightly の mutmut を足すのが shisui app_ver2 の構成に馴染む
