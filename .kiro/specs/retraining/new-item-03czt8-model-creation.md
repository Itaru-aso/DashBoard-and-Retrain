# 新規サイズアイテム(03CZT8)専用モデル作成 — 新フォルダへの完全分離実装 v3.2

> 位置づけ: `retraining` spec の `design.md` を上書きせず、新規サイズアイテム03CZT8の
> monochro/colorモデルを新規に学習するための意思決定記録（ADR）として独立管理する。
>
> **v2.0での方針転換（目付け役レビューでREJECT、2026-09-25）**: v1.0は
> `dataset-export-root-migration.md` 決定12（データ取得・選定前処理部分の例外化）を
> 「新規アイテムのcrop/resizeパラメータ化」という別目的へ拡張利用し、
> `process_image()`/`RawShiftImageFolder`**自体**にcrop_x0/crop_width引数を追加する
> 設計だった。しかし同ADRの「制約/非目標」節（131行目）に
> **「（v1.7）非目標: `RawShiftImageFolder`・`process_image`自体の変更
> （クロップ式・分割ロジックは対象外）」** と明記されており、v1.0はこれに直接抵触していた。
> v2.0では既存の`process_image()`/`RawShiftImageFolder`を一切変更せず、既存ファイルへの
> 新規関数・新規クラス追加として実装する方式（目付け役の代替案A）に転換した。
>
> **v2.1/v2.2でのadvisor・目付け役再指摘反映**: overlap（上下分割の重なり幅）も
> 03CZT8で05CZT8と異なることが実測判明（overlap=50 vs 60）、config.yamlへの
> キー追加要否、CLAUDE.md例外の対象範囲などを修正。
>
> **v3.0での方針転換（ユーザー指示、2026-09-25）**: ユーザーから「既存のプログラムへの
> 変更なしで実装したい。既存プログラムを転用する場合は新しいフォルダにコピーして使用する」
> との指示があり、v2.2の「既存ファイルへの新規関数/新規クラス追加」（`image_preprocessing.py`
> ・`raw_shift_dataset.py`への追加、`train/monochro.py`のDataLoader構築部分での分岐）を
> さらに一歩進め、**既存ファイルに一切触れず、新フォルダに完全分離して実装する**方式へ転換した。
> `train/monochro.py`・`train/color.py`も変更禁止（ユーザー確認済み）。
> advisorに相談した結果、この転換で新たに2つの論点が判明し反映した（決定4・決定10）。
>
> **v3.1での配置場所修正（実装時の実測、2026-09-25）**: 実装後にtraining全体のテストスイート
> （`tests/ci_gates/test_training_boundary.py`、アーキテクチャ境界CI gate）を実行したところ、
> `training/items/item_03czt8/train_monochro.py`/`train_color.py`が`train.common`を直接
> importしており、「`train.common`/`train.color`/`train.monochro`は`train`パッケージ内から
> のみimport可（境界の逆行を防ぐラチェット）」という既存の境界制約に抵触することが判明した。
> `train`パッケージの公開API（`train/__init__.py`）は`train_color`/`train_monochro`の2関数
> のみをexportし、`train.common`の低レベル関数（`get_st_transform`/`TrainTransform`/`predict`/
> `map_normalization`/`teacher_normalization`等）は非公開という既存のカプセル化方針があり、
> これを尊重する（gateを緩めない）ため、`training/items/item_03czt8/`を丸ごと
> `training/train/item_03czt8/`へ移動した（分割せず1つのimportプレフィックスに統一）。
> `training/train/item_03czt8/train_monochro.py`/`train_color.py`は実質的に
> 「`train.monochro`/`train.color`の別実装」であるため、`train`パッケージ内に置くことで
> gateが本来許可する形に適合する（gateを回避したのではなく、実体として準拠させた）。
> 移動後もgate自体は引き続きRED（既存の技術的負債`_scratch_566_saturation_drift/
> run_color_candidate.py`が違反しているため）だが、**offendersリストから本ADRの2ファイルが
> 消えたこと**を成功基準とする（gate全体のPASSではない）。`crop.py`/`preprocessing.py`/
> `margin_dataset.py`/`pipline.py`/`conf_03czt8.yaml`は`train.common`等をimportしないため
> 移動の必要はなかったが、1機能=1ディレクトリ・1importプレフィックスを保つため同じ場所に
> まとめて移動した。
>
> **v3.2でのmonochroリサイズサイズ変更（ユーザー指示、2026-09-25）**: monochroの
> リサイズサイズを512×356から**512×384に変更**。`conf_03czt8.yaml`・関連テスト
> （`test_item_03czt8_margin_dataset.py`/`test_item_03czt8_pipline.py`/
> `test_item_03czt8_preprocessing.py`の期待値）を更新し、モデルforward事前チェック
> （teacher/student/autoencoder出力形状一致、pdn出力(88,120)）で問題なく動作することを
> 確認した。crop_x0/crop_width/overlap（決定1）は変更なし。

