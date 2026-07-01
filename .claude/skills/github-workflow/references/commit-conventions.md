# コミット規約・cc-sdd 連動・Alembic の扱い

main 直接運用のため、コミットの単位と説明が履歴の読みやすさを直接左右する。以下を守る。

> **規約の適用範囲（重要・意図的な上書き）**
> - 本 repo は **Conventional Commits（`<type>(<scope>): <subject>`）を正**とする。これはグローバル CLAUDE.md の「コミットは `種別: 概要`（日本語）」規約を、**本 repo に限り意図的に上書き**する決定である（履歴を機械的に辿れる形に統一するため）。subject の語（日本語/英語）は repo 内で統一する。
> - 一方、**コミット末尾の `Co-Authored-By` トレーラー付与（グローバル規約）は維持する**。Conventional Commits 化と Co-Authored-By は両立させる（footer に両方入れる）。

## コミットメッセージ（Conventional Commits）

書式:

```
<type>(<scope>): <subject>

- 変更点1
- 変更点2
- （必要なら）なぜ / 背景
- tasks.md: <番号> を完了に更新

Task: <spec>/<番号>
Co-Authored-By: <セッションのモデル> <noreply@anthropic.com>
```

- **type**: `feat` / `fix` / `refactor` / `test` / `docs` / `chore` / `perf` / `style`。
- **scope**: 原則 spec 名（`daily-metrics` など）。spec 横断の基盤なら対象モジュール名（`repository`, `orm`, `api`, `ws`, `ui` など）。
- **subject**: 命令形・現在形で簡潔に。文末にピリオドを付けない。日本語/英語はリポジトリ内で統一する。
- **body**: **変更点を箇条書きで列挙する（「何を」を明記する）。** Claude が代わりにコミットするため、後から diff を開かずに履歴だけで何をやったか分かる状態にすることを優先する。挙動の意図や背景（なぜ）が自明でない場合は、それも箇条書きに加える。tasks.md を更新したらその旨も1行入れる。
  - 箇条書きは「ファイル一覧」ではなく「意味のある変更のまとまり」で書く（例: 「daily_metrics への集計サービスを追加」であって「service.py を編集」ではない）。
  - 変更が subject だけで完全に自明な小さなコミット（typo 修正・軽微な整形など）は body を省略してよい。
- **footer**: 完了タスクを `Task: <spec>/<番号>` で参照し（下記）、その下に `Co-Authored-By: <セッションのモデル> <noreply@anthropic.com>` トレーラーを付ける。両方を footer に置く。

### 例

**例1** — daily_metrics の集計サービスを実装
```
feat(daily-metrics): implement 3-KPI aggregation service

- daily_metrics への NG率/虚報率/見逃し率の集計サービスを追加
- annotation_item → dataset_category_item.on_class で正解ラベルを導出
- monochro 画像を集計対象から除外
- 対応するリポジトリメソッドとユニットテストを追加
- tasks.md: 2.3 を完了に更新

Task: daily-metrics/2.3
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

**例2** — NG率集計で monochro 画像を二重計上していたのを修正
```
fix(daily-metrics): exclude monochro images from NG rate double-count

- 正解ラベル導出時に monochro 識別を通しておらず二重計上していたのを修正
- 回帰防止のテストケースを追加

Task: daily-metrics/4.1
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

**例3** — steering ドキュメント（技術スタック）の更新のみ（body 省略可）
```
docs(steering): update tech stack with daily_metrics table
```

## cc-sdd（tasks.md）との連動

`.kiro/specs/<spec>/tasks.md` は `[ ]`（未着手）/ `[~]`（作業中）/ `[x]`（完了）でタスク管理している。Git 履歴と進捗を一致させるため:

1. **タスク完了コミットで tasks.md も更新する。** タスクを完了させる実装コミットの中で、同じコミットとして該当行を `[x]` に変える。実装だけ入れて進捗更新を別コミットにしない。
2. **着手時に `[~]` へ。** 作業を始めたら該当行を `[~]` に。まだ push する区切りでなければ push はしない。
3. **完了タスクを footer で参照する。** どのコミットがどのタスクかを機械的に辿れるよう、footer にタスク番号を書く。

   ```
   feat(daily-metrics): implement 3-KPI aggregation service

   Task: daily-metrics/2.3
   Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
   ```

4. **spec 文書自体の変更は `docs` type。** requirements.md / design.md / tasks.md だけの更新は `docs(<spec>): ...`。

## ステージングの粒度

- `git add -A` の前に必ず `git status` / `git diff` で内容を確認する。
- 無関係な変更が同時に存在する場合は、`git add <path>` や `git add -p` で論理単位に分けてコミットする。
- 保存のたびに細切れコミットを作らない。区切り（タスク完了）でまとめる。

## Alembic を含む変更の扱い

- Alembic リビジョンは **ver2 側の自己管理 DB のみ**が対象。app_db（読み取り専用）に対して autogenerate を実行しない／マイグレーションを作らない。
- `alembic revision --autogenerate` の生成物は鵜呑みにせず、差分（追加/削除カラム・型・インデックス・`down_revision` の連なり）をレビューしてからコミットする。
- マイグレーションを含むコミットは、subject でそれが分かるようにする（例: `... add initial migration`）。可能ならスキーマ変更とアプリ側コードを分けてコミットする。

## 例外的にブランチを使う場合

通常は main 直接だが、大きく壊す可能性のある実験的変更は一時ブランチに隔離してよい。その場合のブランチ名は `experiment/<短い説明>` とし、まとまったら main に取り込む（squash して 1 コミットにすると履歴が整う）。
