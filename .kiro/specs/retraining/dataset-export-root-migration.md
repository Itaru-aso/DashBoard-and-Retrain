# training/ データセット参照方式の変更（FTP→export_root） v1.7

> 位置づけ: `retraining` spec の `design.md` を上書きせず、データ取得元の切替に関する意思決定記録（ADR相当）として独立管理する。
> 注意: 本ドキュメントで削除対象とする FTP は **training/ が学習用画像を取得する入力側FTP**
> （`training/dataset/ftp_download.py` の `FTPManager`、`training/utils/ftp_common.py` の
> `AnnotationDownloader`）であり、`deployment_service.py` が ONNX をエッジPCへ配信する
> **出力側FTP**（`design.md` に記載）とは無関係。**出力側FTPの配信メカニズム・配信先パスは変更しない**。
> ただし v1.4（決定23）で**配信ファイル名のみ**タプル化する変更を加える（エッジ側の受理可否は未確認・要確認事項）。

## 目的 / 背景
`training/` の学習パイプラインは現状 FTP サーバから `good`/`auto_good`（正常）・`somemura`/`cutmiss`等（不良）というフォルダ名ベースで画像を取得し、pool へ振り分けている。この経路には日付範囲・`use_flg`・DBの正解情報（`on_class`）による選定が一切なく、全期間を毎回走査する非効率な実装になっている。

新たに `training/export_root/{dataset_id}/binary/{color_no}/{category_id}/` という、別機能（本タスクのスコープ外）が生成するUUIDベースの構造が既に用意されつつある。今回は **training/ 側の参照元を FTP から export_root に切り替える**。

さらに調査の過程で、`training/train/monochro.py` の `RawShiftImageFolder`（位置ズレ耐性のためのシフトaugmentation。カメラ取付・製品物理位置のばらつき吸収を目的とする）が生の未加工フレームに依存しており、export_root（トリミング・分割済み・マージンなし）だけでは動作不能になることが判明した。これに対応するため、検証段階に取得済みの「マージンあり」固定データプールを別ソースとして扱う設計を追加した（v1.2）。

また、UIから渡すべき引数の調査に伴い、**既存のONNX保存パスがcolor_noのみに依存し、size/chain/tapeを反映していない**ことが判明した（`.kiro/specs/retraining/design.md`は「同一性はフルタプルで保持する」と明記しているにもかかわらず、物理ファイルパスはcolor_noのみで決まる）。このため同一color_noで異なる(size,chain,tape)の再学習が実行されると、後続ジョブが前ジョブのONNXを物理的に上書きしてしまう。これを修正する設計を追加した（v1.4）。

## 決定事項

### データ参照の基本方針（v1.0/v1.1から継続）
1. **スコープ境界**: `export_root`（および後述のマージンあり `export_root_margin` 相当）への書き出し処理（生成側）は本タスクの対象外。今回は training/ 側が読みに行く参照側のみを変更する。
2. **DB問い合わせは一切行わない**: `training/`にも`backend/`にも、この機能のための新規DBモデル・新規クエリを追加しない。`export_root/{dataset_id}/metadata.json`をファイルI/Oで読むことで、size/chain/mode・on_class・invalid_flgのすべてを取得する。
   - 理由: 対象データセット総数が20未満で低頻度更新のため、全件ファイルスキャンのコストは無視できる。DBモデル・Repository・マイグレーション等の新規実装が不要になり、変更範囲が縮小する。
3. **metadata.json のスキーマ（確認済み）**:
   ```json
   {
     "id": "<dataset_id (UUID)>",
     "name": "<mode>_<size>_<chain>",
     "description": null,
     "created_at": "...", "updated_at": "...",
     "category": [
       {
         "category_id": "<UUID>",
         "category_label_name": "...",
         "output_id": "...",
         "on_class": "0|1",
         "invalid_flg": "0|1",
         "version_no": "..."
       }
     ],
     "provenance": { "project_id": "...", "project_name": "..." }
   }
   ```
   - `name` = `{mode}_{size}_{chain}`。アンダースコア区切り固定フォーマット（例: `monochro_5_YY`）。`mode`は`"monochro"`/`"color"`。`size`/`chain`は英数字のみでアンダースコアを含まない。
   - **`name`はデータセット生成側の仕様として一意性が保証される**（同一(mode,size,chain)に対し複数のdataset_idフォルダが同時に存在することはない）。tiebreakルールは不要。
4. **1ジョブ=monochro/color両mode対応**: 再学習1ジョブは monochro/color の対を学習対象とするため、`dataset_id`の解決は mode ごとに（=2回）行う。
5. **dataset_id解決処理は backend が実施**: backend（`training_service.py`等）が `TRAINING_EXPORT_ROOT` 配下を走査し、`metadata.json`の`name`が目的の`{mode}_{size}_{chain}`と一致する`dataset_id`をmode別に検出する。
   - 理由: `training/`にDB接続を一切追加しない既存方針を維持しつつ、export_rootのパス知識をbackend起動時のconfig（既存`TrainingConfig`と同種）に閉じ込める。
