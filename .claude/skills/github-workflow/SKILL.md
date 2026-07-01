---
name: github-workflow
description: shisui app_ver2 の日常的な Git 作業（add → commit → push で main に反映）を Claude Code 上で実施するワークフロー。対象リポジトリは Itaru-aso/DashBoard-and-Retrain（origin・main 直接運用）。spec/steering の .md や .py などを作成・編集したあとの反映、および cc-sdd のタスク（.kiro の tasks.md）を1つ実装し終えた区切りでは、明示指示がなくても自発的にコミット〜push まで進める。Conventional Commits 規約・tasks.md の [x] 連動・push 前の秘密情報/app_db 書き込みチェックもこのスキルが扱う。「コミットして」「push して」「今の変更を反映して」「GitHub に上げて」「上げといて」などの依頼、実装が一段落した場面はすべて対象。一方、git の使い方の説明、コミット履歴の要約、マージコンフリクト解決、CI 失敗のデバッグ、誤 push のリカバリ、単なるファイル編集だけの依頼など「add→commit→push による反映」以外の git 関連作業には使わない。
---

# GitHub Workflow (shisui app_ver2 / ソロ開発・main 直接運用)

shisui app_ver2 は原則ソロ開発。ブランチや PR は使わず、**main に直接 commit → push する軽量運用**。そのぶん「push した瞬間に main が正となる」ため、壊れた状態や秘密情報を push しないための push 前チェックが重要。

- **対象リポジトリ**: `https://github.com/Itaru-aso/DashBoard-and-Retrain.git`（`origin` に登録済み・追跡ブランチ `main`）
- **作業クローン**: `D:\0032011\GitLab\shisui\app_ver2`（Windows ネイティブ）
- **構成**: バックエンド FastAPI + SQLAlchemy + Alembic + PostgreSQL、フロントエンド React/TypeScript、開発は cc-sdd（`.kiro/specs/<spec>/tasks.md` でタスク管理）。

## 発火タイミング（このワークフローに入る場面）

このワークフローは「ファイルを保存した瞬間」に自動で走るものではなく、**変更を Git に記録する工程に入ったとき**に使う。具体的には次の場面で発火する。

- ユーザーが「コミットして」「push して」「今の変更を反映して」「GitHub に上げて」などと依頼したとき。
- **cc-sdd のタスク（`.kiro/specs/<spec>/tasks.md`）を1つ実装し終えた区切りに達したとき。** この場合は明示の指示がなくても、自発的にこのワークフローに従ってコミット〜push まで進める。対象は spec/steering の `.md` 編集、`.py` などプログラムファイルの作成・編集の両方。

### コミットへ進んでよい「区切り」の条件

区切り＝タスク完了。以下を満たして初めて commit → push する。中途半端な状態を main に push しない。

- 対象タスクの実装が動作する状態になっている（壊れていない）。
- 触った範囲の lint / format / test が通っている。
- `tasks.md` の該当行を `[x]` に更新できる状態（＝実際に完了している）。

まだ作業途中なら push せず、必要なら `tasks.md` を `[~]`（作業中）にとどめる。

## 実行場所（どのマシンで git を叩くか）

git の作業クローンと Claude Code は **Windows PC 上（ネイティブ）** にある。`git add` / `git commit` / `git push` はすべてこの Windows PC のローカルクローン内で実行する。これがソースコードの唯一の正（single source of truth）。

- **本番 HPC サーバーではコミットしない。** HPC 上の Docker Compose 環境はデプロイ先（動く場所）であって、編集・コミットする場所ではない。
- **ソースを scp で運ばない。** マシン間の同期は push / pull で行う。scp を使うのは DB ダンプなどの非ソース資産に限る。
- **反映の順序:** Windows PC で編集・commit → GitHub(main) へ push → HPC へデプロイ（サーバー側で pull してビルド、または CI/CD）。このワークフローが扱うのは push まで。デプロイは別工程。

### Windows → Linux 特有の注意（改行コード）

Windows で編集し Linux の Docker 上で動かすため、改行コード（CRLF/LF）差異が事故のもとになる。特に **シェルスクリプト（例: `init/restore.sh`）が CRLF になると Linux コンテナ内で実行できない**。リポジトリ直下に `.gitattributes` を置いて LF に正規化しておく（このリポジトリではまだ未設定なので、初回に作成しておくと安全）:

```gitattributes
* text=auto eol=lf
*.sh text eol=lf
*.png binary
*.dump binary
```

既存の `.gitattributes` / `core.autocrlf` があればそれに合わせる。`git add` 時に出る `LF will be replaced by CRLF` の警告はこの正規化に伴う想定内のもので、無害。

### .gitignore で除外済みのもの（このリポジトリの前提）

初回セットアップ済みの `.gitignore` により、以下は追跡対象外。push 前チェックでもこれらが紛れていないか確認する。

