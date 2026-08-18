# 評価・較正データリークの修正（ADR）

> v1.0（2026-08-18）。`@.kiro/specs/retraining/dataset-export-root-migration.md` の決定19・26・28 の
> 「分割の単位」を上書きする。学習アルゴリズム本体（損失関数・モデル構造・学習ループ）は対象外・変更しない。

## 背景

色番911の monochro 学習で `⚠️ test データが空です (good: 0, defect: 14)` が出たことを起点に調査したところ、
評価が空になる症状の裏に**4つの独立したデータリーク**が存在することが判明した。

### 発見の経緯（実測値）

- メイン `export_root` の monochro データセット `binary/911/` には **NG カテゴリ（on_class=1, 48件）の
  ディレクトリのみ**が存在し、metadata.json に定義済みの良品カテゴリ（`019ef75b-6ea8-...`, on_class=0）の
  ディレクトリが物理的に存在しない。→ `good_pool=0` → `train/good`・`test/good` とも 0 件。
  **split 処理自体は入力どおりに正しく動作している。**
- 075 monochro も同一状態（`good_pool=0` / `defect_pool=2`）。**色番固有の欠落ではなく monochro 全般の
  構造的ギャップ**である可能性が高い。
- 学習自体はマージン側（`export_root_margin`）の良品で成立していた（911: 1059ファイル、075: 2868ファイル）。

### リークの一覧

| ID | 内容 | 該当箇所 | 汚染対象 |
|---|---|---|---|
| L1 | monochro の `test/good` が較正セットと評価セットの兼用 | `train/monochro.py:195-197` ↔ `evaluation/evaluator.py:29` | 評価のFA率 |
| L2 | Evaluator が評価対象データで閾値を再フィット | `evaluation/scoring.py:62-88` の呼び出し方 | 両モードのFA/miss/F1 |
| L3 | 良品側 split が製品IDをグループ化しない（不良側はする） | `utils/split_manager.py:135-150` vs `110-127` | color評価セット・(将来)monochro較正 |
| L4 | マージンの train/val 分割がサンプル単位（top/bottom を独立に扱う） | `train/monochro.py:224-231` | monochro較正セット（＝配信閾値） |

**L4 の規模（実測）**: `RawShiftImageFolder.__len__` は `sample_mode="both"`（既定）で
`ファイル数 × 2`（1 raw画像から top/bottom を生成）。`monochro.py` は
`margin_full_size = len(margin_train_full)` に対し `torch.randperm` を掛けるため、
**同一 raw 画像の top と bottom が train と val に分かれる**。

| color | marginファイル数 | サンプル数 | train | val | valのうちペアが学習側にある割合 |
|---|---|---|---|---|---|
| 911 | 1059 | 2118 | 1482 | 636 | 1482/2117 ≈ **70.0%** |
| 075 | 2868 | 5736 | 4015 | 1721 | 4015/5735 ≈ **70.0%** |

（サンプル数は実ログと一致: 911 val=636→159バッチ、075 val=1721→431バッチ・train=4015→1004バッチ）

**L3 の規模（実測・911 color）**: `good_pool` 2566ファイル → train 1796 / test 770。
テスト側各ファイルのペア面が学習側にある確率 1796/2565 ≈ **70.0%**（約539/770枚）。

L4 は「配信される閾値」を汚しており、**val が容易になる → 閾値（val の99.5パーセンタイル）が低くなる →
実機で良品が閾値を超える**方向のバイアスを生む。実機FP問題の一因である可能性があり、要検証。

## 決定

### 決定1（S2）: 評価は para.json の配信閾値で行う
`Evaluator` は `para.json` の `threshold`（ONNXに焼かれ実機へ配信される値）で指標を算出する。
同一データ上で F1 を最大化する後付け閾値は `ref_f1_optimal_threshold` / `ref_f1_optimal_F1` として
**参考値のみ併記**し、主指標には使わない。閾値が取得できたかは `threshold_from_para`（1.0/0.0）で残す。

- **理由**: `find_optimal_threshold` は評価対象そのものにフィットするため、算出される
  FA/miss/F1 は「配信される挙動」を表さない（AUCは閾値非依存のため影響なし）。
- **`evaluation/scoring.py` は変更しない**。既存関数は参考値算出にそのまま使う。
  （副次的利点: 実行中の学習ジョブは `evaluation.scoring` を遅延importするため、
  scoring.py を触らないことで in-flight のジョブに影響を与えない）