6. **manifestファイルは使わず、単純なCLIオーバーライドで伝達**: backendは解決した`dataset_id`（mode別・マージン含む）と各exportルートの絶対パスを、既存のHydra dotlist overrideと同じ形式の単純な文字列として`training/`に渡す。
   - `common.export_root=<path>`
   - `common.dataset_id_monochro=<uuid>` / `common.dataset_id_color=<uuid>`
   - `common.margin_export_root=<path>`（`TRAINING_MARGIN_EXPORT_ROOT`から）
   - `common.dataset_id_monochro_margin=<uuid or 空文字>`（見つからない場合は空文字＝マージンなし学習にフォールバック。§「マージンあり画像への対応」参照）
   - 理由: 渡す情報が単純な文字列のみのため、JSON manifestという中間ファイルを増やす必要がない。
7. **on_class・invalid_flgの解釈は training/ 側が担う**: `training/`（`dataset/manager.py`）が`export_root/{dataset_id}/metadata.json`を自ら読み、`category_id → on_class`でgood/defect判定し、**`invalid_flg=1`のカテゴリはpool構築から除外する**。マージンあり画像を読む場合も同じロジックを`export_root_margin`側のmetadata.jsonに適用する。
   - 理由: `binary/`配下の画像を読むのと同じファイルI/Oの範囲内であり、DB依存ではないため既存方針と矛盾しない。
8. **`color_no` は既存の `common.target_color` override をそのまま使用**: `common.target_color`の値（ゼロ埋め済み文字列、例`"001"`）が`binary/{color_no}/`のフォルダ名と完全一致する前提。変換ロジックは追加しない。不一致の場合は明確なエラーとする（黙って0件処理にしない）。
9. **catalog/current.json は使用しない**: `training/`は`binary/`配下のファイルと`metadata.json`のみで完結させる。
10. **FTP経路（入力側）は完全削除**: `training/dataset/ftp_download.py`（`FTPManager`）、`training/utils/ftp_common.py`（`AnnotationDownloader`・`GOOD_KINDS`/`DEFECT_KINDS`）を削除し、export_root参照に一本化する。関連する`config.yaml`の`ftp_hosts`/`ftp_common`/`download_dir`等の設定項目も削除する。**出力側FTP（`deployment_service.py`のONNX配信）は対象外・変更しない。**
    - **付随する変更（削除に必然的に伴うもの）**: `training/pipline.py`は`from dataset import DatasetManager, MultiFTPManager`（`MultiFTPManager`側の削除に伴いimport修正が必要）と、FTPダウンロードステージ（`execute()`内、ダウンロード呼び出し部分）を持つ。FTPモジュール削除に伴い、これらオーケストレーション部分（import文・ダウンロードステージの呼び出し）も修正が必要。学習アルゴリズム本体は含まれないため決定12の例外の範囲内とする。
11. **中間ディレクトリ構造の簡素化＋ファイル名正規化＋リサイズの保持**: `1_download`/`2_staging`は廃止。`training/dataset/manager.py`の選定ロジックを export_root（binary/ + metadata.json）→ `3_pool`（good_pool/defect_pool）への直接変換に書き換える。
    - **ファイル名正規化が必須**: export_rootの実ファイル名は`_top`/`_bottom`接尾（例: `NG_image_140049_077_bottom.bmp`）だが、`utils/split_manager.py`の`_extract_product_id`（無改修で流用）は末尾`_<数字>`（`_0`/`_1`）をカメラ面として除去し同一製品のtop/bottomを同じtrain/testにまとめる仕組みである。このまま`_top`/`_bottom`を渡すと数字接尾でないため除去されず、top/bottomが別製品IDと誤認識されてtrain/test間でリークする。**`manager.py`がpoolへコピーする際にファイル名を`_0`/`_1`規則に正規化する**（`_top`→`_0`、`_bottom`→`_1`）。
    - `utils/split_manager.py`自体は無改修で流用する（ファイル名正規化により入力形式を揃えるため）。
    - **リサイズは削除せず保持する**: export_rootの画像は**crop+top/bottom分割のみ済み・リサイズ未適用**であることを確認済み。`process_image`（crop→分割→リサイズの3工程）のうち**crop・分割の呼び出しは不要**になるが、**リサイズ工程（`cv2.resize`、config の image_size 相当）は`manager.py`側に残す**必要がある。理由: マージンあり画像は`RawShiftImageFolder`経由で`process_image`をそのまま呼ぶため crop→分割→リサイズの全工程を通り、config image_size に揃う。export_root側がリサイズを省略すると、決定19でmonochroの同一DataLoaderに合体するexport_root（tight）画像とマージンあり画像の空間サイズが不一致になり、テンソル結合が破綻する。