## 目的 / 背景

960番・559番・053番の3色番で、新規サイズアイテム03CZT8を既存の学習済みモデル(05CZT8)に
転用できるか（グリッドサーチ＋空間異常マップ可視化によるスパイク検証、
`inspection-domain-shift-diagnosis` skill準拠）を検証した。結論は以下の通り（読み取り専用の
スパイク調査であり、リポジトリへのコード変更・コミットは無し）：

- **monochro**: 960/559/053のいずれも転用不可（どのクロップを選んでも自身の閾値の1.3〜3.3倍。
  空間異常マップでもテープ全面に格子状の異常反応があり、05CZT8の学習分布と質感自体が異なる）。
- **color**: 960は転用不可、559は限定的な転用可能性あり、053も限定的な転用可能性あり
  （053最良構成でflagged@1.0=16.7%）。ただしいずれもn=60のスパイク調査であり本番投入判断には未達。

上記結論を受け、**03CZT8はmonochro/colorとも専用データでの新規学習が必要**と判断した。
05CZT8の学習プログラム（`training/`パイプライン、学習ロジック本体）はそのまま流用し、
crop位置・リサイズサイズのみ03CZT8向けに変更する。**v3.0では、既存プログラムに一切触れず
新フォルダへの完全分離実装として、この変更を実現する。**

## 技術的前提（コード調査・実測で確認済みの事実）

1. **crop位置はコードにハードコード、色番非依存**: `training/utils/image_preprocessing.py`の
   `process_image()`は monochro crop=(485,0,1250,H)、color crop=(215,0,1675,H) を固定値で持つ。
   `training/utils/crop_split_annotation_export.py`（生産検証アノテーションデータ用、別スコープ）
   にも同じ座標が意図的に重複実装されている（学習ロジック本体を変更せず独立に保つための
   意図的な重複、というdocstring上の設計思想が既に存在する。v3.0の方針はこれと同型で、
   重複をファイル全体・オーケストレーション層まで拡張したものと位置づけられる）。
2. **export_rootの画像はcrop+top/bottom分割済み・リサイズ未適用**（`dataset/manager.py`
   `process_annotated_images`のdocstring・実装で確認済み）。`image_size`（config駆動、
   mode別・全色番共通のグローバル値）でのリサイズのみをtraining/側が行う。
3. **03CZT8のexport_rootデータは既に決定済みクロップで前処理済み**（実測で確認）：
   - `export_root/03CZT8-color/binary/053/ok/*_0.bmp` … shape=(1266,1280,3) → width=1280と一致
   - `export_root/03CZT8-monochro/binary/053/ok/*_0.bmp` … shape=(660,950,3) → width=950と一致
   - **x0の実測確認**: `export_root_margin/03CZT8-monochro/binary/053/ok/`（生画像、
     shape=(1220,2048,3)）と上記binaryとで共通するファイル名8件をテンプレートマッチング
     （`cv2.matchTemplate`）した結果、**x0=655, score=1.0000で完全一致**を確認。
   - **3b. overlap（上下分割の重なり幅）が03CZT8と既存コードで異なることを実測確認**:
     `process_image()`/`crop_split_annotation_export.py`は`overlap=60`固定。しかし03CZT8の
     export binaryは`overlap=50`で作られている：
     - monochro: raw高さ1220、half=610。bottom(`_1.bmp`)を生画像へテンプレートマッチング
       した結果y0=560=610-50（score=1.0000、全5サンプル一致）。`process_image()`なら
       y0=550（610-60）になるはずで、既存コードとは異なる。
     - color: raw回転後高さ2432、half=1216。03CZT8のbinary高さは1266=1216+50
       （既存05CZT8のbinary高さ1276=1216+60とは異なる）。
     - **05CZT8側のoverlap=60を直接shape確認で実測**: marginデータとbinaryデータは時期・
       対象が完全に分離しており共通ファイルが無いため（前提17参照）、05CZT8 monochro
       binaryのtop/bottom画像を直接読み、shape=(670,1250,3)であることを確認した
       （raw高さ1220、half=610、670=610+60で`overlap=60`と一致）。
     - **結論**: 03CZT8のexport一式（monochro/color共通）は`overlap=50`という
       05CZT8とは異なる規約で作られている。`crop_x0`/`crop_width`だけでなく
       `overlap`も03CZT8専用の値としてパラメータ化が必要（決定1・決定3参照）。
