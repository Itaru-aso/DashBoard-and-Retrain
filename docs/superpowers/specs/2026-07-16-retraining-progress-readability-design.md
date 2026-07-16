# 再学習進捗パネルの可読化 設計書

- 日付: 2026-07-16
- 対象: `frontend/src/pages/Retraining.tsx`（モデル再学習画面の進捗パネル）
- 関連: `.kiro/specs/retraining/`（M-R6: WebSocketで進捗・ログを揮発配信・行を素通し配信）

## 背景・課題

UIのAI学習画面は `training/pipline.py` の標準出力を `[STATUS]`/`[CMD]` 等の一部プレフィックスを除きそのまま `<pre>` に表示している。学習ループの tqdm 進捗（`Current loss: 0.37  :  91%|████████ | 22001/24120 [1:05:02<5:39:04,  9.60s/it]` のような行）が延々と流れ続けるため、視認性が悪い。特に:

- tqdm 進捗のノイズ（同じ内容の繰り返し・バー文字）でログが埋まる
- ログの量が多すぎて、重要な行（開始/完了/警告/エラー）が埋もれる

## 調査で判明した事実

- フロント: `Retraining.tsx` の `ProgressPanel`（L85-115）が `useJobProgress`（`useRetraining.ts` L76-101）で受信した行を素通しで `<pre>` に蓄積・表示している。
- バックエンド: `training_service.py` は `[STATUS]`/`[CMD]`/`[ERROR]`/`[DEPLOY]` の自前プレフィックス行と、`training/` からの素通し行を同じ WebSocket に配信する（M-R6 仕様: 行を素通し配信・揮発）。
- `training/pipline.py` は既定で `parallel_train: true`（`conf/config.yaml`）。monochro/color を並列学習し、各子プロセスの標準出力は `training/utils/log_tailer.py`（`LogTailer`）が専用ログファイルを tail して `[monochro] ...` / `[color] ...` のプレフィックス付きで親プロセスの標準出力へ再配信する。この再配信は `\r`/`\n` どちらでも正しく行分割される。
- 子プロセス内の学習ループ（`train_func_color.py`/`train_func_monochro.py`）が tqdm で `Current loss: X  : N%|bar| cur/total [elapsed<remaining, rate]` 形式の進捗を出す。`Validation Loss: X` は各エポック末の素の print。
- `training/` の学習ロジック（tqdm 呼び出し・print 文自体）は改変禁止（CLAUDE.md）。変更対象はフロントエンドの表示ロジックに限定する。

## 方針

バックエンドの WebSocket 配信仕様（素通し・揮発）は変更しない。フロントエンドで受信した行をその場で分類し、UIを「進捗バー（monochro/color 2本）＋重要ログ一覧＋元ログ展開表示」の3段構成に変更する。

### 分類ロジック（`frontend/src/lib/trainingProgress.ts` 新規）

`classifyLine(raw: string): ClassifiedLine` という純粋関数を追加する。

1. 先頭の `[monochro] ` / `[color] ` を検出し `phase` として取り出す（`LogTailer` の接頭辞）。無ければ `phase` は `undefined`。
2. 残りの文字列が tqdm 進捗パターン（`<desc>: NN%|bar| cur/total [elapsed<remaining, rate]`）に一致するかを正規表現で判定する。一致すれば以下を返す:
   ```ts
   { kind: "progress"; phase?: "monochro" | "color"; percent: number;
     current: number; total: number; loss?: number; eta?: string; raw: string }
   ```
   `desc` 部分に `Current loss: ([\d.]+)` があれば `loss` として抽出する。
3. 一致しなければ `{ kind: "other"; phase?: "monochro" | "color"; raw: string }` を返す（`[STATUS]`/`[CMD]`/`[ERROR]`/`[DEPLOY]`・emoji ログ・`Validation Loss:` 等はすべてここに入る）。
4. 正規表現が想定外のtqdm変種に一致しない場合も例外を投げず `"other"` にフォールバックする。

