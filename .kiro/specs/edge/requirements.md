# エッジPC管理 — Requirements

> spec: `エッジPC管理 (edge-pc)`
> 配置想定: `.kiro/specs/edge-pc/requirements.md`
> 前提 steering: `product.md`（エッジPC管理＝モデル配信先の登録・管理）, `tech.md`（FTP 接続情報は DB 管理）, `structure.md`
> 依存される spec: `モデル再学習ワークフロー`（配信先としてこの接続情報を利用）

## 概要 (Introduction)

ONNX モデルの **FTP 配信先**（エッジPC＝検査PC）の**接続情報を登録・管理**する。
接続情報は **ver2 DB** に持つ（環境変数に置かない）。FTP は平文 `ftplib.FTP`（ver1 踏襲）。
**実 FTP I/O（配信そのもの）は `モデル再学習ワークフロー`／`training/` が担い**、本 spec は**接続先の管理のみ**。
学習用画像の収集元ではない（収集は同一 PC 上の別機能・スコープ外）。

### スコープ (In Scope)
- エッジPC（FTP 配信先）接続情報の登録・更新・削除・一覧（ver2 DB）。
- （任意）接続テスト。

### スコープ外 (Out of Scope)
- 実 FTP 配信処理そのもの（→ `モデル再学習ワークフロー`／`training/`）。
- 学習用画像の収集（別機能・スコープ外）。取り込み（外部）。

### 用語・前提（`tech.md` 確定）
- FTP は平文 `ftplib.FTP`（ver1 踏襲）。FTPS/SFTP は要件化まで不採用。
- 接続情報は **DB 管理**（env に置かない）。

---

## 要件 (Requirements)

### E-R1. 接続先の登録・管理
**User Story**: 保守担当者として、モデルの配信先エッジPCを登録・管理したい。

**受け入れ基準 (EARS)**
1. エッジPC接続情報を登録・更新・削除できる（SHALL）。
2. 保持項目（**ver1 準拠・配信スコープに限定**）: 名称・`host`・`username`・`password`（平文）・
   `model_port`（**ONNX 配信用**）・有効フラグ。`username` はドメイン付き（例 `ykk\shisui_PJ`）を許容。
   `monochro_port`／`color_port`／`local_root` は ver1 の**画像収集用**で本スコープ外のため**持たない**。
   配信先パス（remote_path）も ver1 に無いため持たない。
3. 名称（または識別子）の重複は不可（SHALL）。

### E-R2. パスワードの保管
**受け入れ基準 (EARS)**
1. 接続情報は **ver1 踏襲で平文保管**（暗号化しない）（SHALL）。
2. パスワードは平文の文字列で保持する（ver1 に実値あり。例 `shisui@09`）（SHALL）。

### E-R3. 配信先の決定
**受け入れ基準 (EARS)**
1. 再学習成果は、**登録済みで有効な全エッジPCへ配信**する（色→エッジPC のマッピングは持たない）（SHALL）。
   各検査PCは自分が扱う色のモデルのみ使用する前提。

### E-R4. 一覧・参照
**受け入れ基準 (EARS)**
1. エッジPC接続先を一覧・参照できる（SHALL）。

### E-R5. FTP 送信可否の監視
**受け入れ基準 (EARS)**
1. 登録済みエッジPCへの **FTP 接続可否（ファイル送信可能な状態か）を確認**でき、一覧に状態として表示する（SHALL）。
2. 確認はオンデマンド（テスト実行）で行える。定期チェック（スケジューラ）は任意（SHOULD）。
3. 監視対象は **FTP 到達性（送信可否）のみ**。機台の CPU/メモリ/FPS 等のテレメトリは対象外。

### E-R6. アクセス
**受け入れ基準 (EARS)**
1. 認証は Basic 認証（単一共有・ロールなし）（SHALL）。

---

## 確定事項・残課題 (Resolved & Pending)

確定:
- **E3 配信先**: **有効な全エッジPCへ配信**（マッピングなし。`deployment_service` は有効な全台へ送る）。
- **E2 パスワード**: **平文保管**（ver1 踏襲・実値あり。例 `shisui@09`）。
- **E1 接続情報**: 名称・`host`・`username`（ドメイン付き可）・`password`（平文）・`model_port`・有効フラグ。
  収集用の `monochro_port`／`color_port`／`local_root` は持たない。`remote_path` も持たない。
- **配信ポート**: **`model_port`**（monochro/color ポートは画像収集用＝スコープ外）。
- **監視**: **FTP 送信可否**（オンデマンド確認＋一覧に状態表示。定期チェックは任意）。CPU/FPS 等のテレメトリは対象外。