4. **monochroのmarginデータ（`export_root_margin`）は生画像のまま**:
   `use_raw_shift_dataset: true`（既定）により、`RawShiftImageFolder`
   （`training/utils/raw_shift_dataset.py`）が生画像から`process_image()`を
   `crop_offset_x`をランダムに揺らして呼び出す（撮像シフト耐性augmentation、567番実例で
   効果確認済み）。この仕組み自体は03CZT8向けの新モジュールで再現する必要がある（決定3）。
   - colorモードは`RawShiftImageFolder`を使わない設計（`crop_shift_max_px>0`はmonochro専用、
     color+shift>0はエラーになる既存ガード）。03CZT8のcolor marginデータも提供されておらず、
     設計上の非対称は既存仕様と整合している。
5. **metadata.jsonが存在しない・カテゴリ構造が異なる**: 05CZT8は
   `export_root/{dataset_id}/metadata.json`でcategory_id(UUID)→on_class(0=good/1=defect)を
   管理し、`binary/{color}/{category_id}/`という階層を持つ。03CZT8は`metadata.json`が無く、
   `binary/{color}/ok/`という固定名フォルダのみ（不良品カテゴリは現時点で存在しない）。
   `dataset/manager.py`の`_load_category_map`はmetadata.json必須のため、そのままでは
   `FileNotFoundError`になる。
6. **defectサンプルが0件の場合の既存フォールバック**: `utils/channel_weights.py`は
   `n_defect==0`のとき`unsupervised 100%（後方互換）`にフォールバックする既存ロジックを持つ
   （teacher-student学習自体は良品のみで成立するため問題なし）。一方
   `evaluation/scoring.py`の`find_optimal_threshold`（F1最大化）はdefectサンプルが無いと
   意味のある閾値を選べない（TP/FNが常に0でF1が常に0になり得る）。今回は**まず良品のみで
   学習し、閾値較正・評価は不良品サンプルが揃ってから行う**方針とする。
7. **画像サイズのアスペクト比**: 03CZT8 colorのクロップ後比率(1266:1280≈0.99)は正方形に近く
   384×384で妥当（異方性歪み~1%）。03CZT8 monochroのクロップ後比率(660:950≈0.695)は
   正方形に遠く、384×384(width×heightではなくheight×width表記に注意、以下同様)では
   縦方向に約44%の異方性伸縮が生じる。05CZT8 monochro（クロップ後約670:1250≈0.536→
   512×256=0.5、誤差7%程度）はアスペクト比を意図的に温存している既存パターンであり、
   これを踏まえてv3.0では512×356（比率0.695に近い）を採用したが、**v3.2で
   512×384に変更**（2026-09-25ユーザー指示）。比率は0.75となり660:950≈0.695からは
   ややずれるが、384はpdn_small_output_size()のdocstring例（384→88）にも載っている
   実績値であり、モデルforward事前チェック（teacher/student/autoencoder出力形状
   一致、pdn出力(88,120)）で問題なく動作することを確認済み。
8. **edge（検査PC）側のC#推論プログラムは対象外・別スコープ**:
   `image_preprocessing.py`のコメントに「C#推論プログラム（`Class1.cs`:
   `new Rect(485, 0, 1250, height)`）と2026-07-27に整合確認済み」とあり、検査PC側
   （このリポジトリ外）はクロップ座標とONNX入力サイズをハードコードしている可能性が高い。
   03CZT8は異なるcrop・異なるresizeになるため、学習・ONNX作成自体は本ADRの範囲で可能だが、
   **検査PCへの実配信には既存C#推論プログラム側の別途対応が必要**（2026-09-25ユーザー確認）。
   本ADRのスコープは学習・ONNX作成までとし、edge側対応は別タスクとする。