12. **CLAUDE.md制約の明示的な例外化（データ取得・選定前処理）**: プロジェクトCLAUDE.mdの「やってはいけないこと」に記載された「学習ロジック（training/の学習本体）を改変しない（許可された薄いラッパ改修=skip_download/skip_uploadのみ）」を、**training/のデータ取得・選定前処理部分**（`training/dataset/`、`training/utils/ftp_common.py`、`training/utils/image_preprocessing.py`、`training/pipline.py`のオーケストレーション部分＝import文・FTPダウンロードステージ呼び出し等）に限り明示的に上書きする。ユーザー承認済み。
13. **export_root の物理パス**: 新規環境変数`TRAINING_EXPORT_ROOT`を追加し、backendのver2 config（`TrainingConfig`相当）に新項目として定義する。
14. **UI→pipline.py引数連携の変更**: 現状UIは色番/size/chain/tapeの4項目を入力させるが、`training/pipline.py`に実際に渡るのは`common.target_color`（色番）のみで、`training_service.py:_run_job`が取得する`size`/`chain`/`tape`はDB取得後に未使用変数として捨てられている（`_size`, `_chain`, `_tape`）。今回の設計では`{mode}_{size}_{chain}`→`dataset_id`解決にsize/chainが必須のため、**`_run_job`が取得したsize/chainを`build_command`まで配線し直す**。`tape`は`dataset_name`解決には使わない（dataset_idのname規約に含まれないため）が、**決定21〜24のONNX保存パス管理には使用する**（`_run_job`内で保持し、完了後のパス解決に渡す）。

### マージンあり画像への対応（v1.2 新規）
15. **背景・目的**: `RawShiftImageFolder`（monochro専用、`use_raw_shift_dataset: true`が既定）は、生の未加工フレームを毎回ランダムなオフセット（±`crop_shift_max_px`、既定20px）で再クロップし、**カメラ取付・製品の物理位置のばらつきを吸収し、推論時の位置ズレに強いモデルにする**ためのaugmentationである。export_root（マージンなし・現行crop範囲と完全一致・今後の運用段階で増え続けるデータ）にはシフトに使える余白ピクセルが存在しないため、この仕組みを維持するには別ソースが必要。
16. **データの二層構造**: 検証段階に取得済みの「マージンあり」データは**今後増えない固定プール**であり、運用段階に入ると新規取得データは全て「マージンなし」（export_root）になる。両者は生成時期・対象が完全に分離しており、**製品レベルで重複しないことをユーザーが確認済み**（train/testリークの懸念なし）。
17. **マージンあり画像の配置規約**: 生成（別機能・本タスクのスコープ外）自体は対象外とし、配置規約のみ確定する。
    - 新規ルートディレクトリ**`training/export_root_margin/`**（確定・`export_root`と対をなす命名）に、`export_root`と同じ`{dataset_id}/metadata.json` + `binary/{color_no}/{category_id}/`構造で存在する。
    - 新規環境変数`TRAINING_MARGIN_EXPORT_ROOT`をbackend configに追加し、backendが`export_root`と同じ規約（`metadata.json`の`name`一致検索）でdataset_idを解決する。
    - **一部の色番（mode,size,chain）ではマージンありデータが見つからない場合がある**（検証段階が全色を網羅していない）。見つからない場合は非致命的にフォールバックし、その色番の学習はマージンなしデータのみで行う（エラーにしない）。
    - **color modeはマージン対応不要**：`RawShiftImageFolder`はmonochro専用であり、既存仕様でcolorはshift>0を拒否している。マージン関連の解決・受け渡しはmonochroのみに限定する。
18. **マージン画像に対する要件（export側への要求として記録・確認済み）**:
    - **未分割**（top/bottom分割前のフルフレーム1枚。export_rootとは異なり分割しない）。`RawShiftImageFolder`が自前でcrop→top/bottom分割→リサイズ（`process_image`）を行う前提。
    - **座標系は生センサー座標系のまま**（`process_image`のmonochro crop式`(485+crop_offset_x, 0, 1250, height)`がそのまま有効。座標の再基準・crop式の変更は不要）。
    - 余白は`crop_shift_max_px`（既定20px）以上を持つこと。
    - 上記2点（未分割・生センサー座標系）が確認済みのため、**`RawShiftImageFolder`/`process_image`のcrop式自体は変更不要**。変更が必要なのは`raw_image_root`の参照先（`1_download`→マージンありexportの解決済みパス）のみ。
