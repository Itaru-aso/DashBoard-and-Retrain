# モデル再学習ワークフロー — Requirements

> spec: `モデル再学習ワークフロー (model-retraining)`
> 配置想定: `.kiro/specs/model-retraining/requirements.md`
> 前提 steering: `product.md`（主要機能・不変条件1/5）, `tech.md`（subprocess・GPU・FTP・ONNX・WS）, `structure.md`
> 依存 spec: `基盤整備`（ver2 DB・単一ワーカ）／ `エッジPC管理`（FTP 接続先を利用）

## 概要 (Introduction)

色（フルタプル）に対する**モデル再学習のオーケストレーション**を担う。ジョブの起票・キュー管理・実行（subprocess）・
キャンセル・状態遷移・履歴、進捗のリアルタイム表示（WebSocket）、ONNX モデルの FTP 配信。
**学習用画像は同一 PC 上の別機能が所定パスへ用意**し、ver2 はそれを読むだけ（収集はスコープ外）。
学習成果は ver2 DB のジョブ記録（状態・時刻・結果）を正とし、進捗・ログは揮発（WS のみ）。

### スコープ (In Scope)
- 再学習ジョブの起票・キュー（FIFO・同時1本）・実行（subprocess・2GPU・monochro/color の対）・キャンセル。
- ジョブ状態遷移（`QUEUED → RUNNING → COMPLETED/FAILED/CANCELLED`）と履歴（ver2 DB）。
- 進捗・ログのリアルタイム表示（WebSocket・揮発）。
- ONNX モデルの FTP 配信（アプリ → エッジ）と、色ごとの**現行配信モデル**の記録。

### スコープ外 (Out of Scope)
- **学習アルゴリズム／モデル設計そのもの**（`training/` の外部パイプライン。ver2 は **subprocess で呼ぶだけ**）。
- **学習用画像の収集**（同一 PC 上の**別機能**が所定パスへ用意。ver2 はローカルパスを読むだけ＝スコープ外）。
- エッジPC接続情報の管理（→ `エッジPC管理` spec。ここでは**利用するだけ**）。
- 取り込み（外部）。閾値・ダッシュボード・色ライフサイクル（各 spec）。

### 用語・前提（`product.md`／`tech.md` 確定）
- モデル同一性: `(monochro/color) × color_no×size×chain×tape`。**1色 ↔ monochro/color の2モデル（対）**（不変条件1）。
- GPU: RTX PRO 4000 Blackwell 24GB ×2。**1ジョブで monochro/color を2枚の GPU で学習し2枚占有**。
- 学習は PyTorch、配信・推論は **ONNX**。FTP は **ONNX 配信（アプリ→エッジ）のみ**（平文 `ftplib.FTP`・ver1 踏襲・接続情報は DB 管理）。
- 学習用画像は**同一 PC 上の所定パス**（`TRAINING_DATASET_PATH` 相当。外部が用意）から読む（ver2 は収集しない）。
- 単一ワーカが subprocess・キューを所有（`tech.md`）。

---

## 要件 (Requirements)

### M-R1. ジョブ起票
**受け入れ基準 (EARS)**
1. 色（`color_no×size×chain×tape`）を指定して再学習ジョブを起票できる（SHALL）。
2. 1ジョブは **monochro/color の対**を学習対象とする（SHALL。不変条件1）。
3. 起票は**作業者の手動実行**（画面から色を選んで起票）（SHALL）。

### M-R2. キュー・同時実行
**受け入れ基準 (EARS)**
1. 起票直後の状態は `QUEUED`。キューは **FIFO**（SHALL）。
2. **同時実行は1本**（`RUNNING` は高々1つ。後続は QUEUED で待つ）（SHALL）。

### M-R3. 実行（subprocess・GPU）
**受け入れ基準 (EARS)**
1. 実行時、`training/` パイプラインを **subprocess** で起動し、`RUNNING` にする（SHALL）。
2. **2枚の GPU** で monochro/color を学習する（2枚占有）（SHALL）。
3. 学習用画像は**同一 PC 上の所定パス**（外部が用意）から読む（ver2 は収集しない）（SHALL）。

### M-R4. 状態遷移
**受け入れ基準 (EARS)**
1. 状態は `QUEUED → RUNNING → COMPLETED / FAILED / CANCELLED`（SHALL。不変条件5）。逆行しない。

### M-R5. キャンセル
**受け入れ基準 (EARS)**
1. `QUEUED` のジョブはキューから除去して `CANCELLED` にできる（SHALL）。
2. `RUNNING` のジョブは**プロセスツリー kill** で停止し `CANCELLED` にできる（SHALL）。

### M-R6. 進捗のリアルタイム表示
**受け入れ基準 (EARS)**
1. 実行中の進捗・ログを **WebSocket** で配信する（SHALL）。
2. 進捗・ログは**揮発**（永続しない）。永続するのはジョブ記録のみ（SHALL）。

### M-R7. ジョブ記録・履歴
**受け入れ基準 (EARS)**
1. ジョブの状態・開始/終了時刻・結果/エラーを **ver2 DB に永続**（DB を正）（SHALL）。
2. ジョブ履歴を一覧・参照できる（SHALL）。

### M-R8. ONNX モデルの配信・現行モデル管理
**受け入れ基準 (EARS)**
1. 学習成果（ONNX）をエッジPCへ **FTP で配信**（アプリ → エッジ）する（SHALL）。
2. **v1 は学習成功（`COMPLETED`）時に自動配信**する（SHALL）。
   将来は「完了 → 人が結果確認 → 手動配信」へ切り替える（**非破壊で移行**）。
3. 配信したモデルを**色ごとの「現行配信モデル」**として記録する（どのジョブの成果か・配信日時）。
   再配信・現行把握に用いる（SHALL）。

### M-R9. アクセス
**受け入れ基準 (EARS)**
1. 認証は Basic 認証（単一共有・ロールなし）（SHALL）。

---

## 確定事項 (Resolved)

- **T1 起票** ＝ **作業者の手動実行**（画面から色を選んで起票）。
- **T3 ONNX 配信** ＝ **v1 は学習成功時に自動配信**。将来は「完了 → 確認 → 手動配信」へ非破壊で移行。
- **T4 モデル管理** ＝ ジョブ履歴 ＋ **色ごとの現行配信モデルの最小管理**（再配信・現行把握）。

> FTP は**配信のみ**（アプリ → エッジ）。学習用画像は同一 PC 上の別機能が用意（**収集はスコープ外**）。
