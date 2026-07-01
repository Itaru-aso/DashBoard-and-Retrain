# gh CLI（GitHub CLI）— shisui app_ver2 での使い方

`gh` は GitHub の公式 CLI。このリポジトリは **solo・main 直接運用**なので、gh の主な用途は「push の HTTPS 認証を肩代わりさせる」ことと「CI（GitHub Actions）導入後の結果確認」。PR / issue は原則使わないが、必要になった場面のために最小限を記載する。

- 対象リポジトリ: `Itaru-aso/DashBoard-and-Retrain`（`origin`・HTTPS リモート・追跡ブランチ `main`）
- 実行場所: **Windows PC 上のローカルクローン**（`D:\0032011\GitLab\shisui\app_ver2`）。git を叩くのと同じマシン。

## 1. 認証（最初に一度だけ）

`gh auth login` は対話プロンプト。Claude Code のセッションからは `! gh auth login` と入力して手元で実行する（Claude が代行できない対話コマンド）。

推奨回答:

```
? What account do you want to log into?        GitHub.com
? What is your preferred protocol for Git operations?   HTTPS
? Authenticate Git with your GitHub credentials?        Yes
? How would you like to authenticate?           Login with a web browser  （or Paste an authentication token）
```

**要点は "Authenticate Git ... Yes"。** これで gh が git の credential helper として登録され、`git push`（HTTPS）でユーザー名/パスワードを聞かれなくなる。PAT を使う場合は `repo` スコープ（CI を見るなら `workflow` も）を付ける。

確認:

```bash
gh auth status          # ログイン済みか・スコープ・使用プロトコルを表示
```

トークンが切れた／スコープを足したいとき:

```bash
gh auth refresh -s workflow     # スコープ追加
gh auth login                   # 入れ直し（対話）
```

## 2. 日常で使う補助コマンド

```bash
gh repo view --web       # ブラウザでリポジトリを開く
gh repo view             # 説明・デフォルトブランチ・最近の情報を端末で確認
gh browse                # 現在のファイル/リポジトリを GitHub 上で開く
gh browse <path>         # 特定ファイルを GitHub 上で開く
```

push 自体は従来どおり `git push`。gh はあくまで認証と閲覧の補助であって、push の主役ではない。

## 3. CI（GitHub Actions）の結果確認

> `.github/workflows/ci.yml` を設定済み（main への push と `workflow_dispatch` で発火）。ガード付き構成で、`backend/`・`frontend/` が未実装の間は該当 job を skip する。以下で結果を確認する。

```bash
gh run list --limit 5           # 直近の実行一覧（状態・ブランチ・トリガー）
gh run watch                    # 最新（進行中）の実行をライブ監視
gh run view <run-id>            # 実行の詳細
gh run view <run-id> --log-failed   # 失敗ジョブのログだけ表示
gh run rerun <run-id>           # 再実行
```

push 後の基本動線: `git push` → `gh run watch`（or `gh run list`）で緑を確認。**赤くなったら放置せず、修正コミットを積んで push し直す**（main 直接運用なので赤い main を残さない）。

## 4. PR / issue（原則使わないが必要なとき）

solo・main 直接運用のため通常は不要。大きく壊す実験を一時ブランチ（`experiment/<説明>`）に隔離したときや、レビューを挟みたいときのみ。

```bash
# 一時ブランチを PR にする（レビュー/CI を通したいとき）
gh pr create --base main --head experiment/<説明> --fill
gh pr view --web
gh pr checks            # その PR の CI 状態
gh pr merge --squash --delete-branch   # まとまったら squash で main へ

# メモ代わりの issue
gh issue create --title "..." --body "..."
gh issue list
```

## 5. 注意

- **gh でも main 直接運用の原則は変わらない。** 壊れた状態・秘密情報を push しない、区切り（タスク完了）まで待つ、は `SKILL.md` の通り。
- gh の操作対象リポジトリは、カレントが git クローン内なら自動で `origin`（`Itaru-aso/DashBoard-and-Retrain`）になる。別リポジトリを触らないよう、実行前にカレントディレクトリを確認する。
- 認証情報（PAT）はシェル履歴やファイルに残さない。`gh auth login` の対話フロー／ブラウザ認証を使う。