19. **train/val/testのマージ方式**（v1.7で決定19後半を上書き。§「validationデータ不足への対応」参照）:
    - **モノクロは one-class 異常検知（good画像のみで学習）であることを確認済み**（`use_raw_shift_dataset=true`時の現行`RawShiftImageFolder`はtrain/valともに`good`のみを読む。defect画像はmonochroの学習には使わない、既存動作を維持）。したがって本設計のmonochro向けマージも**on_class=0（good）カテゴリの画像のみ**を対象とする。マージンあり画像側・export_root側とも、defectカテゴリ（on_class=1）はmonochroのDataLoaderには渡さない。
    - **train** = マージンありデータのgood画像の`pool_train_ratio`分（見つかった場合。`RawShiftImageFolder`で毎回±20pxランダムシフトして使用） + export_root（マージンなし）のgood画像のtrain分（`pool_train_ratio`で分割したtight画像をそのまま使用、シフトなし）。
    - **val/test** = export_root（マージンなし）のgood画像のtest分 + マージンありデータのgood画像の残り（`pool_train_ratio`の残り分。offset=0固定でクロップ、位置ズレ頑強性はtrain側のシフトaugmentationのみで獲得されるためval側は推論時と同一の分布に揃える）。**v1.2〜v1.6時点では「マージンあり側にtrain/test分割は不要（全量train）」だったが、v1.7でこれを撤回し分割対象に変更した**（理由はv1.7セクション参照）。
    - **defect画像の扱い**: `dataset/manager.py`が構築するdefect_pool自体は（他用途・color側等のため）維持するが、monochroのDataLoader構築ではdefect_poolを参照しない。colorは既存どおりgood+defectの二値分類を維持し、本設計による変更はない。
    - **実装上の注意**: `use_raw_shift_dataset=true`時のmonochro.pyは`split_manager`（`split_pool_to_dataset`の出力）を使わず、マージンあり画像を`torch.randperm`で独自にtrain/val分割している（`_build_datasets`内）。export_root（マージンなし）側は`split_manager`経由の既存train/test分割（`pool_train_ratio`）をそのまま使う。
20. **CLAUDE.md例外の再拡張（DataLoader構築部分）**: 上記のマージ処理は`training/train/monochro.py`の`RawShiftImageFolder`呼び出し方式・DataLoader構築部分の変更を伴う。決定12の例外を、**DataLoader構築部分（マージンあり/なしデータの合体ロジック）に限り**再拡張する。**学習アルゴリズム本体（損失関数・モデル構造・学習ループ・color側の学習ロジック）は引き続き対象外・変更不可**。ユーザー承認済み。

### ONNX保存パスのタプル管理（v1.4 新規）
21. **問題**: `TrainingConfig.onnx_path(color_no, mode)`（`training_service.py`）および`training/deploy/model_export.py`の出力先は`model_dir/{color_no}/{mode}/{color_no}_{mode}_model.onnx`で、**color_noのみ**に依存する。`.kiro/specs/retraining/design.md`は「同一性はフルタプル（color_no/size/chain/tape）で保持する」と明記しているが、物理パスはこれに従っていない。同一color_noで異なる(size,chain,tape)の再学習ジョブが実行されると、後続ジョブの完了処理が前ジョブのONNXファイルを物理的に上書きし、DBの`onnx_monochro_path`/`onnx_color_path`が指す内容と実体が食い違う。
22. **修正方針: training/は不変。backendが完了後に最終パスへ移動する**。
    - `training/deploy/model_export.py`（学習本体側の出力先formula）は**変更しない**。単一ワーカ・FIFO実行のため、同一color_no+modeの一時出力先を複数ジョブが使い回しても実行時の競合は発生しない（ステージング領域として機能する）。
    - backend（`training_service.py`）が完了判定（既存の`onnx_ok`チェック）後、ステージングパス（`self._cfg.onnx_path(color_no, mode)`）から**タプル別の最終パス**へファイルを移動する。
    - **最終パスの命名規則（確定）**: `model_dir/{color_no}/{size}_{chain}_{tape}/{mode}/{color_no}_{size}_{chain}_{tape}_{mode}_model.onnx`。`tape`が空文字の場合は空文字のまま連結する（例: `{size}_{chain}_`のように末尾アンダースコアが残る形を許容。特別なプレースホルダは使わない）。
    - **履歴保持方針**: タプル単位で**最新のみ保持**（新しいジョブの完了時に同タプルの既存ファイルを上書き）。`DeployedModel`の`UniqueConstraint(color_no,size,chain,tape)`と整合する。ジョブ単位の履歴保持（`job_id`をパスに含める等）は不採用。
    - `mark_completed(job_id, mono_path, color_path)`には**移動後の最終パス**を渡し、DBに保存されるパスと実体を一致させる。
    - この変更は`backend/src/services/`配下のみで完結し、`training/`には一切触れないため、**新規のCLAUDE.md例外は不要**。
