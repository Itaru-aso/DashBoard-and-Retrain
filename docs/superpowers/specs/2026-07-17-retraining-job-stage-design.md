# 再学習ジョブ全体のステージ表示 設計書

- 日付: 2026-07-17
- 対象: `frontend/src/pages/retrainingProgress.ts`（拡張）/ `frontend/src/hooks/useRetraining.ts` / `frontend/src/pages/Retraining.tsx`
- 関連: [[2026-07-16-retraining-progress-readability-design]]（進捗パネル可読化）の続き

## 背景・課題

進捗パネル可読化（前回の設計・実装）で追加した進捗バーは「monochro/color 各モードの学習ループ進捗」を示すもので、バーが100%になっても学習完了直後の評価・ONNX出力・アップロード処理などが続くため、ジョブ全体としては完了していない。ユーザーから「ジョブ全体としての進行度を見たい」との要望があった。

## 方針

数値%での全体進行度は推定しない（各ステージの相対時間比が学習時間・データ量・GPU環境で変動し、正確な重み付けができないため）。代わりに、`training/pipline.py` が実際に出力する既知のテキストマーカーから「今どのステージにいるか」を検出し、テキストで表示する。

## ステージ定義

実際に `training/pipline.py` / `training/model_exporter.py` に存在する print 文を確認済みのマーカーとして使う。

| stage | ラベル | 検出マーカー | 出典 |
|---|---|---|---|
| `backup` | バックアップ中 | `バックアップ作成中` | `pipline.py:615` |
| `training` | 学習中 | `モノクロAIの学習を開始します` / `カラーAIの学習を開始します` / `並列学習 GPU 割当` | `pipline.py:444,447,683` |
| `export_eval` | モデル出力・評価中 | `Exported ONNX:` | `model_exporter.py:179` |
| `completed` | 完了 | `パイプライン完了` | `pipline.py:732` |

## 検出ロジック

`frontend/src/pages/retrainingProgress.ts` に `detectStage(raw: string): Stage | undefined` を追加する。生ログ1行に対し、上表のマーカー（正規表現、非アンカー・prefix有無を問わない）に一致すれば対応する `Stage` を返す。一致しなければ `undefined`。

`useJobProgress`（`useRetraining.ts`）に `stage: Stage | undefined` を追加し、受信した行ごとに `detectStage` を呼ぶ。検出結果が現在の `stage` より**後方**（`STAGE_ORDER` 配列の添字が大きい）の場合のみ更新する（**単調前進のみ・後退しない**）。並列学習中に🟢🔵どちらの行が来ても同じ `training` ステージなので後退は発生しない。ジョブ切り替え・WS再接続時は `undefined`（起動中）にリセットする。

マーカーに一致しない行の分類（`classifyLine` によるprogress/other振り分け）には影響しない。`detectStage` は既存の分類と並行して独立に動作する。

## UI

`Retraining.tsx` の `ProgressPanel` 内、既存のステータス行（「学習中 配信中」等を表示している `.statusRow`）に、`stage` に対応するラベル（例:「現在の処理: 学習中」）を追加表示する。`stage` が `undefined`（まだ何も検出していない）間は「起動中…」を表示する。進捗バー2本（monochro/color の学習ループ進捗）は変更しない。

## テスト方針

- `detectStage` の単体テスト（vitest）: 4マーカーそれぞれの検出、一致しない行での `undefined`。
- `useJobProgress` の単調前進ロジック: 後方のマーカーが先に来ても `stage` が後退しないことを確認（例: `training` 検出後に前段の `バックアップ作成中` が遅延到着しても `training` を維持）。
- `Retraining.tsx` 統合テスト: WSメッセージでステージラベルが更新されることを確認。

## スコープ外（既知の制約）

- 全体%表示は行わない（上記方針の通り）。
- `training/` 側の print 文自体は変更しない。
- バックエンド（WebSocket配信仕様）は変更しない。