9. **`training/utils`配下のモデルアーキテクチャはサイズ非依存に設計済み**:
   実際の学習パイプラインが使う`get_pdn_small()`（教師/生徒、Conv/AvgPool連鎖のみで
   出力サイズ動的決定・ハードコードUpsampleなし）と`get_autoencoder()`
   （`image_size_height/width`から`pdn_small_output_size()`で最終Upsampleサイズを動的計算）は
   いずれもサイズ非依存。`scoring_transform.py`の`compute_anomaly_score()`も`height`/`width`
   を引数で受け取る設計。`edge_mask.py`の両端マスク（`edge_mask_w=2`）もPDN出力幅に対し
   十分小さく安全（monochro幅120、color幅88程度）。
10. **`train/monochro.py`/`train/color.py`は巨大な単一関数であり部分的な再利用が困難**:
    `train_monochro()`（376-867行目、約490行）はモデル構築・DataLoader構築・学習ループ・
    評価・保存までを一体で行う単一関数。`train_color()`も同様の構造。DataLoader構築部分
    （`_build_datasets`関数、285-376行目）だけを既存ファイルから呼び出す形にはできず、
    ユーザー指示（既存ファイル変更禁止）を満たすには**関数全体を新フォルダへコピー**する
    必要がある。
11. **03CZT8はbackend（`training_service.py`）経由ではなく`training/pipline.py`直接起動が前提**:
    `docs/reference/retraining-batch-training-manual.md`によれば、`training_service.py`の
    dataset_id自動解決（`{mode}_{size}_{chain}`名前検索）は現在`05_CZT8`のみが登録されており、
    03CZT8はUI/backend未登録の新規タプル。本ADRでは`pipline.py`をCLI overrideで直接起動する
    手動運用（同マニュアルのパターン）を前提とする。**backend経由での運用が別途必要になった場合は
    UI・DBへの03/CZT8タプル登録が別タスクとして必要**（本ADRのスコープ外）。
12. **para.jsonへのimage_size記録は既に実装済み**:
    `evaluation/scoring.py`の`load_model()`は「para.jsonに`image_size_height/width`が
    含まれていればそれを優先、なければ引数既定の256×512」という設計だが、
    `train/monochro.py`（670-671, 783-784行目）・`train/color.py`（424-425, 511-512行目）は
    いずれも学習完了時に`image_size_height`/`image_size_width`を必ずpara.jsonへ書き込む
    （コピー先でも同様の書き込みを維持する）。
13. **CLAUDE.md決定12のファイルリストに`raw_shift_dataset.py`は含まれていない**:
    決定12がリストする対象ファイルは`training/dataset/`・`training/utils/ftp_common.py`・
    `training/utils/image_preprocessing.py`・`training/pipline.py`のオーケストレーション部分のみ。
    ただしv3.0では両ファイルとも一切変更しないため、この論点自体が不要になった（決定9参照）。
14. **【v3.0新規・最重要】03CZT8はcolor_no="053"を05CZT8と共有しており、
    既存の出力パスがcolor_noのみに依存している（advisor指摘・実測確認済み）**:
    - `6_model/053/monochro/`には既存の05CZT8 monochroモデル一式
      （`053_monochro_model.onnx`, `para.json`, `teacher/student/autoencoder_state_best.pth`）が
      **本番稼働中**として実在する（実測確認済み）。
    - `3_pool/053/monochro/good_pool/`には既存の05CZT8良品画像が106件実在する（実測確認済み）。
      `dataset/manager.py`の`_copy_if_new`はファイル名でスキップ判定するだけなので、
      03CZT8の画像をここに書き込むと**両アイテムの画像が同一プールに混在する**。
    - `4_dataset/`・`5_splits/`・`backup/`も同様にcolor_noのみで構成されるパス。
    - これは`dataset-export-root-migration.md`決定21が指摘した既知の欠陥
      （「既存のONNX保存パスがcolor_noのみに依存し、size/chain/tapeを反映していない」）と
      同種の問題であり、同ADR決定22の対策（backendが完了後にタプル別最終パスへ移動する）が
      前提とする**backend経由の運用フロー**が、本ADR決定11（`pipline.py`直接起動）では
      機能しない。**対策を講じずに03CZT8の学習を実行すると、本番稼働中の05CZT8/053モデルと
      プールデータを上書き・混在させる**（決定4で対処）。