23. **エッジPC配信ファイル名も同様にタプル化する**: `deployment_service.py`の`_remote_name(color_no, mode)`（現状`{color_no}_{mode}_model.onnx`）を`{color_no}_{size}_{chain}_{tape}_{mode}_model.onnx`に変更する。`job`（`RetrainingJob`/`DeployedModel`）が既にsize/chain/tapeを保持しているため、新規のDB問い合わせは不要。配信メカニズム・配信先パス（`remote_dir`等）自体は変更しない。
    - **注意（確認済み・2026-07-24）**: エッジPC側の検査アプリケーション（本リポジトリ外）を、新ファイル名（フルタプルベース）を読み込めるようユーザー側で改修し、本番検査PC全台への反映・確認を完了した（ユーザー確認）。`tape`が空文字の場合に生じる二重アンダースコア（例: `501_05_CZT8__monochro_model.onnx`）についても実機で問題なく読み込めることを確認済み。これにより決定21〜22と同様、決定23も実装可能となった。
24. **`_run_job`のtape配線**: 決定14で配線するsize/chainに加え、`tape`も`_run_job`内で保持し、完了後のパス解決（決定22）・配信ファイル名解決（決定23）に使用する。

### validationデータ不足への対応（v1.7 新規）
25. **背景**: retrain_app_CW（旧実装）とtraining/（新実装）で同じcolor（001, monochro）を学習しparaを比較したところ、q_st_end（-11%）・threshold（約1/2）・cand1_Z（約1/3）・cand1_A（-39%）と、キャリブレーション定数に大きなズレが実測された。teacher_mean/stdはほぼ一致（分布自体は同等）していたため、原因はteacher-studentの学習品質ではなく、キャリブレーション（`q_st_start/end`・cand1の`mu/sigma/A/Z`・threshold）を算出するvalidationセットのサイズにあると特定した。決定19（v1.2〜v1.6）ではvalidationがexport_root（マージンなし）のtest/goodのみで、実測（color=001）では**36枚**しかなく、marginデータ（同色1998枚）は全量trainに回されvalには一切使われていなかった。
26. **決定: マージンデータもtrain/valに分割する**。分割比率は既存の`pool_train_ratio`（monochro設定、既定0.7）を流用し、新規の設定キーは追加しない。決定19の「マージンあり側にtrain/test分割は不要（全量train）」を本決定で上書きする。
27. **val側のマージンサンプルはcrop_offset=0固定とする**（train側のみ`crop_shift_max_px`のランダムshiftを適用）。理由: シフトへの頑強性はtrain側augmentationのみで獲得され、val/calibration側は推論時の実分布（C#側は常にoffset=0）と一致させる必要があるため。位置ズレ耐性と検出性能はどちらもこの方式で両立する（トレードオフではない）。
28. **分割の実装方式**: 同じ`margin_root`を参照する`RawShiftImageFolder`を2つ作る（train用: `crop_shift_max_px`、val用: `crop_shift_max_px=0`）。`full_size = len(margin_train_full)`に対し`torch.randperm(full_size, generator=seed固定)`でインデックスをシャッフルし、`pool_train_ratio`で分割した上で`Subset`を適用する（旧CW実装の`train_full`/`val_full`分割パターンと同一）。`RawShiftImageFolder`/`process_image`自体は無改修（決定18を維持）。

## 却下した代替案
- **app_dbに直接問い合わせる案（dataset/dataset_category_itemテーブル）**: 当初この案で進めていたが、metadata.jsonに同等の情報（size/chain/mode・on_class）が既に含まれることが判明。データセット総数20未満・低頻度更新という規模では、新規DBモデル・Repository・問い合わせコードを追加するコストが、ファイル走査のコストを上回るため不採用。
- **training/ が app_db に直接接続する案**: training/へDB依存を追加すると、CLAUDE.mdの「training/は学習ロジックのみ・DB非依存」というアーキテクチャ境界をさらに広く破ることになるため却下。
- **category対応表をJSON manifestファイルで渡す案**: DB参照案を検討していた時点では有効な代替案だったが、metadata.json自体をtraining/が直接読めるとわかったため不要になった。
- **1_download/2_staging構造を維持しラッパのみ差し替える案**: 中間段階を残す案も検討したが、ユーザーの判断で「export_root→3_pool相当へ直接変換」を採用（中間ファイルコピーの手間を省く）。
- **マージンあり画像1種類だけをexportし、offset=0/±20pxの両方をRawShiftImageFolderからサンプリングして「マージンなし」相当も代替する案**: シンプルだが、運用段階でマージンありデータの新規取得が止まる（検証段階の固定プールのみ）ため、長期的にtightデータの供給元をマージン画像に依存し続けることができない。マージンなしデータ（export_root）は別途・継続的に必要であり不採用。
- **training側でパディング・ゼロパッドによる合成シフトでマージンを代用する案（案B）**: 自己完結だが、crop境界（x=485付近）に人工画素を注入するため検査精度への影響が読めず、また実在するマージン画素を使う方針（ユーザー判断）と矛盾するため不採用。
- **合成シフトを廃止し自然な位置分散のみに依存する案（案C）**: シフトaugmentationの目的が「カメラ取付・製品位置ズレという特定の分散源を吸収するため」であり、単なるデータ量確保が目的ではないため、代替なしに廃止すると位置ズレ耐性の低下リスクがあり不採用。
- **（v1.7）val側のマージンサンプルもランダムshiftを残す案**: 実装は単純だが、推論時に発生しない「ズレたクロップ」をcalibration統計に混入させることになり、キャリブレーションが本番分布からズレる。頑強性向上には寄与しない（頑強性はtrain側のみで決まる）ため不採用。
- **（v1.7）margin専用の新規分割比率キー（`margin_train_ratio`等）を新設する案**: 設定項目を増やす理由がなく、既存の`pool_train_ratio`（7:3という運用上の意味）と統一する方が理解しやすいため不採用。
- **（v1.7）画像パス単位でtop/bottomを分離しないようグルーピングしてから分割する案**: 旧CWの挙動（サンプル単位でランダム分割、top/bottomがtrain/valに分かれる可能性あり）と非対称になり実装も複雑化するため、今回は旧CWと同じサンプル単位分割を採用（top/bottom分離の厳密化は本タスクの対象外）。