### 決定2（S1）: monochro の validation は train 側から作り、`test/good` は評価専用にする
`test/good/images` を較正（`validation_loader`）から外す。tight 側の validation は
`train/good` を分割して得る。これにより `test/good` は学習・較正に一切使われない held-out になる。

- **分割比率は 0.8/0.2**（color の `color.py:195` `int(0.8 * len(full_train_set))` と同一）。
  `pool_train_ratio`（0.7）は**流用しない**。`train/good` は既に `split_pool_to_train_test` の
  70% 出力であり、再度 0.7 を掛けるとプール比 49%/21% という誰も選んでいない配分になるため。
  決定26 の「`pool_train_ratio` を流用し新規キーを作らない」は**マージンプールの分割**についての
  判断であり、train 側の再分割には適用しない。
- **現状 no-op**: 911・075 は `train/good`・`test/good` とも 0 件のため数値は変わらない。
- **margin が無い色番では挙動が変わる**（val が `test/good` → `train/good` の20%）。
  これは意図した修正であり、該当色番の再学習時は para.json の回帰確認対象とする。

### 決定3（S1・S3 共通）: 分割の単位を「撮像」に統一し、実装を共有ヘルパに寄せる
1撮影 = 表面(top) + 裏面(bottom) の2枚であり、同一製品・同一照明・同一瞬間で強く相関する。
片面を学習に、他面を較正/評価に使うことを禁じる。

`utils/split_manager.py` に既存の `_extract_product_id` / `_group_by_product_id` を使う
**共有ヘルパ `split_files_by_product`（ファイル一覧・比率・seed → 2分割）** を追加し、
以下から呼ぶ。

- `split_pool_to_train_test` の良品側（S3。不良側の既存実装と対称化）
- `train/monochro.py` の tight train/val 分割（S1）

- **理由**: 同じ分割ロジックの近似コピーを3箇所に持つと、次の担当者が2箇所しか直さない。
- **境界確認済み**: `tests/ci_gates/test_training_boundary.py` が禁じるのは
  「`train/` 内部モジュールを `train/` 外から import すること」であり、`train/` が
  `utils.split_manager` を import することは許容される（`dataset/manager.py`・
  `evaluation/scoring.py` も既に import 済みの共通モジュール）。

### 決定4（S4）: マージンの train/val 分割をファイル単位にする
`torch.randperm` をサンプル数（2N）ではなく**ファイル数（N）**に対して行い、
分割後にサンプルindexへ展開する（`sample_mode="both"` なら ファイル i → サンプル `2i`, `2i+1`）。
展開倍率は `len(dataset) // len(dataset.paths)` から導出し、`sample_mode` を前提に置かない。

- 決定28 の「`full_size = len(margin_train_full)` に randperm」を本決定で上書きする。
  旧CW実装から引き継いだパターンだが、top/bottom がサンプル単位で混ざる帰結は考慮されていなかった。
- 決定16 の「マージンプールと export_root は製品レベルで重複しない（ユーザー確認済み）」という前提は
  **マージンプール内部の train/val 分割には及ばない**。
- `RawShiftImageFolder` 自体は無改修（決定18を維持）。

### 決定5（S3）: コード変更は行うが、`4_dataset` の再生成は別途承認を得る
`split_pool_to_train_test` は差分追加方式（`split_manager.py:144` `if not os.path.exists(dst)`）のため、
**分割ルールを変えても既に配置済みのファイルは移動しない**。S3 を実効化するには
`4_dataset/{color}/{mode}/{train,test}` の削除・再生成が必要。

これは不可逆・破壊的操作であり、かつ既存全モデルの train/test 境界を無効化するため、
**コードのみ先行してコミットし、再生成は明示承認を得てから実施する**（承認まで S3 は休眠状態）。

## 却下した代替案

- **マージンデータの一部をメイン `export_root` へ移動して split 対象に入れる案**: 「評価が空」の症状は
  消えるがリークは残る。移動した良品は `train/good` と `test/good` の両方に入り、`test/good` は
  monochro の較正セットなので held-out にならない。加えて (a) マージンプールを削ることで決定26 が
  意図的に増やした `margin_val` が縮む、(b) `train/good` 経由の画像は `_FlatGoodImageFolder` で
  シフトなし読み込みになり ±20px 頑強性に寄与しない、(c) メインは 1250×670・`_top`/`_bottom` 付き
  （crop・分割済み）だがマージンは 2048×1220・接尾辞なし（生センサー座標・未分割）で、
  `dataset/manager.py:145-147` は `process_image` の x=485 crop を通さず単純 resize するため
  誤フレーミングの画像が混入する。**(c) は事前 crop で回避可能だが (a)(b) とリーク残存は残るため不採用。**
