# モデル再学習ワークフロー — Tasks

> spec: `モデル再学習ワークフロー (model-retraining)`
> 配置想定: `.kiro/specs/model-retraining/tasks.md`
> 上流: `requirements.md`（M-R1〜M-R9・確定事項）・`design.md`（学習側連携の確定含む） ／ 規約: `tech.md`・`structure.md`
> 連携の事実: `2026-06-30-retraining-integration-answers.md`・`schema-spec-mapping.md`
>
> 進め方: 各タスクは **1テスト + 1実装 + 1コミット**、**RED → GREEN → REFACTOR**。
> 完了条件は `tech.md` の検証ゲート（pytest cov≥80・black・flake8・mypy／front: tsc・eslint・vitest）。
> コミットは Conventional Commits（例: `feat(retraining): ...`）。
>
> 進捗印: `[ ]` 未着手／`[~]` **参照実装あり（要結合）** ＝ コードは作成済みだが import パス調整・実環境での結合・
> テスト緑化は未了／`[x]` 完了（TDD 緑化・ゲート通過）。本セッションでタスク 0〜9 の参照実装を作成（`[~]`）。
>
> **参照実装あり**: 本機能は ver2 実装コードの素案を作成済み（`retraining_job.py`・`deployed_model.py`・
> `xxxx_create_retraining.py`・`retraining_repository.py`・`training_service.py`・`deployment_service.py`・
> `retraining_endpoint.py`・`retraining_schemas.py`・`retraining_wiring_example.py`、テスト5本）。
> import パス・DI・config は本プロジェクトのレイアウトに合わせて調整する。

## 前提 (Preconditions)