## 制約 / 非目標
- **非目標**: export_root および export_root_margin の生成（書き出し）処理の実装。これらは別機能のスコープ。
- **非目標**: `training/train/`配下の学習アルゴリズム本体（損失関数・モデル構造・学習ループ・monochro.py/color.py/model_handler.pyの学習コア）の変更。DataLoader構築部分（決定20）のみが例外。
- **非目標**: `deployment_service.py`が使う出力側FTP（ONNX配信）の変更。
- **制約**: `on_class`は'0'=OK/'1'=NG の二値。多クラス分類は対象外（現状のgood/defect二値分類の枠を維持）。
- **制約**: マージン対応はmonochroのみ。colorのDataLoader構築・学習ロジックには一切変更を加えない。
- **前提**: metadata.jsonの`name`の一意性（同一(mode,size,chain)に対し常に1つのdataset_idのみ存在）はexport_root生成側の仕様保証に依存する。
- **前提**: 検証段階のマージンプールと運用段階のexport_root（マージンなし）は、時期・対象が完全に分離しており製品レベルで重複しない（train/testリークなし）。ユーザー確認済み。この前提が崩れた場合は製品ID基準の重複除外ロジックの追加検討が必要。
- **制約**: ONNX保存はタプル単位で最新のみ保持する（決定22）。同一(color_no,size,chain,tape)への複数回再学習は、過去のONNXを意図的に上書きする仕様であり、ジョブ単位の履歴保持は本設計の対象外。
- **（v1.7）非目標**: `RawShiftImageFolder`・`process_image`自体の変更（クロップ式・分割ロジックは対象外）。`pool_train_ratio`のデフォルト値変更（0.7を維持）。
- **（v1.7）既存モデルへの影響**: 既存の学習済みモデル（`6_model/*/monochro/para.json`）は本変更を反映していないため、本変更後は再学習が必要になる（キャリブレーション値が変わるため）。

## 検証基準
- export_root/export_root_marginの生成処理は対象外のため、E2Eでの実データ検証は不可。以下のフィクスチャベースの検証で完成を判断する：
  1. サンプルexport_rootディレクトリ（既存の2つのUUIDフォルダのようなbinary/{color_no}/{category_id}/構成、実ファイル名は`_top`/`_bottom`接尾）とフィクスチャmetadata.json（name・category配列にon_class/invalid_flgを含む）を用意し、`dataset/manager.py`の新選定ロジックが正しくgood_pool/defect_poolを構築すること、`invalid_flg=1`のカテゴリが除外されること、**ファイル名が`_0`/`_1`に正規化されていること**、**pool格納後の画像サイズがconfigのimage_sizeにリサイズされていること**を単体テストで確認する。
  2. 正規化後のファイル名に対し、既存`_extract_product_id`（無改修）が同一製品のtop/bottomを正しく同一グループとして扱うことを確認する（回帰テスト）。
  3. `common.target_color`の値と`binary/{color_no}/`フォルダ名が一致しない場合に、明確なエラー（サイレントな0件処理ではない）になることを確認する。
  4. backend側：`TRAINING_EXPORT_ROOT`／`TRAINING_MARGIN_EXPORT_ROOT`配下を走査し`(mode,size,chain)`→`dataset_id`を解決する単体テスト（フィクスチャディレクトリ・複数metadata.jsonを用意）。マージン側が見つからないケース（該当色番のフォルダが存在しない）で空文字にフォールバックし、非致命的に処理が継続することを確認する。
  5. `training_service.py`の`_run_job`/`build_command`が、DBから取得したsize/chainを使ってdataset_id解決結果を正しくCLI overrideに組み立てることの単体テスト（`common.export_root`/`common.dataset_id_monochro`/`common.dataset_id_color`/`common.margin_export_root`/`common.dataset_id_monochro_margin`）。
  6. monochroのDataLoader構築で、マージンデータが存在する場合に`RawShiftImageFolder`（マージンあり・goodのみ・train分は±20pxシフト）とexport_root（マージンなし・good・train分・シフトなし）が正しく合体されること、マージンデータが存在しない場合はexport_rootのみで学習が継続すること、**defectカテゴリの画像がmonochroのDataLoaderに一切含まれないこと**をフィクスチャで確認する。
  7. （v1.7で更新）val/testがexport_root（マージンなし・good）のtest分と、マージンデータの`pool_train_ratio`残り分（offset=0固定）の合成から構築されること、defect画像を含まないこと、`pool_train_ratio`を変えるとマージンのtrain/val分割数が追従することをフィクスチャで確認する。マージンデータが存在しない場合はexport_root（マージンなし・good）のtest分のみで構成され、変更前と同じ挙動を維持することを確認する。
  7b. colorのDataLoader構築（good+defect二値分類）が本設計により変更されていないことを確認する（既存テストのgreen維持）。
  11. `TrainingConfig`が(color_no,size,chain,tape,mode)から最終ONNXパスを正しく組み立てること（tape空文字ケースを含む）を単体テストで確認する。
  12. `_run_job`完了処理が、ステージングパスから最終パスへファイルを移動し、`mark_completed`に最終パスを渡すことをフィクスチャ（一時ファイル）で確認する。同一タプルで2回連続完了させた場合、2回目の最終ファイルが1回目を正しく上書きすることを確認する。
  13. `deployment_service.py`の`_remote_name`がタプルを反映したファイル名を生成することを単体テストで確認する。
  8. FTP関連コード削除後、`training/`配下に`ftp_download.py`/`ftp_common.py`への参照が残っていないことをgrepで確認する。
  9. `deployment_service.py`側の出力FTP関連テストに変更が及んでいないことを確認する（誤って触っていないことの確認）。
  10. colorモードのDataLoader構築・学習ロジックに変更が無いこと（既存テストが無改修でgreenを維持）を確認する。