## 検討した代替案と却下理由

- **（v1.0で採用・却下）決定12を「新規アイテムのcrop/resizeパラメータ化」目的へ拡張利用し、
  `process_image()`/`RawShiftImageFolder`自体に引数を追加する案**: 目付け役レビューで
  `dataset-export-root-migration.md`の非目標条項（131行目）と直接矛盾すると判明したため却下。
- **（v2.0〜v2.2で採用・v3.0でユーザー方針により却下）既存ファイルへの新規関数/新規クラス追加＋
  `train/monochro.py`のDataLoader構築部分への軽微な分岐追加**: 非目標条項には抵触しない
  設計だったが、ユーザーが「既存プログラムへの変更を一切行わない」ことをより優先し、
  新フォルダへの完全分離方式へ転換。
- **`process_image()`内部でcolor_no→crop座標のテーブルを参照する案（関数シグネチャは維持）**:
  シグネチャを変えなくても関数内部のロジックを変更するため、非目標条項が意図する
  「既存全色番が通る共有パスに一切触れさせない」という趣旨を満たせない。却下。
- **05CZT8のcrop式(485,1250)を維持し、画像側にパディングを加えてサイズを合わせる案**:
  crop境界に実在しない画素を人工的に注入することになり、566番ADRで同種の判断
  （案B「パディング・ゼロパッドによる合成シフト」を不採用とした前例）と同じ理由で却下。
- **リサイズサイズだけ変更し、cropは05CZT8と共通（485,1250）のまま使う案**: 03CZT8の
  テープ位置・幅は05CZT8と異なる（グリッドサーチで確認済み）ため、共通cropでは
  テープ以外の背景領域が大きく写り込み学習が成立しない。不採用。

## 決定事項

1. **crop位置・overlap（03CZT8向け）**: monochro (x0=655, width=950, overlap=50)、
   color (x0=418, width=1280, overlap=50)。x0・overlapとも実測（テンプレートマッチング、
   score=1.0000）で確認済み（技術的前提3・3b参照）。colorのoverlapは学習時の経路には
   影響しない（決定3参照。export_root画像が既にクロップ済みでそのまま使うため）が、
   export済みデータの実測事実として記録する。
2. **リサイズサイズ（03CZT8向け）**: monochro 512×384（アスペクト比温存）、
   color 384×384（正方形に近いため）。
3. **新フォルダへの完全分離実装（v3.0）: 既存ファイルは一切変更しない（diffゼロ）**。
   新フォルダ`training/train/item_03czt8/`（v3.1で`training/items/03czt8/`から移動。
   理由は本ADR冒頭「v3.1での配置場所修正」参照）を新設し、以下の3分類で構成する：
   - **新規実装**（既存に対応物が無い、または対応物をそのまま使えない部分）:
     - crop/上下分割関数（`crop_x0`/`crop_width`/`overlap`をパラメータとして受け取る。
       `process_image()`の03CZT8向け相当だが、既存ファイルへの追加ではなく新規ファイル
       として実装する）。
     - monochro margin用のDatasetクラス（`RawShiftImageFolder`の03CZT8向け相当。
       上記の新規crop関数を呼ぶ）。
   - **コピー**（オーケストレーション層。既存ファイルを一切変更せず、内容を新フォルダの
     新規ファイルへ複製し、DataLoader構築部分のみ新規crop関数/新規Datasetクラスを使うよう
     書き換える）:
     - `train/monochro.py`の`train_monochro()`。
     - `train/color.py`の`train_color()`（決定を参照。DataLoader構築部分自体に変更は
       ほぼ無いが、独立性のためコピーする）。
     - `pipline.py`のステージ実行シーケンス（集計→train→deploy、03CZT8専用の起動スクリプト
       として必要な範囲のみ）。
   - **無変更でimport**（重複させない。学習ロジック本体が実際に定義されているモジュール
     であり、ここをコピーすると「学習ロジック本体の複製」に該当してしまうため、既存モジュールを
     そのままimportして使う）:
     `utils/common.py`（`get_pdn_small`/`get_autoencoder`等）、`model.py`、
     `utils/scoring_transform.py`、`utils/channel_weights.py`、`utils/edge_mask.py`、
     `utils/split_manager.py`、`utils/preprocessing.py`、`utils/predict.py`、
     `evaluation/scoring.py`、`deploy/model_export.py`、`dataset/manager.py`
     （`manager.py`はリサイズのみでcropしないため、出力パスをoverrideすれば無改修で動く）。