- `.omc/`（OMC セッション状態・成果物ではない）
- 大容量バイナリ: `*.bmp`（検査画像）/ `*.pth` `*.onnx` `*.pt` `*.ckpt` `*.safetensors`（モデル）
- 秘密情報: `.env` / `.env.*`（`DATABASE_URL` / `BASIC_AUTH_PASS` 等）
- Python / Node の生成物（`__pycache__/` `node_modules/` `dist/` など）

大容量のモデルを GitHub で配布したくなった場合は Git LFS 導入を別途検討する（無料枠の帯域・ストレージに注意）。

## 標準フロー（add → commit → push）

> 完全ソロ・main 直接運用のため、作業前の定型 `git pull` は行わない（他者の push がなく空振りになるため）。リモートが進んでいて push が弾かれた場合のみ、後述の手順3で `git pull --rebase` する。

### 1. 変更内容の把握と安全確認

コミット対象を必ず自分の目で確認する。PR がない運用なので、この確認が唯一のレビュー機会。

```bash
git status          # 意図しないファイルが混ざっていないか
git diff            # 変更内容の確認（未ステージ）
```

**push 前セルフチェック:**

- この変更はタスクの目的に対して過不足ないか。無関係な変更が混ざっていないか。
- デバッグ用の `print` / `console.log` / コメントアウトした残骸が残っていないか。
- **秘密情報が入っていないか。** DB 認証情報・接続文字列・`.env`・ダンプファイル・大きなバイナリがステージされていないか（`.gitignore` に頼り切らず目視）。
- **app_db に対する書き込み・マイグレーションが混ざっていないか。** app_db は読み取り専用。Alembic リビジョンは ver2 側の自己管理 DB のみが対象。
- 触った範囲の lint / format / test（バックエンド: black+flake8+mypy+pytest / フロント: eslint+`tsc --noEmit`+vitest+`npm run build`）が通っているか。実行内容は `pyproject.toml` / `package.json` / `.github/workflows/ci.yml` を確認して合わせる。

### 2. tasks.md を更新してコミット

**タスクを完了させるコミットでは、同じコミット内で `tasks.md` の該当行を `[ ]` → `[x]` に更新する**（実装と進捗を履歴上で一致させる）。論理単位ごとに add し、Conventional Commits でコミットする。コミット規約の詳細は `references/commit-conventions.md` を参照。

```bash
git add <関連するファイル群>        # 論理単位でステージ（git add -A の前に内容を確認）
git commit               # <type>(<scope>): <subject> + footer で Task 参照
```

複数タスクぶんの変更が溜まっている場合は、タスク単位でコミットを分ける（保存ごとの細切れコミットは作らないが、無関係な変更を1コミットに混ぜもしない）。

### 3. push

```bash
git push
```

push が reject された場合（リモートが進んでいる）は `git pull --rebase` してから再度 push する。

**HTTPS 認証は `gh` に肩代わりさせる。** リモートは HTTPS なので、初回のみ `! gh auth login`（対話・"Authenticate Git ... Yes"）を実行しておくと、`git push` でユーザー名/パスワードを聞かれなくなる。認証状態は `gh auth status` で確認。手順は `references/gh-cli.md` を参照。

**CI（GitHub Actions）の確認。** `.github/workflows/ci.yml` が設定済み（main への push と手動実行で発火）。push 後は `gh run watch`（進行中をライブ監視）または `gh run list --limit 5` で結果を確認する。CI が赤くなったら放置せず、修正コミットを積んで push し直す（main 直接運用なので赤い main を残さない）。gh コマンドの詳細は `references/gh-cli.md`。

> CI は**ガード付き**構成: `backend/`（依存マニフェスト有）・`frontend/package-lock.json` が未実装の段階では該当 job を skip（灰色）し、コードが揃うと自動で有効化される。よって現段階（本体未実装）では push しても大半が skip される想定で、それは異常ではない。

### 4. チャットで報告する

proactive にコミットした場合は特に、**何をやったかをチャット側でも要約報告する**（ユーザーが気づかないうちに main が進む事故を防ぐ）。報告には以下を含める:

- コミットした subject（複数コミットなら各 subject）
- 主な変更点の要約
- push 先（main）と、CI がある場合はその結果

コミットメッセージ body に変更点を箇条書きで書いているので、報告はそれを要約する形でよい。

## 判断に迷ったときの原則

- **壊れた状態を main に push しない。** 直接運用なので push＝即 main 反映。区切り（タスク完了・テスト通過）まで待つ。
- **1 コミット = 1 つのまとまった目的**（多くは 1 タスク）。無関係な変更を混ぜない。
- **秘密情報をコミットしない。** commit 前に `git status` / `git diff --staged` で必ず確認。
- 大きく壊す可能性のある実験的変更は、例外的に一時ブランチを切って隔離してもよい（通常運用は main 直接）。

## Reference ファイル

- `references/commit-conventions.md` — Conventional Commits 規約・cc-sdd(tasks.md) との連動書式・Alembic を含む変更の扱い・コミットメッセージ例
- `references/gh-cli.md` — gh CLI の使い方（`gh auth login` による push 認証・`gh repo view`・CI の `gh run` 確認・例外的な PR/issue）