### フック（`useJobProgress`, `frontend/src/hooks/useRetraining.ts`）

既存の `lines: string[]`（素通し全行、変更なし）に加えて状態を2つ追加する:

- `importantLines: string[]` — `classifyLine` が `"other"` と判定した行のみ蓄積。
- `progress: Partial<Record<"monochro" | "color", ProgressState>>` — `"progress"` と判定した行で該当フェーズのキーを都度上書き（直近の進捗のみ保持。`phase` が無い行は `"monochro"` として扱わず、専用の暫定キー無しで無視 — 実運用では並列時は必ず `[monochro]`/`[color]` 接頭辞が付くため問題にならない）。

`ws.onmessage` 内で `classifyLine` を1回呼び、`lines`・`importantLines`・`progress` を同時に更新する（メッセージごとにO(1)、既存の再レンダリングコストを増やさない）。

### UI（`Retraining.tsx` の `ProgressPanel`）

- 上部: monochro用・color用の進捗バーを常に2本並べる。`percent`/`current/total`/`loss`/`eta` を表示。該当フェーズの進捗がまだ来ていなければ「待機中…」。
- 中部: `importantLines` を現行と同じ見た目の `<pre>` ログボックスで表示する（tqdmノイズが消え、重要行だけになる）。
- 下部: `<details><summary>元ログを表示</summary></details>` で既存の全行素通し `<pre>`（`lines.join("\n")`）を折りたたみ表示する（デフォルト閉、デバッグ時のみ展開）。
- 失敗理由表示（`job.error_message`）は現状維持。

## テスト方針

- `classifyLine` の単体テスト（vitest）: tqdm行の分類（接頭辞あり/なし）・loss抽出・eta抽出・非tqdm行のフォールバック・不完全な行（分類できないパターン）でも例外にならないこと。
- `useJobProgress` の更新: モックWebSocketメッセージを流し、`lines`/`importantLines`/`progress` が期待通り分離・更新されることを確認する。
- `Retraining.tsx` の表示は手動確認（モックWSメッセージで進捗バー・重要ログ・元ログ折りたたみの見た目を目視確認）。

## スコープ外（既知の制約）

- WS再接続時に配信される直近200行バッファ（`training_service.py` の `_RECENT_LINES`）に重要行が埋もれる可能性は既存の制約であり、本タスクでは対応しない。
- **直列学習時（`training/pipline.py` が `parallel_train: false` で動く場合）は進捗バーが動作しない既知の制約。** `LogTailer` による `[monochro]`/`[color]` 接頭辞は並列学習（`_spawn_with_gpu_env` で子プロセスに分離した場合）のみ付与される。直列実行では `run_trainer` が親プロセス内でそのまま動くため tqdm 行に接頭辞が付かず、`classifyLine` が `phase` を取り出せずに `useJobProgress` がその進捗行を破棄する（進捗バーは「待機中…」のまま、元ログには残る）。
  `pipline.py:669-673` は「color/monochro のどちらかで MLflow が有効」なときに限り `parallel_train` を自動的に `false` へ強制する。一方 `TrainingConfig.base_overrides`（`training_service.py`）は ver2 UI から起票する**すべて**のジョブに対し無条件で `color.mlflow.enabled=false`／`monochro.mlflow.enabled=false` を付与し、`parallel_train` 自体を上書きすることもない。したがって **ver2 UI 経由の起票では直列化条件に到達せず、既定の `parallel_train: true`（`training/conf/config.yaml`）のまま並列実行される**。この制約が現実に影響するのは `training/conf/config.yaml` を手動で書き換える、または ver2 を経由せず `pipline.py` を直接起動する場合のみであり、本タスクでは対応しない。
- `training/` 側の print/tqdm 呼び出し自体は変更しない（学習ロジック改変禁止）。
- バックエンドの WebSocket 配信仕様（素通し・揮発、`.kiro/specs/retraining` M-R6）は変更しない。