## 未解決パラメータ
- manifestファイルの物理的な配置場所（一時ディレクトリのパス規則）→ 廃止決定により解消（該当なし）。
- `TRAINING_EXPORT_ROOT`/`TRAINING_MARGIN_EXPORT_ROOT`のDocker/Windows環境間でのマウント方法（既存の`data_root`上書き機構との関係）は未確定。実装時に決定する。
- backend側でexport_root/export_root_margin走査を行うコードの配置場所（`training_service.py`に直接実装するか、新規ヘルパーモジュールに切り出すか）は未確定。実装時に既存の命名規則に従って決定する。
- マージンあり画像の余白px数の正確な下限値（20px以上を推奨するが、export側の実装値は未確認）は実装時にexport側と合意する。
- マージンあり画像が「見つからない」場合の判定基準（該当dataset_idフォルダが物理的に存在しない、のみで判定するか、metadata.json自体の異常も考慮するか）は実装時に詳細化する。
- ~~エッジPC側の検査アプリケーション（リポジトリ外）が、配信ファイル名のタプル化（決定23）を受理できるか未確認~~ →
  解消（2026-07-24）。ユーザー側で検査アプリを改修し本番検査PC全台へ反映・確認済み（空tapeの二重アンダースコア
  ケースも実機確認済み）。決定23実装済み（タスク18）。