4. **【v3.0新規・最重要】出力パスを03CZT8専用に完全分離する（advisor指摘、ブロッカー対応）**:
   技術的前提14の上書きリスクに対応するため、`common.model_dir`/`common.pool_base`/
   `common.dataset_path`/`common.splits_dir`/`common.backup_dir`を、既存の05CZT8等が使う
   パス（`./6_model`/`./3_pool`/`./4_dataset`/`./5_splits`/`./backup`）とは異なる
   03CZT8専用パス（例: `./6_model_03czt8`/`./3_pool_03czt8`等、実装時に確定）に設定する。
   これらは既に`common:`セクションの既存configキーであり、コード変更は不要
   （新フォルダ内の03CZT8専用configファイル、またはコピーしたエントリスクリプト内の
   固定値・CLI overrideで指定する）。**`common.export_root`/`common.margin_export_root`
   （読み取り専用のデータソース）は既存のまま共有してよい**（dataset_idで
   `03CZT8-color`/`03CZT8-monochro`を指定するため、既存05CZT8のデータとは自然に分離される）。
   実行前・実行後に`git status`相当の確認（`6_model/053`・`3_pool/053`ツリーのタイムスタンプ・
   内容比較）を行い、既存05CZT8アーティファクトが一切変更されていないことを確認する運用手順を
   テスト方針に追加する。
5. **crop_x0/crop_width/overlapは共有`config.yaml`に追加しない（v3.0で決定6を再修正）**:
   v2.1では共有`config.yaml`へのキー追加が必要と判断したが、v3.0では新フォルダに
   完全分離するため、これらの値は**新フォルダ内のモジュール定数、または新フォルダ専用の
   configファイル**として保持する。共有`config.yaml`（`training/conf/config.yaml`）は
   **一切変更しない**。リサイズサイズ（`image_size_width`/`image_size_height`）のみ、
   既存の共有configキーへの通常のCLI dotlist overrideで対応する（既存の
   `candidate1.enabled=true`と同じ方式。コピーしたエントリスクリプトから既存config構造を
   読み込んで使うため、この部分は既存の仕組みと変わらない）。
6. **metadata.json（データ側のみ、コード変更なし）**: `export_root/03CZT8-color/`、
   `export_root/03CZT8-monochro/`、`export_root_margin/03CZT8-monochro/`それぞれに、
   以下を持つ`metadata.json`を新規作成する：
   - `name`: `color_03_CZT8` / `monochro_03_CZT8`（引用元スキーマの`{mode}_{size}_{chain}`
     形式に合わせる。決定11により現時点ではbackend解決を経由しないため実質使われないが、
     将来のbackend移行・スキーマ整合のため設定する）。
   - `category`: `category_id="ok"`, `category_label_name="good"`, `on_class="0"`,
     `invalid_flg="0"`（1件のみ。`category_id`が非UUID文字列である点は引用元スキーマ
     （UUID前提）と形式が異なるが、`dataset/manager.py`は文字列としてしか使わないため
     動作上は問題ない）。
7. **defectカテゴリなしで学習を進める**: 現時点でNGサンプルが存在しないため、良品のみで
   teacher-student学習を行う。channel_weightsは既存の`unsupervised 100%`フォールバックが
   適用される。閾値較正・F1ベースの評価は不良品サンプルが揃ってから別途行う。
8. **CLAUDE.md制約の新規例外は不要（v3.0で決定9を再修正）**: 既存ツリー
   （`training/utils/image_preprocessing.py`・`training/utils/raw_shift_dataset.py`・
   `training/train/monochro.py`・`training/train/color.py`・`training/conf/config.yaml`・
   `training/pipline.py`）に一切変更を加えないため、CLAUDE.md「やってはいけないこと」節への
   新規例外追記は不要と判断する。**「新規例外は不要、既存ファイルはdiffゼロ」という結論を
   本ADRに記録する**（例外を追記しないことも決定として明示し、後から見た人が「検討漏れ」と
   誤解しないようにする）。損失関数・モデル構造・学習ループ・color側の学習ロジックは
   決定3の「無変更でimport」区分により実際に触れられておらず、対象外・変更不可のまま。