- **完了判定（`training_service._run_job`）を評価成功でハードゲートする案**: 不良サンプルが無い色番が
  正当に失敗するうえ、評価は ONNX・閾値が確定した後の事後処理であるため不適。代わりに評価結果の
  永続化（観測可能性の向上）で「COMPLETED かつ未評価」を識別可能にする方針とする（本ADRの対象外・別途）。
- **`test/good` を較正に使い続け、評価用に第3の split を新設する案**: split が3系統になり
  データ量の少ない色番で各セットが痩せる。color と同じ2系統（train側を分割・test は held-out）で足りる。

## 非目標・制約

- **非目標**: 学習アルゴリズム本体（損失関数・モデル構造・学習ループ・color側の学習ロジック）の変更。
  本ADRの変更は DataLoader構築部分（決定20の例外範囲）・split ユーティリティ・評価ステージに限る。
- **非目標**: 評価結果の永続化（`training_service` / DB）。本ADRとは別スコープ。
- **制約**: `evaluation/scoring.py` は変更しない（決定1）。
- **要承認**: `utils/split_manager.py` は CLAUDE.md の既存例外リストに未記載。文言案を
  「未解決事項」に記す。

## 検証基準

リーク解消の完成条件は数値ではなく**集合の非交差**で定義し、テストで固定する。

1. 学習・較正に使ったファイル集合 ∩ 評価に使ったファイル集合 = ∅（決定2・L1）
2. 同一 raw ファイル由来のサンプルが train と val に跨らない（決定4・L4）
3. 同一 product_id が train と test に跨らない（決定3・L3）
4. 評価出力の threshold が para.json の値と一致する（決定1・L2）

加えて **S1/S4 適用後に色番911を再学習し、`para.json` の `threshold` / `cand1_A` / `cand1_Z` を
現行値と比較する**（予測方向: 閾値が上がる）。これがリーク修正が較正へ効いた唯一の実測証拠になる。

現行値（S1/S4 適用前・2026-08-18 取得）:

| color/mode | threshold | cand1_A | cand1_Z | q_st_start | q_st_end |
|---|---|---|---|---|---|
| 911 monochro | 0.7860505467653283 | 0.5023857682943343 | 11.680119830940974 | 0.42459596991539006 | 0.6742388612031943 |
| 911 color | 5.368054239749911 | (cand1無効・キーなし) | 同左 | 0.35274963080883026 | 0.8008358344435651 |

`para.json` の実ファイルはセッションのスクラッチ領域
（`baseline_before_leak_fix/911_{mode}_para.json`）に退避済み。再学習は
`6_model/911/{mode}/para.json` を上書きするため、比較時はこの退避分を参照する
（パイプライン自身の `backup_model()` による `backup/` 配下の自動バックアップも併用可）。

**911 color は S1/S4 の対象外**（S1/S4 は monochro のみ）。color 側は S2 により
評価数値の意味だけが変わるため、para.json の較正定数は変化しない見込み。
これも回帰確認の対象（変わらないことの確認）とする。

## 未解決事項

- **`4_dataset` 再生成の承認**（決定5）。承認まで S3 は休眠。再生成は既存モデルの train/test 境界を
  無効化するため、どの色番を対象にするかも合わせて決める。
- **CLAUDE.md 例外リストへの追記文言（案・ユーザー確認待ち）**:
  「①データ取得・選定前処理部分」の列挙に `training/utils/split_manager.py`（train/test 分割の
  グループ化単位の修正に限る）を追加する。
- **S4 適用後に検知率が下がる可能性**。閾値が上がるため FP は減る見込みだが、実機NGサンプルでの
  検知率確認を回帰項目に含める必要がある。
- **メイン `export_root` に monochro 良品が出力されない原因**（export生成側は本リポジトリ外・
  決定22の非目標）。「そもそも良品がアノテーションされていない」のか「生成器が落としている」のかを
  export 側と確認する必要がある。これが解消しない限り monochro の評価は空のままになる。

## 変更履歴

- [2026-08-18] v1.0 初版。911 monochro の評価スキップ調査から4つのリーク（L1〜L4）を特定し、
  S1〜S4 の修正方針を決定。L4（マージンの分割単位）は本調査での新規発見。