## 変更履歴
- [2026-07-22] v1.0 初版作成（grill-meインタビューにより決定。DB参照方式を前提としていた）
- [2026-07-22] v1.1 metadata.jsonにsize/chain/mode・on_class情報が含まれることが判明したため、DB参照方式を撤回しファイルI/O方式に全面変更。manifestファイル廃止・新規DBモデル不要に簡素化。dataset_id一意性の前提を明記。invalid_flg除外ルールを追加。
- [2026-07-22] v1.2 UI→pipline.py引数連携の実態（size/chain未使用）を明記し配線変更を決定事項化。`RawShiftImageFolder`の生フレーム依存が export_root（マージンなし）では動作不能になる問題を発見し、検証段階の「マージンあり」固定データプールを別ソースとして扱う設計を追加（配置規約・train/val/testのマージ方式・CLAUDE.md例外の再拡張）。ファイル名規則の不一致（`_top`/`_bottom` vs `_extract_product_id`が期待する`_<数字>`）によるtrain/testリークの可能性を発見し、ファイル名正規化を決定事項化。
- [2026-07-22] v1.3 マージン画像の分割状態・座標系を確認（未分割・生センサー座標系のまま）。これにより`RawShiftImageFolder`/`process_image`のcrop式自体は変更不要と判明し、決定18を確定事項に更新。raw-shiftモードのmonochro.pyが現状split_managerを使わずrandperm独自分割している点を実装上の注意として明記（決定19）。monochroが one-class 異常検知（goodのみ学習）であることを確認し、マージ対象をgood画像限定に修正。defect画像はmonochroのDataLoaderに含めないことを明記（決定11・19）。colorの二値分類（good+defect）は変更なしを再確認。export_rootの画像がリサイズ未適用（crop+分割のみ）であることを確認し、`manager.py`側にリサイズ工程を残す必要があることを決定11に追記（マージンあり画像側は`process_image`経由でリサイズ済みのため、次元不整合を防ぐために必須）。FTP削除に必然的に伴う`training/pipline.py`のオーケストレーション部分（import文・ダウンロードステージ呼び出し）の修正を決定10・12・CLAUDE.md例外に明記（削除承認から当然に導かれる付随変更として追記、再確認は不要と判断）。
- [2026-07-24] v1.4 マージンあり画像のフォルダ名を`training/export_root_margin/`に確定（決定17）。UI引数連携の調査に伴い、ONNX保存パスがcolor_noのみに依存しフルタプル同一性と食い違っている既存のギャップを発見。backendが完了後にステージングパスからタプル別最終パスへファイルを移動する方式で修正することを決定（決定21〜24）。training/への変更は不要なため新規CLAUDE.md例外は不要。エッジPC配信ファイル名も同様にタプル化する決定をしたが、これが出力側FTP不変の方針（v1.1冒頭注記）と矛盾していたため注記を修正し「配信メカニズム・配信先パスは不変、ファイル名のみ変更」と明確化。エッジ側検査アプリケーション（リポジトリ外）が新ファイル名を受理できるか未確認のため、未解決パラメータに追記し決定23の実装保留を明記。履歴保持はタプル単位で最新のみ（ジョブ単位の履歴は対象外）。
- [2026-07-24] v1.5（実装時の発見）タスク16実装中、決定19の`train`合体（マージンあり全量＋tight train）により、`train_step`（学習イテレーション数）の算出根拠が`full_train_set`の意味変化を通じて変わることが判明: 旧実装は生画像プール全量（`train_full`、raw-shift分割前の母数）を基準にしていたが、新実装は実際にDataLoaderへ渡す学習データ量（マージンあり全量＋tight train）を基準にする。マージンあり画像が見つからない色番（決定16の想定どおり運用段階で増えていくケース）では、旧実装の生画像プール全量より学習データ量が少なくなり、結果として`train_step`が旧実装より減る可能性がある。ADR本体（決定15〜20）はこの`train_step`への影響を明示的に扱っていなかったため、ユーザーに確認し「学習量が減ることを許容する」との回答を得た（2026-07-24）。追加の調整（ステップ数下限の確保等）は本ADRの対象外のまま維持する。
- [2026-07-24] v1.6 決定23（エッジPC配信ファイル名のタプル化）の未解決パラメータが解消。ユーザーが検査PC側の
  検査アプリケーション（本リポジトリ外）を新ファイル名形式（`{color_no}_{size}_{chain}_{tape}_{mode}_model.onnx`）
  に対応するよう改修し、本番検査PC全台への反映・確認を完了。tapeが空文字の場合の二重アンダースコア
  （`501_05_CZT8__monochro_model.onnx`）も実機で確認済みとの回答を得たため、タスク18（`deployment_service.py`の
  `_remote_name`変更）を実装した。
- [2026-07-27] v1.7 retrain_app_CW（旧実装）とtraining/（新実装）で同色（001, monochro）を学習しparaを比較した
  結果、q_st_end・threshold・cand1のA/Zに大きなズレ（最大約3倍）を実測。teacher_mean/stdはほぼ一致していたため、
  原因をvalidationデータ不足（export_root test/goodのみでcolor=001は実測36枚）と特定した。決定19の
  「マージンあり側にtrain/test分割は不要（全量train）」を上書きし、マージンデータも`pool_train_ratio`で
  train/valに分割する設計に変更（決定25〜28）。val側のマージンサンプルはoffset=0固定（train側のみランダム
  shift）とし、推論時分布とのキャリブレーション整合を優先。分割は旧CW実装の`train_full`/`val_full`インデックス
  分割パターンを復活させる形で実装（`RawShiftImageFolder`自体は無改修）。既存の学習済みモデルは本変更後に
  再学習が必要になることを明記。`training/train/monochro.py::_build_datasets`・
  `tests/train/test_monochro_export_root_margin.py`を実装・更新し、既存59件を含む`training/tests/`は
  無改修分もすべてgreenのまま維持。
  なお実装直後、`utils/image_preprocessing.py`のmonochro crop幅コメント「TEMP crop1250 (要revert→1200 /
  C#整合は1200)」がv1.7の変更（marginをvalにも使うようになったことで、この幅がキャリブレーションにも
  影響し得る）と関連しうる懸念として提起されたが、ユーザーに実機C#ソース（Class1.cs）を確認してもらった
  結果、C#側も現在`new Rect(485, 0, 1250, height)`であり、Python側の1250と一致していることが判明。古い
  コメント（1200時代の名残）が誤って残っていただけで、実際のパリティ上の問題は無かった。コメントを
  「2026-07-27にC#側と一致確認済み」に修正した（動作変更なし）。