9. **edge側C#推論プログラムの対応はスコープ外**: 本ADRは学習・ONNX作成までを対象とし、
   検査PCへの実配信に必要なC#側の対応は別タスクとする。
10. **【v3.0新規】コピー部分と新規実装部分でテスト手法を分ける（advisor指摘）**:
    - `train_monochro()`/`train_color()`/`pipline.py`ステージシーケンスの**verbatimコピー**
      部分は、既存ロジックの単純な移植であり新規のRED→GREENは意味を持たないため、
      **特性化テスト**（コピー前後で同一入力に対し同一出力になることの回帰確認）で検証する。
    - crop/分割関数・margin用Datasetクラスという**新規実装**部分は、真のground truthが
      存在する（技術的前提3のテンプレートマッチング実測）ため、通常のTDD（RED→GREEN）を
      適用する（決定11のテスト方針参照）。

## 実装対象ファイル（想定、新フォルダ内はすべて新規作成）

- `training/train/item_03czt8/`（v3.1で`training/items/03czt8/`から移動。実装済み）:
  - `crop.py`: crop/分割関数（新規実装。`crop_and_split()`）。
  - `preprocessing.py`: crop+分割+リサイズ（新規実装。`process_image_item()`）。
  - `margin_dataset.py`: monochro margin用Datasetクラス（新規実装。
    `Item03CZT8RawShiftImageFolder`）。
  - `train_monochro.py`（`train/monochro.py`の`train_monochro()`をコピーし
    DataLoader構築部分を書き換えたもの）。
  - `train_color.py`（`train/color.py`の`train_color()`をコピーしたもの。
    DataLoader構築部分の変更は無いが独立性のためコピー）。
  - `pipline.py`（`pipline.py`のステージ実行シーケンスを03CZT8向けに複製）。
  - `conf_03czt8.yaml`: 03CZT8専用のパス設定（`model_dir`/`pool_base`/`dataset_path`/
    `splits_dir`/`backup_dir`を既存と分離、決定4）・crop/resize値。
- **既存ファイルは一切変更しない**（`training/utils/image_preprocessing.py`・
  `training/utils/raw_shift_dataset.py`・`training/train/monochro.py`・
  `training/train/color.py`・`training/pipline.py`・`training/conf/config.yaml`は
  diffゼロ）。
- （データ側、コード外）03CZT8向け`metadata.json`3件の新規作成（決定6）。
- `CLAUDE.md`: 変更不要（決定8）。

## テスト方針

- **新規実装部分（TDD、RED→GREEN→REFACTOR）**:
  - crop/分割関数: **真のground truthを使ったRED**。`export_root_margin/03CZT8-monochro/`の
    生画像に対し(x0=655, width=950, overlap=50)で処理した結果が、既存の
    `export_root/03CZT8-monochro/binary/053/ok/*_0.bmp`/`*_1.bmp`
    （リサイズ前、実測でscore=1.0000一致済み）と**pixel-identical**であることをassertする。
    関数が存在しない現時点では確実に失敗し（genuine RED）、パラメータが正しい場合のみ
    合格するテストになる（同時にoverlap=50の配線が正しいことも証明する）。colorも同様に
    (x0=418, width=1280, overlap=50)で`export_root/03CZT8-color/binary/053/ok/`との
    pixel-identical一致を確認する。
  - crop/分割関数: `crop_x0 + crop_width`が元画像幅を超える場合、`overlap`が
    `half_height`以上または負値の場合に明確な例外が発生すること（境界チェックの異常系）。
  - monochro margin用Datasetクラス: crop/分割関数を正しい`crop_x0`/`crop_width`/`overlap`
    で呼び出すこと（ランダムシフト機構は既存`RawShiftImageFolder`と同等に動作すること）。
- **コピー部分（特性化テスト、RED→GREENは適用しない）**:
  - `train_monochro_03czt8.py`/`train_color_03czt8.py`: DataLoader構築部分以外
    （モデル構築・学習ループ・保存処理の呼び出し方）が元の`train_monochro()`/`train_color()`
    と同一であることを、フィクスチャベースで回帰確認する。
  - DataLoader構築部分の書き換え箇所のみ、新規crop関数/新規Datasetクラスが使われることを
    確認する（既存の`RawShiftImageFolder`/`process_image`が一切呼ばれないことも確認する）。