- **基盤整備**: 単一ワーカ（`uvicorn --workers 1`）・ver2 DB・**lifespan でのワーカ起動/停止**・conftest（2 DB）。
- **`エッジPC管理`**: 有効エッジPC（host/username/password/**model_port**）を `find_enabled()` で取得。
- **`色マスター・色ライフサイクル`**: 起票時の `color_master` 存在チェック（`exists_by_tuple`）。
- **`training/` パイプライン**（`pipline.py` を **subprocess**・CWD=`training/`・**GPU 2枚**は学習側が自動割当）。
- **同一性はフルタプル（案A）**。学習起動は **color_no のみ**渡す（学習側は size/chain/tape 未使用）。
- 画像は**別機能が `1_download` に事前配置**（収集スコープ外）。成果物 ONNX は所定パス。
- テストでは **subprocess・FTP・プロセス kill はモック**（実学習・実配信はしない）。

---

## タスク (Tasks)

- [x] **0. 学習側の薄い改修（`training/pipline.py`・ロジック不変）**
  - `execute()` の **FTP ダウンロードを `common.skip_download` でガード**（608–613）、
    **FTP アップロードを `common.skip_upload` でガード**（689–690）。`conf/config.yaml` の `common` に両既定 `false` を追記。
  - （任意）末尾の `パイプライン完了` 前に **ONNX 未生成なら `sys.exit(1)`**、節目に `[PROGRESS] ...` を print。
  - テスト（学習リポジトリ側・任意）: skip_download/skip_upload で DL/配信が呼ばれないこと（FTP モック）。
  - commit: `feat(training): add skip_download/skip_upload flags (no logic change)`

- [x] **1. マイグレーション: `retraining_job` ＋ `deployed_model`**（ver2 DB）
  - `retraining_job`（フルタプル・`status`〔CHECK 制約〕・各時刻・error・ONNX パス・created_by・索引）、
    `deployed_model`（**フルタプル ユニーク**・`job_id` FK・ONNX パス・`deploy_status`・`deploy_detail`・`deployed_at`）。
  - テスト（integration）: upgrade/downgrade、`deployed_model` のフルタプル ユニークを制約が弾く。
  - Refs: M-R7, M-R8.3 ／ commit: `feat(retraining): add retraining_job and deployed_model migration`

- [x] **2. ORM モデル**
  - `src/models/retraining_job.py`（`RetrainingJob`・`JobStatus`・`TERMINAL_STATUSES`）、
    `src/models/deployed_model.py`（`DeployedModel`・`DeployStatus`）。
  - テスト（integration）: round-trip・status CHECK・FK・`is_terminal`。
  - commit: `feat(retraining): add ORM models`

- [x] **3. Pydantic スキーマ**
  - `src/schemas/retraining.py`: 起票（フルタプル＋created_by）・一覧/詳細・キャンセル・現行配信・配信結果。
  - テスト（unit）: 検証（正常／異常）。
  - Refs: M-R1 ／ commit: `feat(retraining): add schemas`

- [x] **4. Repository**
  - `src/repositories/retraining_repository.py`（ver2）: ジョブ作成（QUEUED）・状態更新（running/completed/failed/cancelled）・
    履歴一覧（filter/paging）・`list_active`（復旧用）・`deployed_model` upsert（フルタプル）・現行取得。
  - テスト（integration）: 作成・状態遷移の永続・一覧/絞り込み/ページング・list_active 順序・deployed upsert（上書き・ユニーク）・取得。
  - Refs: M-R7, M-R8.3 ／ commit: `feat(retraining): add retraining repository`

- [x] **5. Service: `training_service`（キュー・実行・キャンセル）**
  - シングルトン。`main.py` lifespan で **asyncio キュー＋単一ワーカ**起動・**FIFO・同時1本**。復旧（消えた RUNNING→FAILED・QUEUED 再投入）。
  - 実行: `python pipline.py common.target_color=<color_no> common.pipeline_mode=train
    common.skip_download=true common.skip_upload=true color.mlflow.enabled=false monochro.mlflow.enabled=false`
    を **CWD=`training/`・`start_new_session=True`** で起動。標準出力を**1行ずつ素通し**で進捗配信（揮発）。
  - **成功判定（終了コード非依存）**: 両 mode の **ONNX 生成有無**＋標準出力の **`パイプライン完了`** マーカー。
  - キャンセル: QUEUED は除外、RUNNING は**プロセスグループごと kill**（SIGTERM→猶予→SIGKILL）。状態は DB を正に永続。
  - テスト（integration・**subprocess/kill モック**）: COMPLETED（ONNX＋マーカー）／FAILED（ONNX 欠落・マーカー欠落）／
    起動コマンド・cwd・start_new_session／FIFO・同時1本／QUEUED キャンセルは起動されず CANCELLED／進捗素通し。
  - Refs: M-R2, M-R3, M-R4, M-R5, M-R6, M-R7 ／ commit: `feat(retraining): add training_service (queue, subprocess, cancel)`

- [x] **6. Service: `deployment_service`（配信・現行モデル・学習と分離）**
  - `deploy_job(job_id)`: COMPLETED の ONNX を有効エッジPC全台へ **ver2 自前 ftplib** で送信（`model_port`・
    リモート名は検査PC互換の **`{color_no}_{mode}_model.onnx`** を FTP ルート直下）→ `deployed_model` をフルタプルで upsert。
    集約: 全台成功=SUCCESS／一部失敗=PARTIAL／全失敗=FAILED（再配信可・ジョブ成功は覆さない）。
  - v1 は `make_auto_deploy_hook` を `training_service.on_completed` に渡し **COMPLETED で自動配信**。
  - テスト（integration・**FTP フェイク注入**）: 全台成功 SUCCESS（送信数・色番名・model_port）／一部失敗 PARTIAL／全失敗 FAILED／
    エッジPCなし FAILED／非 COMPLETED は ValueError／ONNX 欠落は FileNotFoundError／deployed upsert。
  - Refs: M-R8 ／ commit: `feat(retraining): add deployment_service (ver2 ftplib, separated)`

- [x] **7. WebSocket 進捗**
  - `WS /api/retraining/jobs/{id}/progress`: `training_service.subscribe` を購読し**行を素通し**配信、None で close（揮発）。
  - テスト（api）: 行が流れる・None で閉じる・切断時 unsubscribe。
  - Refs: M-R6 ／ commit: `feat(retraining): add websocket progress`

- [x] **8. API: エンドポイント + ルーター登録**
  - `src/api/retraining_endpoint.py`（`main.py` 登録・Basic 認証ゲート）: `POST /jobs`（**color_master 存在チェック→404**）・
    `GET /jobs`（filter/paging）・`GET /jobs/{id}`・`POST /jobs/{id}/cancel`（終端は **accepted=false** で冪等）・
    `GET /deployed`・`POST /jobs/{id}/deploy`（将来の手動配信）。
  - テスト（api / TestClient）: 起票（存在チェック 404・enqueue 呼出）・一覧・詳細・キャンセル（終端は accepted=false）・
    現行配信・手動配信・認証。
  - Refs: M-R1, M-R5, M-R7, M-R8, M-R9 ／ commit: `feat(retraining): add retraining API endpoints`

- [x] **9. フロント: 再学習画面**
  - `frontend/src/api/retrainingApi.ts`、WS フック、TanStack Query フック、`frontend/src/pages/Retraining.tsx`
    （履歴一覧・色を選んで起票・**WS ライブ進捗（素通しログ）**・キャンセル・現行配信モデル表示）。
  - テスト（Vitest + Testing Library）: 一覧/起票・WS 進捗表示・キャンセル・現行配信表示。
  - Refs: M-R1, M-R5, M-R6, M-R7, M-R8 ／ commit: `feat(retraining): add retraining screen`

- [x] **10. 配線・仕上げ: lifespan 配線＋検証ゲート**
  - `main.py` lifespan で `deployment_service` 生成→`init_training_service`（on_completed に自動配信フック）→`start()`、終了で `stop()`。
    `config.py` に `training_dir`/`training_model_dir`/`training_python`。`dependencies.py` に DI（color_master/deployment）。
  - 全テスト・`black`/`flake8`/`mypy`、front の `tsc`/`eslint`/`vitest` をグリーンに。カバレッジ 80% 以上。
  - commit: `chore(retraining): wire lifespan and satisfy verification gate`

- [x] **11. フロント: 画面デザイン刷新（`ui-shell` 準拠・見た目のみ）**
  - モックアップ（`Shisui Dashboard (standalone).html`）を参照し `Retraining.tsx` をダーク基調に作り直す。
    モックアップは「サイズ/チェーン/色番を複数選択してまとめて1回実行」という単一パネルだが、
    本 spec は**単一フルタプルごとにジョブを起票**する運用モデル（履歴一覧・WSライブ進捗・キャンセル・
    現行配信モデル一覧を含む）のため、モックアップの構造には簡略化しない。**既存機能はすべて残し、
    見た目（パネル化・ダーク配色・JetBrains Mono表示・ライブログのモノスペース表示）のみ合わせる**
    （brainstormingで確認済み）。AIメトリクスカード（データソース不明）は本specに無いためスコープ外。
  - テスト: 既存7テストが無変更で通ることを確認。
  - 代替検証: `npm run dev`（バックエンド接続）で目視確認。
  - Refs: M-R1, M-R5, M-R6, M-R7, M-R8 ／
    commit: `feat(retraining): restyle retraining screen with ui-shell design`

---

## 追加タスク: データセット参照方式の変更（FTP→export_root）

> 出典: `.kiro/specs/retraining/dataset-export-root-migration.md` v1.4（設計レビュー完了・決定事項1〜24）。
> CLAUDE.md例外（決定12・20）はユーザー承認済み。対象: `training/dataset/`・`training/utils/ftp_common.py`・
> `training/utils/image_preprocessing.py`・`training/pipline.py`のオーケストレーション部分・
> `training/train/monochro.py`のDataLoader構築部分のみ。学習アルゴリズム本体（損失関数・モデル構造・
> 学習ループ・color側ロジック）は対象外・変更不可。
> 依存順: 12 → 13 → 14 → 15 → 16、17 は 14 と並行可・15 に依存（決定24でtapeを15が配線するため）、
> 18 は要確認待ちで着手しない。

- [x] **12. `training/dataset/manager.py`: export_root直接変換への書き換え**
  - `1_download`/`2_staging`を廃止し、`export_root/{dataset_id}/metadata.json` + `binary/{color_no}/{category_id}/`を
    直接読んで`3_pool`（good_pool/defect_pool）へ変換する新選定ロジックに書き換える。
    `metadata.json`の`category[].on_class`でgood/defect判定、`invalid_flg=1`のカテゴリはpool構築から除外。
  - ファイル名正規化（`_top`→`_0`、`_bottom`→`_1`）をpoolコピー時に実施（`utils/split_manager.py`の
    `_extract_product_id`が期待する`_<数字>`接尾に揃える。`split_manager.py`自体は無改修で流用）。
  - リサイズ工程（`cv2.resize`、config `image_size`相当）は`manager.py`側に残す（crop・分割の呼び出しは不要）。
  - `common.target_color`と`binary/{color_no}/`フォルダ名の不一致は明確なエラーとする（サイレント0件処理は禁止）。
  - テスト（`training/tests/dataset/`・フィクスチャexport_root）: 検証基準1・2・3。
  - Refs: 決定1, 2, 3, 7, 8, 9, 11 ／ commit: `feat(training-dataset): export_root直接変換への選定ロジック書き換え`

- [x] **13. FTP入力側の削除 + `pipline.py`オーケストレーション修正 + `config.yaml`整理**
  - **既存タスクとの関係**: タスク0（`[x]`完了済み）が追加した`common.skip_download`ガード付きのFTP経路を
    含め、入力側FTPを本タスクで全削除する（タスク0の成果は本タスクで置き換わる。`skip_download`キー自体は
    backendのCLI override互換のため残すが、コード上はno-op化）。
  - `training/dataset/ftp_download.py`（`FTPManager`/`MultiFTPManager`）を削除。`training/utils/ftp_common.py`は
    `AnnotationDownloader`・`GOOD_KINDS`/`DEFECT_KINDS`のみ削除し、出力側で使う`upload_file_to_ftp`等は残す。
    `training/dataset/__init__.py`のre-exportを追随修正。`training/tests/dataset/test_ftp_download.py`も削除。
  - `training/pipline.py`: `MultiFTPManager`のimport・`__init__`の`self.ftp_manager`・`execute()`内のFTP DLループを削除。
    **出力側FTP（`deploy.upload_model`）は変更しない**。
  - `pipeline_mode=stage_only`モード（`2_staging`廃止に伴い実装が壊れるため）はユーザー承認により削除。
    **フォローアップ（未対応）**: `docs/superpowers/specs/2026-07-21-training-modular-monolith-migration-design.md`・
    `docs/reference/retraining-integration-answers.md`が`pipeline_mode=<train|stage_only>`を
    pipeline-edge契約として明文化したままになっている。次にこれらのドキュメントに触る際は
    stage_only削除を反映すること。
  - `training/conf/config.yaml`: `download_dir`・`staging_dir`（`utils/paths.py`の`_KEYS`からも削除）・`ftp_common`
    （入力側local_root）を削除し、`common.export_root`/`common.dataset_id_monochro`/`common.dataset_id_color`/
    `common.margin_export_root`/`common.dataset_id_monochro_margin`のCLIオーバーライド用キーを追加。
    **`ftp_hosts`は出力側`deploy.upload_model`が使うため削除せず維持**（当初「入力側専用」と誤認したが
    `deploy/ftp_upload.py`が読んでいることをコミット前に確認し復元）。
  - テスト: 検証基準8（`ftp_download.py`/`AnnotationDownloader`への参照が残っていないことをgrepで確認）・
    検証基準9（`deployment_service.py`側の出力FTPテストに変更が及んでいないことを確認）。
  - Refs: 決定10, 12 ／ commit: `refactor(training-pipline): FTP入力側を削除しexport_root参照へ一本化`

- [x] **14. backend: `TRAINING_EXPORT_ROOT`/`TRAINING_MARGIN_EXPORT_ROOT`設定 + dataset_id解決**
  - `backend/src/config.py`に`TRAINING_EXPORT_ROOT`/`TRAINING_MARGIN_EXPORT_ROOT`を既存`TRAINING_DIR`等と
    同パターンで追加。`main.py`のlifespanで`TrainingConfig`（`export_root`/`margin_export_root`）へ配線。
  - 配置場所は`training_service.py`直接実装を採用（`TrainingConfig`と密結合のため新規モジュールは不要と判断）。
    モジュール関数`_find_dataset_id(export_root, target_name)`が`export_root`配下を走査し`metadata.json`の
    `name`一致で dataset_id（サブディレクトリ名）を返す。`TrainingConfig.resolve_dataset_id(mode, size, chain)`
    （export_root・mono/color両対応）と`resolve_margin_dataset_id(size, chain)`（margin_export_root・
    monochro専用）でラップ。見つからない場合はいずれも空文字を返す（致命的にするかはCLI override配線側＝
    タスク15/16の責務、本タスクの解決関数自体は主/マージンで同一の「見つからなければ空文字」動作）。
  - **フォローアップ（未対応）**: `TrainingConfig.build_command`の`data_root`上書きブロックが
    `common.download_dir`/`common.staging_dir`/`monochro.raw_image_root={data_root}/1_download`という
    タスク13で廃止済みのキーを今も生成する（`test_build_command_overrides_data_paths_when_data_root_set`が
    その文字列を検証中）。害はない（存在しないキーを新規作成するだけ）が、export_root系に揃える修正は
    build_commandを触るタスク15で行う。
  - テスト（`backend/tests/integration/test_training_service.py`・フィクスチャディレクトリ）: 検証基準4
    （main/marginのdataset_id解決・マージン側が見つからない場合の空文字フォールバック）。
  - Refs: 決定4, 5, 13 ／ commit: `feat(training-service): export_root/export_root_marginのdataset_id解決を追加`

- [x] **15. backend: `_run_job`/`build_command`のCLI override配線（size/chain/tape配線）**
  - **既存タスクとの関係**: タスク5（`[x]`完了済み）は学習起動に`common.target_color`（color_noのみ）を渡す
    設計だったが、本タスクでsize/chain/tapeも渡すよう配線を追加する（タスク5の起動コマンド構築を拡張）。
  - `_run_job`が`_size`/`_chain`/`_tape`として捨てていたsize/chain/tapeを`color_no, size, chain, tape = tup`に
    変更。`tape`はCLI overrideには使わない（dataset_id解決のname規約に含まれない）が、`[STATUS] RUNNING`
    ログ行に含める形で保持し、完了後のONNXパス解決（タスク17）・配信ファイル名解決（タスク18・保留）に
    引き続き使えるようにした。
  - `build_command(color_no, size, chain)`に署名変更。`resolve_dataset_id`/`resolve_margin_dataset_id`
    （タスク14で実装済み）を呼び、`common.dataset_id_monochro`/`common.dataset_id_color`/
    `common.dataset_id_monochro_margin`・`common.export_root`/`common.margin_export_root`のいずれも
    **解決/設定できた場合のみ**付与する（`key=`空値はOmegaConfで`None`になりconfig.yaml側の空文字既定を
    上書きしてしまうため。advisorレビューで発見・`OmegaConf.from_dotlist(['x='])`で実測確認）。
  - **付随修正**: `data_root`設定時のオーバーライドから、タスク13で廃止済みの`common.download_dir`/
    `common.staging_dir`を削除（送っても実害はないが死んだキーなので整理）。`monochro.raw_image_root`は
    現状`{data_root}/1_download`のまま維持（タスク16で`export_root_margin`の解決済みパスに差し替えるまでの
    暫定。TODOコメントを付記）。
  - テスト（`backend/tests/integration/test_training_service.py`）: 検証基準5
    （dataset_id override省略/付与の条件分岐・export_root系の条件付与・DB取得size/chainからの配線を
    確認する`test_command_contains_expected_overrides`拡張、他4件新規）。
  - Refs: 決定6, 14, 24 ／ commit: `feat(training-service): size/chain/tapeをbuild_commandまで配線`

- [x] **16. `training/train/monochro.py`: マージンあり/なしDataLoader合体（monochro専用）**
  - `use_raw_shift_dataset=true`時の旧`raw_image_root`（`1_download`）参照を全面撤廃。新規ヘルパー
    `_resolve_margin_good_root(cfg, color_num)`が`common.margin_export_root`/`dataset_id_monochro_margin`
    からマージンあり画像の`binary/{color}/{good_category_id}/`を解決する（on_class='0'・invalid_flg!='1'の
    カテゴリのみ、複数見つかった場合は明確なエラー、見つからない場合はNoneでフォールバック）。
    `RawShiftImageFolder`・`process_image`のcrop式自体は変更なし（未分割・生センサー座標系のため）。
  - 新規`_FlatGoodImageFolder`（サブフォルダ無しのフラット画像フォルダ用Dataset。`ImageFolderWithoutTarget`
    はtorchvision`ImageFolder`前提＝クラスサブフォルダ必須のため使えない）でexport_root
    （マージンなし）の`dataset_path/train/good`・`dataset_path/test/good/images`を読む。
  - train = マージンありgood画像全量（見つかった場合。±crop_shift_max_pxランダムシフト）
    + tight train（シフトなし）。val = tight testのみ（マージン混入なし）。旧`torch.randperm`独自
    80/20分割は撤廃し、export_rootの既存train/test分（`split_pool_to_dataset`の出力）を使う置き換えとして扱った。
  - defectカテゴリ（on_class=1）はmonochroのDataLoaderに一切含めない（マージン側はgoodカテゴリのみ解決、
    export_root側もtrain/good・test/good/imagesのみ参照）。colorのDataLoader構築・学習ロジックは無変更
    （`color.py`は今回未編集）。
  - テスト容易化のため、データセット構築部分を`_build_datasets(...)`関数として抽出（DataLoader構築部分の
    範囲内。損失関数・モデル構造・学習ループは touch していない）。`use_raw_shift=false`時の既存80/20分割は
    ロジック無変更（バイト単位で移動のみ）。
  - **付随修正**: `training/conf/config.yaml`の`monochro.raw_image_root`キー（誰も読まなくなった）を削除。
    backendの`build_command`から対応する`monochro.raw_image_root=...`オーバーライド（タスク15のTODOで
    暫定維持していたもの）も削除し、テストを更新。
  - テスト（`training/tests/train/test_monochro_export_root_margin.py`・フィクスチャ）: 検証基準6・7
    （新規9テスト）。7b・10（color無変更）は既存colorテストのgreen維持で確認（training/フルスイート
    49→58件、全パス）。
  - Refs: 決定15-20 ／ commit: `feat(training-monochro): マージンあり/なしデータのDataLoader合体`

- [x] **17. backend: ONNX保存パスのタプル管理（ステージング→最終パス移動）**
  - `TrainingConfig.onnx_path(color_no, mode)`（学習側ステージング出力先）は不変のまま、新規
    `TrainingConfig.final_onnx_path(color_no, size, chain, tape, mode)`が最終パス
    `model_dir/{color_no}/{size}_{chain}_{tape}/{mode}/{color_no}_{size}_{chain}_{tape}_{mode}_model.onnx`
    を組み立てる（tape空文字は空文字のまま連結・プレースホルダなし）。
  - `_run_job`の完了判定後、`TrainingService._promote_onnx`（`shutil.move`+`os.makedirs`）がステージング
    パスから最終パスへファイルを移動し、`mark_completed(job_id, ...)`には移動後の最終パスを渡す
    （タプル単位で最新のみ保持・同タプルの既存ファイルは上書き）。`training/`側（`deploy/model_export.py`）
    は変更しない。
  - **付随修正**: 移動失敗時（`OSError`）はFAILEDとして記録する（training自体は成功していても、
    タプル別最終パスへの配置が失敗した場合はジョブとして未完了とみなす。ADRに明示はないが決定22の
    「backendが完了後に移動する」を安全に実装する上で必要と判断）。モジュールdocstringの
    「画像は別機能が1_downloadに事前配置」という記述もexport_root前提に更新。
  - テスト（`backend/tests/integration/test_training_service.py`）: 検証基準11（`final_onnx_path`の
    tuple組み立て・tape空文字ケース）・12（完了処理のステージング→最終パス移動＋同一タプル2回連続完了
    での上書き）ともに実行確認済み（Docker起動後、`test_training_service.py`全22件PASS。うち
    `test_completion_promotes_onnx_to_final_tuple_path_and_overwrites_on_rerun`が検証基準12に対応）。
    `deployment_service.deploy_job`は`job.onnx_monochro_path`/`onnx_color_path`（DB保存値）を読む実装
    であることを確認済みのため、`mark_completed`に最終パスを渡す変更が自動配信フローと整合することも
    確認済み。
  - Refs: 決定21, 22 ／ commit: `feat(training-service): ONNX保存パスのタプル管理`

- [ ] **18.（保留・要確認待ち）エッジPC配信ファイル名のタプル化**
  - **既存タスクとの関係**: タスク6（`[x]`完了済み）が実装した`{color_no}_{mode}_model.onnx`固定の
    リモート名は、着手条件が満たされるまで現状のまま維持する（本タスク着手時に置き換わる）。
  - `deployment_service.py:102-104`の`_remote_name(color_no, mode)`
    （`{color_no}_{mode}_model.onnx`）を`{color_no}_{size}_{chain}_{tape}_{mode}_model.onnx`に変更する。
    配信メカニズム・配信先パス（`remote_dir`等）自体は変更しない。
  - **着手条件**: エッジPC側の検査アプリケーション（リポジトリ外）が新ファイル名を受理できるか未確認。
    確認が取れるまで実装しない（`dataset-export-root-migration.md`未解決パラメータ参照）。
  - テスト（着手後）: 検証基準13。
  - Refs: 決定23 ／ commit: 未定（保留中）

---

## トレーサビリティ (Requirements ↔ Tasks)

- M-R1（起票・手動・存在チェック）→ 3, 8, 11 ／ M-R2（キュー・同時1）→ 5
- M-R3（subprocess・GPU・skip_download/upload）→ 0, 5 ／ M-R4（状態遷移・成功判定）→ 5 ／ M-R5（キャンセル）→ 5, 8, 11
- M-R6（WS 進捗・素通し）→ 5, 7, 9, 11 ／ M-R7（記録・履歴・復旧）→ 1, 2, 4, 8, 11
- M-R8（配信・現行モデル・学習と分離）→ 0, 1, 6, 8, 11 ／ M-R9（認証）→ 8

> 注: 実学習・実 FTP・プロセス kill はテストでモック。CUDA は学習側 cu121→**cu128 系へ入替**前提（Blackwell・`tech.md`）。
> 配信先 ONNX のリモート名は検査PC互換のため color_no ベース固定（ver2 の記録はフルタプル＝案A）。
> **タスク18（配信ファイル名タプル化）の着手後は本注記を更新すること。**

### データセット参照方式移行（ADR決定 ↔ Tasks）

- 決定1〜3・7〜9・11（export_root参照の基本方針）→ 12 ／ 決定10・12（FTP削除・CLAUDE.md例外）→ 13
- 決定4・5・13（per-mode解決・dataset_id解決・env）→ 14 ／ 決定6・14・24（CLI override配線・size/chain/tape）→ 15
- 決定15〜20（マージンあり画像・monochro DataLoader）→ 16 ／ 決定21・22（ONNXパスのタプル管理）→ 17
- 決定23（配信ファイル名タプル化・保留）→ 18