- **リサイズサイズ変更の事前チェック（実装着手時・最初に1回実施）**: モデル構築後、
  **monochro(512×384)・color(384×384)それぞれでダミー入力を1回forwardし、
  teacher/student/autoencoderの出力空間サイズが一致すること（shape不整合エラーが
  出ないこと）を確認する**。1分程度で完了する安価なチェックであり、これを長時間の
  学習実行より先に行う（技術的前提9で設計上は動的対応済みと確認しているが、実機検証は未実施）。
- **【v3.0新規・最重要】既存05CZT8アーティファクトの無変更確認（決定4関連、実行前後で必須）**:
  03CZT8の学習を実行する前に`6_model/053/`・`3_pool/053/`・`4_dataset/053/`・
  `5_splits/053/`・`backup/`配下のファイル一覧・タイムスタンプ・ハッシュ等を記録し、
  実行後に差分が無いことを確認する。差分が生じた場合は即座に学習を停止し、
  パス分離設定（決定4）を見直す。

## リスク

- **コード重複の保守負債**: `crop.py`と`process_image()`、`margin_dataset.py`と
  `RawShiftImageFolder`、`train_monochro.py`と`train/monochro.py`の`train_monochro()`、
  `train_color.py`と`train/color.py`の`train_color()`、`pipline.py`と`training/pipline.py`は、
  いずれもユーザー指示（既存プログラムへの変更なし）に基づき意図的に分離した複製であり、
  ロジックが重複する。将来`training/train/monochro.py`等に不具合修正や仕様変更が入った場合、
  `training/train/item_03czt8/`側が追従されずに放置されるリスクがある。対策として、
  コピー元・コピー先の対応関係をdocstringに明記し、`training/train/monochro.py`側を
  変更する開発者への注意喚起とする（強制はしない）。
- **出力パス分離の設定漏れリスク**: 決定4のパス分離を誤ると本番稼働中の05CZT8/053アーティファクトを
  破壊する。実行前後の無変更確認（テスト方針参照）を必須の運用手順とする。

## 未解決事項・確認事項

- 決定11（`pipline.py`直接起動前提）が実際の運用と合っているか、実装着手前に再確認する。
- 03CZT8専用の出力パス（`6_model_03czt8`等の具体的な命名）を実装時に確定する。
- config.yamlへの`crop_x0`/`crop_width`/`overlap`キー追加時のHydra/OmegaConfのstruct mode
  検証は、v3.0では共有config.yamlに追加しないため**不要になった**（決定5参照）。
- **teacher_weights（03CZT8サイズ向けpretraining済みTeacher重み）が未検証**:
  `_resolve_teacher_weights_path()`は`{h}_{w}_teacher_{model_size}_monochro/color_
  {backbone}_final_state.pth`という命名規則でファイルを探す。03CZT8向けサイズ
  （monochro 512×384、color 384×384）に対応するTeacher重みファイルが
  `0_pretraining/`に存在するか未確認。存在しない場合、実際の学習実行時に
  `FileNotFoundError`になる（コード実装・テストの範囲では検出されない、実行時にのみ判明する）。
- **ONNX parity失敗3件は既存の技術的負債と確認済み（本ADRの実装とは無関係）**:
  `tests/deploy/test_model_export_onnx_parity.py`の3テスト
  （`test_export_onnx_matches_eager_model_color`等）は、`training/deploy/model_export.py`の
  セッション開始前からの未コミット差分（`self.cfg.target_item.size/chain`参照の追加）と、
  テストフィクスチャ（`_build_synthetic_model_dir`）が`target_item`キーを持たない旧形式の
  cfgを構築していることの不整合が原因（`git diff`で確認済み）。本ADRのconfig
  （`conf_03czt8.yaml`）は`target_item`を含むため03CZT8実行時にはこの問題は再現しないと
  推定されるが、実際に`pipline.py`経由で`deploy.export_model()`を呼ぶ際に確認すること。
- **ci_gate（`tests/ci_gates/test_training_boundary.py`）は本ADRの実装分については
  クリーンだが、既存の技術的負債（`_scratch_566_saturation_drift/run_color_candidate.py`）
  により全体としては引き続きRED**。本ADRの成功基準は「offendersリストに本ADRのファイルが
  含まれないこと」であり、gate全体のPASSではない（v3.1配置場所修正の節参照）。
- edge側C#推論プログラムの対応は別タスクとして追跡する（本ADRのスコープ外）。
