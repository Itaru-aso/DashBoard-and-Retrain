# training/ モジュラモノリス移行 Seam1: deployのFTPアップロード境界化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `training/pipline.py` に混在している ONNX モデルの FTP アップロード処理を、新設の `training/deploy` パッケージの公開API (`deploy.upload_model`) に切り出し、CI gate で境界の逆行を防止する。挙動（アップロード先host/port/path・`skip_upload`ガード・stdout文言）は一切変更しない。

**Architecture:** strangler-fig方式。(1) 現状挙動をcharacterization testで固定 → (2) `training/deploy`パッケージに同等の公開APIをTDDで新規実装 → (3) `pipline.py`を新APIへリダイレクトし旧実装を削除、既存の`test_pipline_skip_flags.py`を新しい境界に合わせて更新 → (4) 境界の逆行を防ぐCI gateテストを追加。設計根拠は `docs/superpowers/specs/2026-07-21-training-modular-monolith-migration-design.md` §2・§8（Seam1）、および先行実装 `D:\0032011\GitLab\shisui\EfficientAD` の同名Seam（`docs/superpowers/plans/2026-07-14-modular-monolith-seam1-deploy-ftp-upload.md`）を参照。

**Tech Stack:** Python 3.11 / pytest 9.x（このマシンに導入済み: `D:\0032011\GitLab\shisui\app_ver2\training` で `python -m pytest` 実行可能、確認済み） / `unittest.mock`（標準ライブラリ） / OmegaConf 2.3.0（既存依存）

## Global Constraints

- 内部アーキテクチャは全モジュール layered に統一する（hexagonal不採用。設計書ADR-1継承）
- 新規の外部依存パッケージは追加しない
- FTPアップロード先ホスト/ポート/ローカルファイルパス/リモートフォルダの決定ロジックは、現状と完全に同一の値を出力すること（挙動変更なし）
- `common.skip_upload` ガード（`execute()` 内、アップロード呼び出しを条件分岐でスキップする仕組み）と、その際に出力される `print(f"skip_upload=true: FTP アップロードをスキップ (mode={sub_mode})")` の文言は1文字も変更しない（設計書ADR-app2: ver2フロントエンドはこの周辺のstdoutをステージ検出に使っていないが、他の保存対象マーカーと同じ原則で扱う）
- テストは `training/` を cwd として `python -m pytest` で実行すること（`cd training && python -m pytest tests/... -v`）。このリポジトリの既存テスト（`tests/test_pipline_skip_flags.py`）も同じ方式で緑化済み（実測: 5 passed, 185.81s、2026-07-21確認済み）。EfficientADのようなルート`conftest.py`は不要（`python -m pytest`はcwdを自動でsys.pathに乗せるため）
- `training/tests/test_pipline_skip_flags.py` は Task 3 で更新が必要（既存の意図＝skip_download/skip_uploadガードの検証は変えない。パッチ対象を新しい境界`pipline.deploy.upload_model`に付け替えるのみ）
- コミットメッセージは日本語、`<type>(<scope>): <subject>` 形式（Conventional Commits）
- 以降のSeam（4, 6）でも `training/tests/test_pipline_skip_flags.py` の更新が必要になる見込み（Seam4: `_run`内の`pipline.ModelExporter`パッチが`pipline.deploy.export_model`に変わる／Seam6: `skip_download`側のパッチ対象が変わる）。各Seamの計画に反映すること

---

## Task 1: 現状のONNXアップロード挙動を固定する characterization test

**Files:**
- Create: `training/tests/deploy/test_ftp_upload_characterization.py`
- Create: `training/tests/deploy/__init__.py`（空。パッケージ化のため）

**Interfaces:**
- Consumes: `pipline.MultiFTPManager`, `pipline.FTPManager`（現状の実装、変更しない）
- Produces: `upload_file_to_ftp(host, port, username, password, local_file_path, remote_folder)` の呼び出し形状（Task2の新実装が満たすべき期待値として記録する）

- [ ] **Step 1: ディレクトリを作成する**

`training/tests/deploy/` ディレクトリは未作成。`training/tests/__init__.py` は存在しない（既存の `tests/test_pipline_skip_flags.py` は無印パッケージのフラットディレクトリのため）。`training/tests/deploy/__init__.py` は空ファイルとして作成する（サブディレクトリをパッケージとして明示するため。既存の `tests/` フラット直下は変更しない）。

- [ ] **Step 2: characterization testを書く**

```python
# training/tests/deploy/test_ftp_upload_characterization.py
"""現状の MultiFTPManager.upload_onnx_model() の挙動を固定するテスト。

Seam1移行（training/deployパッケージへの切り出し）前の挙動を記録し、
Task2で実装する新実装 (deploy.upload_model) が同じ値を出すことの比較対象とする。

実行: cd training && python -m pytest tests/deploy/test_ftp_upload_characterization.py -v
"""
import os
from unittest.mock import patch

from omegaconf import OmegaConf

import pipline


def _make_cfg():
    return OmegaConf.create({
        "common": {
            "model_dir": "./6_model",
            "target_color": "841",
            "mode": "color",
            "ftp_common": {"local_root": "./annotated_data"},
            "ftp_hosts": [
                {
                    "name": "PC1", "host": "10.0.0.1",
                    "username": "u1", "password": "p1",
                    "monochro_port": 2121, "color_port": 2122, "model_port": 2123,
                },
                {
                    "name": "PC2", "host": "10.0.0.2",
                    "username": "u2", "password": "p2",
                    "monochro_port": 3121, "color_port": 3122, "model_port": 3123,
                },
            ],
        }
    })


def test_multi_ftp_manager_uploads_onnx_to_every_host():
    cfg = _make_cfg()
    cfg.common.mode = "color"
    mgr = pipline.MultiFTPManager(cfg)

    with patch("pipline.upload_file_to_ftp") as mock_upload:
        mgr.upload_onnx_model()

    assert mock_upload.call_count == 2
    mock_upload.assert_any_call(
        host="10.0.0.1", port=2123, username="u1", password="p1",
        local_file_path=os.path.join("./6_model", "841", "color", "841_color_model.onnx"),
        remote_folder=os.path.join("./"),
    )
    mock_upload.assert_any_call(
        host="10.0.0.2", port=3123, username="u2", password="p2",
        local_file_path=os.path.join("./6_model", "841", "color", "841_color_model.onnx"),
        remote_folder=os.path.join("./"),
    )
```

- [ ] **Step 3: 実行して現状コードに対してPASSすることを確認する**

Run: `cd training && python -m pytest tests/deploy/test_ftp_upload_characterization.py -v`
Expected: `test_multi_ftp_manager_uploads_onnx_to_every_host PASSED`（現状のコードに対する回帰記録なので、この時点でPASSするのが正しい）

- [ ] **Step 4: commit**

```bash
git add training/tests/deploy/__init__.py training/tests/deploy/test_ftp_upload_characterization.py
git commit -m "$(cat <<'EOF'
test(training-deploy): ONNXモデルFTPアップロードの現状挙動を固定するcharacterization testを追加

training/ のモジュラモノリス移行Seam1（deploy境界化）に先立ち、
MultiFTPManager.upload_onnx_model()の現状挙動（宛先ホスト/ポート/
ローカルファイルパス/リモートフォルダ）をcharacterization testとして固定する。
EOF
)"
```

---

## Task 2: `training/deploy`パッケージに公開APIを新規実装する（TDD red → green）

**Files:**
- Create: `training/deploy/__init__.py`
- Create: `training/deploy/ftp_upload.py`
- Test: `training/tests/deploy/test_ftp_upload.py`

**Interfaces:**
- Consumes: `utils.ftp_common.upload_file_to_ftp(host, port, username, password, local_file_path, remote_folder)`（既存、変更なし。シグネチャは `training/utils/ftp_common.py:333` で確認済み）
- Produces:
  - `deploy.upload_model(cfg, target_color: str, mode: str) -> None`（deployステージの公開API）
  - `deploy.ftp_upload.upload_model_to_host(host_cfg, model_dir: str, target_color: str, mode: str) -> None`（内部実装、deployパッケージ外から直接importしない）

- [ ] **Step 1: 失敗するテストを書く**

```python
# training/tests/deploy/test_ftp_upload.py
"""deploy.upload_model の公開APIテスト。

Task1のcharacterization testと同じ期待値（host/port/local_file_path/remote_folder）を
検証することで、旧実装(pipline.MultiFTPManager)との挙動の一致を保証する。

実行: cd training && python -m pytest tests/deploy/test_ftp_upload.py -v
"""
import os
from unittest.mock import patch

from omegaconf import OmegaConf

import deploy


def _make_cfg():
    return OmegaConf.create({
        "common": {
            "model_dir": "./6_model",
            "ftp_hosts": [
                {
                    "name": "PC1", "host": "10.0.0.1",
                    "username": "u1", "password": "p1",
                    "monochro_port": 2121, "color_port": 2122, "model_port": 2123,
                },
                {
                    "name": "PC2", "host": "10.0.0.2",
                    "username": "u2", "password": "p2",
                    "monochro_port": 3121, "color_port": 3122, "model_port": 3123,
                },
            ],
        }
    })


def test_upload_model_uploads_onnx_to_every_host():
    cfg = _make_cfg()

    with patch("deploy.ftp_upload.upload_file_to_ftp") as mock_upload:
        deploy.upload_model(cfg, target_color="841", mode="color")

    assert mock_upload.call_count == 2
    mock_upload.assert_any_call(
        host="10.0.0.1", port=2123, username="u1", password="p1",
        local_file_path=os.path.join("./6_model", "841", "color", "841_color_model.onnx"),
        remote_folder=os.path.join("./"),
    )
    mock_upload.assert_any_call(
        host="10.0.0.2", port=3123, username="u2", password="p2",
        local_file_path=os.path.join("./6_model", "841", "color", "841_color_model.onnx"),
        remote_folder=os.path.join("./"),
    )


def test_upload_model_continues_when_one_host_fails():
    """1台のアップロードが失敗しても他のホストへのアップロードを継続する
    （MultiFTPManager.upload_onnx_model()の現状挙動: try/exceptで1台ずつスキップ）。"""
    cfg = _make_cfg()

    with patch("deploy.ftp_upload.upload_file_to_ftp") as mock_upload:
        mock_upload.side_effect = [RuntimeError("接続失敗"), None]
        deploy.upload_model(cfg, target_color="841", mode="color")

    assert mock_upload.call_count == 2
```

- [ ] **Step 2: 実行してFAILを確認する**

Run: `cd training && python -m pytest tests/deploy/test_ftp_upload.py -v`
Expected: `ModuleNotFoundError: No module named 'deploy'` によりFAIL（`training/deploy`パッケージが未実装のため）

- [ ] **Step 3: `training/deploy/ftp_upload.py`を実装する**

```python
# training/deploy/ftp_upload.py
"""deployステージ: 学習済みモデル(ONNX)を検査PCへFTP配布する。"""
import os

from utils.ftp_common import upload_file_to_ftp


def upload_model_to_host(host_cfg, model_dir, target_color, mode):
    """1台の検査PCへONNXモデルをFTPアップロードする。

    Args:
        host_cfg: cfg.common.ftp_hosts の要素1件
            (name/host/username/password/model_port等を含む)
        model_dir: ONNXモデルの格納ルート (cfg.common.model_dir)
        target_color: 色番号
        mode: "color" or "monochro"
    """
    target_color = str(target_color)
    model_file_name = f"{target_color}_{mode}_model.onnx"
    onnx_file_path = os.path.join(model_dir, target_color, mode, model_file_name)

    upload_file_to_ftp(
        host=host_cfg.host,
        port=host_cfg.model_port,
        username=host_cfg.username,
        password=host_cfg.password,
        local_file_path=onnx_file_path,
        remote_folder=os.path.join("./"),
    )


def upload_model(cfg, target_color, mode):
    """全検査PCへONNXモデルをFTPアップロードする（deployステージの公開API）。

    いずれかのホストへのアップロードが失敗しても、他のホストへの
    アップロードは継続する（1台の障害でパイプライン全体を止めない）。
    """
    for host_cfg in cfg.common.ftp_hosts:
        try:
            print(f"📤 [{host_cfg.name}] へアップロード中...")
            upload_model_to_host(host_cfg, cfg.common.model_dir, target_color, mode)
            print(f"✅ [{host_cfg.name}] アップロード完了")
        except Exception as e:
            print(f"⚠ [{host_cfg.name}] へのアップロード失敗（スキップ）: {e}")
```

- [ ] **Step 4: `training/deploy/__init__.py`を実装する**

```python
# training/deploy/__init__.py
"""deployステージの公開API。

deployパッケージ外からは `deploy.upload_model` のみを使用すること。
`deploy.ftp_upload.upload_model_to_host` 等の内部関数を外部から
直接importしてはならない（境界はtests/ci_gates/test_deploy_boundary.pyで検証）。
"""
from deploy.ftp_upload import upload_model

__all__ = ["upload_model"]
```

- [ ] **Step 5: 実行してPASSを確認する**

Run: `cd training && python -m pytest tests/deploy/test_ftp_upload.py -v`
Expected: `test_upload_model_uploads_onnx_to_every_host PASSED`, `test_upload_model_continues_when_one_host_fails PASSED`

- [ ] **Step 6: commit**

```bash
git add training/deploy/__init__.py training/deploy/ftp_upload.py training/tests/deploy/test_ftp_upload.py
git commit -m "$(cat <<'EOF'
feat(training-deploy): ONNXモデルFTPアップロードのdeploy公開APIを新設

deploy.upload_model(cfg, target_color, mode) を追加。
pipline.MultiFTPManager.upload_onnx_model()と同一の
宛先決定ロジック（ホスト/ポート/ローカルファイルパス/リモートフォルダ）を
tests/deploy/test_ftp_upload_characterization.pyと同じ期待値で検証。
EOF
)"
```

---

## Task 3: `pipline.py`を`deploy`公開API経由にリダイレクトし旧実装を削除する

**Files:**
- Modify: `training/pipline.py`（import文、`FTPManager.__init__`、`FTPManager.upload_onnx_model`、`MultiFTPManager.upload_onnx_model`、`TrainingPipeline.execute()`）
- Modify: `training/tests/test_pipline_skip_flags.py`（パッチ対象を新境界に付け替え）
- Delete: `training/tests/deploy/test_ftp_upload_characterization.py`

**Interfaces:**
- Consumes: `deploy.upload_model(cfg, target_color, mode)`（Task2で実装済み）
- Produces: `pipline.TrainingPipeline.execute()`の観測可能な挙動は変更なし（Task2のテストが引き続き回帰防止テストとして機能する）

- [ ] **Step 1: `pipline.py`のimport文を修正する**

`training/pipline.py` の20行目を変更する。

変更前:
```python
from utils.ftp_common import upload_file_to_ftp, download_ftp_selected, is_directory, AnnotationDownloader
```

変更後:
```python
from utils.ftp_common import download_ftp_selected, is_directory, AnnotationDownloader
```

28行目 `from model_handler import ONNXModelHandler` の直後に1行追加する。

変更前:
```python
from model_handler import ONNXModelHandler
```

変更後:
```python
from model_handler import ONNXModelHandler
import deploy
```

- [ ] **Step 2: `FTPManager.__init__`から不要になった`self.model_port`を削除する**

変更前（310〜320行目）:
```python
class FTPManager:
    def __init__(self, cfg, host_config):
        self.cfg = cfg
        self.name = host_config.name
        self.host = host_config.host
        self.username = host_config.username
        self.password = host_config.password
        self.monochro_port = host_config.monochro_port
        self.color_port = host_config.color_port
        self.model_port = host_config.model_port
        self.local_root = cfg.common.ftp_common.local_root
```

変更後:
```python
class FTPManager:
    def __init__(self, cfg, host_config):
        self.cfg = cfg
        self.name = host_config.name
        self.host = host_config.host
        self.username = host_config.username
        self.password = host_config.password
        self.monochro_port = host_config.monochro_port
        self.color_port = host_config.color_port
        self.local_root = cfg.common.ftp_common.local_root
```

（`self.model_port`はこのStepで削除する`upload_onnx_model`専用の属性であり、`download_images`では使用されていない。）

- [ ] **Step 3: `FTPManager.upload_onnx_model`メソッドを削除する**

削除対象（`download_images`メソッドの直後、`class MultiFTPManager:`の直前、377〜395行目）:
```python
    def upload_onnx_model(self):
        """
        再学習モデルのデプロイ
        """
        mode = self.cfg.common.mode
        target_color = self.cfg.common.target_color
        model_file_name = f"{target_color}_{mode}_model.onnx"
        upload_path = os.path.join("./")
        port = self.model_port
        onnx_file_path = os.path.join(self.cfg.common.model_dir, str(target_color), mode, model_file_name)

        upload_file_to_ftp(
            host=self.host,
            port=port,
            username=self.username,
            password=self.password,
            local_file_path=onnx_file_path,
            remote_folder=upload_path
        )
```

このメソッド全体を削除する（メソッド前後の空行は1行分だけ残し、`download_images`の直後に`class MultiFTPManager:`が続く形にする）。

- [ ] **Step 4: `MultiFTPManager.upload_onnx_model`メソッドを削除する**

削除対象（`MultiFTPManager.download_images`メソッドの直後、419〜426行目）:
```python
    def upload_onnx_model(self):
        for mgr in self.managers:
            try:
                print(f"📤 [{mgr.name}] へアップロード中...")
                mgr.upload_onnx_model()
                print(f"✅ [{mgr.name}] アップロード完了")
            except Exception as e:
                print(f"⚠ [{mgr.name}] へのアップロード失敗（スキップ）: {e}")
```

このメソッド全体を削除する。

- [ ] **Step 5: `TrainingPipeline.execute()`の呼び出し箇所を`deploy.upload_model`に変更する**

変更前（714〜732行目）:
```python
        # 6. ONNX エクスポート + 評価 (両 mode) + アップロード
        # skip_upload=true では FTP 配信をスキップする (ver2 連携: 配信は deployment_service が担う)
        skip_upload = self.cfg.common.get("skip_upload", False)
        for sub_mode in ["monochro", "color"]:
            sub_cfg = build_sub_cfg(self.cfg, sub_mode, gpu_id=0)
            exporter = ModelExporter(sub_cfg)
            exporter.export_onnx()

            mgr = mgr_color if sub_mode == "color" else mgr_monochro
            ev = Evaluator(self.cfg, color, mode=sub_mode, mgr=mgr)
            ev.evaluate()

            self.cfg.common.mode = sub_mode
            if skip_upload:
                print(f"skip_upload=true: FTP アップロードをスキップ (mode={sub_mode})")
            else:
                self.ftp_manager.upload_onnx_model()

        print("パイプライン完了")
```

変更後:
```python
        # 6. ONNX エクスポート + 評価 (両 mode) + アップロード
        # skip_upload=true では FTP 配信をスキップする (ver2 連携: 配信は deployment_service が担う)
        skip_upload = self.cfg.common.get("skip_upload", False)
        for sub_mode in ["monochro", "color"]:
            sub_cfg = build_sub_cfg(self.cfg, sub_mode, gpu_id=0)
            exporter = ModelExporter(sub_cfg)
            exporter.export_onnx()

            mgr = mgr_color if sub_mode == "color" else mgr_monochro
            ev = Evaluator(self.cfg, color, mode=sub_mode, mgr=mgr)
            ev.evaluate()

            self.cfg.common.mode = sub_mode
            if skip_upload:
                print(f"skip_upload=true: FTP アップロードをスキップ (mode={sub_mode})")
            else:
                deploy.upload_model(self.cfg, color, sub_mode)

        print("パイプライン完了")
```

（`skip_upload`ガードと`print`文言は1文字も変更しない。呼び出し先のみ`self.ftp_manager.upload_onnx_model()`→`deploy.upload_model(self.cfg, color, sub_mode)`に変わる。）

- [ ] **Step 6: `training/tests/test_pipline_skip_flags.py`を新境界に合わせて更新する**

`deploy.upload_model`を経由するようになったため、`pipe.ftp_manager.upload_onnx_model`をアサートしていた既存テストはこのままだと壊れる（`test_flags_false_preserves_behavior`は`ftp_manager.upload_onnx_model.call_count == 2`を期待するが、呼ばれなくなるため`0`になりFAILする。`test_skip_upload_true_skips_ftp_upload`は何もパッチしていないモックへの`assert_not_called()`になり形だけのテストになる）。`pipline.deploy.upload_model`をパッチする方式に付け替える。

変更前（全文）:
```python
"""pipline.execute() の薄いラッパ改修（retraining task0）テスト。

`common.skip_download` / `common.skip_upload` で FTP ダウンロード / アップロードを
ガードできること、既定（false）では従来どおり呼ばれること（後方互換）を検証する。
学習本体・重い依存は import 段階でのみ必要で、execute() 内の学習/エクスポート/評価は
モック・パッチで無害化する（実学習・実 FTP は行わない）。

実行: cd training && python -m pytest tests/test_pipline_skip_flags.py
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from omegaconf import OmegaConf

import pipline


def _make_pipeline(skip_download: bool, skip_upload: bool):
    cfg = OmegaConf.create(
        {
            "common": {
                "target_color": "501",
                "pipeline_mode": "train",
                "parallel_train": False,
                "skip_download": skip_download,
                "skip_upload": skip_upload,
                "mode": "color",
            },
            "color": {"mlflow": {"enabled": False}},
            "monochro": {"mlflow": {"enabled": False}},
        }
    )
    p = pipline.TrainingPipeline.__new__(pipline.TrainingPipeline)
    p.cfg = cfg
    p.dataset_manager = MagicMock()
    p.ftp_manager = MagicMock()
    return p


def _run(pipe):
    # 学習・ONNX エクスポート・評価は task0 の対象外。実行を無害化する。
    with patch.object(pipline, "run_trainer"), patch.object(
        pipline, "build_sub_cfg", return_value=OmegaConf.create({})
    ), patch.object(pipline, "ModelExporter"), patch.object(pipline, "Evaluator"):
        pipe.execute()


def test_skip_download_true_skips_ftp_download():
    pipe = _make_pipeline(skip_download=True, skip_upload=False)
    _run(pipe)
    pipe.ftp_manager.download_images.assert_not_called()


def test_skip_upload_true_skips_ftp_upload():
    pipe = _make_pipeline(skip_download=False, skip_upload=True)
    _run(pipe)
    pipe.ftp_manager.upload_onnx_model.assert_not_called()


def test_flags_false_preserves_behavior():
    pipe = _make_pipeline(skip_download=False, skip_upload=False)
    _run(pipe)
    # 従来どおり monochro / color の2回ずつ呼ばれる（後方互換）。
    assert pipe.ftp_manager.download_images.call_count == 2
    assert pipe.ftp_manager.upload_onnx_model.call_count == 2
```

変更後（全文）:
```python
"""pipline.execute() の薄いラッパ改修（retraining task0）テスト。

`common.skip_download` / `common.skip_upload` で FTP ダウンロード / アップロードを
ガードできること、既定（false）では従来どおり呼ばれること（後方互換）を検証する。
学習本体・重い依存は import 段階でのみ必要で、execute() 内の学習/エクスポート/評価は
モック・パッチで無害化する（実学習・実 FTP は行わない）。

Seam1移行（training/deploy境界化）により、アップロードは
`pipline.ftp_manager.upload_onnx_model()` ではなく `deploy.upload_model(...)` 経由になった。
本テストのパッチ対象もそれに合わせて `pipline.deploy.upload_model` に付け替えている
（検証する意図＝skip_upload時にアップロードが呼ばれないこと、は変更していない）。

実行: cd training && python -m pytest tests/test_pipline_skip_flags.py
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from omegaconf import OmegaConf

import pipline


def _make_pipeline(skip_download: bool, skip_upload: bool):
    cfg = OmegaConf.create(
        {
            "common": {
                "target_color": "501",
                "pipeline_mode": "train",
                "parallel_train": False,
                "skip_download": skip_download,
                "skip_upload": skip_upload,
                "mode": "color",
            },
            "color": {"mlflow": {"enabled": False}},
            "monochro": {"mlflow": {"enabled": False}},
        }
    )
    p = pipline.TrainingPipeline.__new__(pipline.TrainingPipeline)
    p.cfg = cfg
    p.dataset_manager = MagicMock()
    p.ftp_manager = MagicMock()
    return p


def _run(pipe):
    # 学習・ONNX エクスポート・評価・deployアップロードは task0 の対象外。実行を無害化する。
    with patch.object(pipline, "run_trainer"), patch.object(
        pipline, "build_sub_cfg", return_value=OmegaConf.create({})
    ), patch.object(pipline, "ModelExporter"), patch.object(pipline, "Evaluator"), patch.object(
        pipline.deploy, "upload_model"
    ) as mock_upload_model:
        pipe.execute()
    return mock_upload_model


def test_skip_download_true_skips_ftp_download():
    pipe = _make_pipeline(skip_download=True, skip_upload=False)
    _run(pipe)
    pipe.ftp_manager.download_images.assert_not_called()


def test_skip_upload_true_skips_ftp_upload():
    pipe = _make_pipeline(skip_download=False, skip_upload=True)
    mock_upload_model = _run(pipe)
    mock_upload_model.assert_not_called()


def test_flags_false_preserves_behavior():
    pipe = _make_pipeline(skip_download=False, skip_upload=False)
    mock_upload_model = _run(pipe)
    # 従来どおり monochro / color の2回ずつ呼ばれる（後方互換）。
    assert pipe.ftp_manager.download_images.call_count == 2
    assert mock_upload_model.call_count == 2
```

- [ ] **Step 7: Task1のcharacterization testを削除する**

対象メソッド(`FTPManager.upload_onnx_model` / `MultiFTPManager.upload_onnx_model`)が削除されたため、これらを対象としていたテストは役目を終える。Task2のテスト(`training/tests/deploy/test_ftp_upload.py`)が同じ期待値を検証しているため、回帰防止の役割はそちらに引き継がれている。

```bash
git rm training/tests/deploy/test_ftp_upload_characterization.py
```

- [ ] **Step 8: 全テストを再実行し、回帰していないことを確認する**

Run: `cd training && python -m pytest tests/ -v`
Expected: `tests/deploy/test_ftp_upload.py` の2件、`tests/test_pipline_skip_flags.py` の3件、`tests/test_pipline_spawn_context.py` の2件、すべてPASS（計7件）

- [ ] **Step 9: `pipline.py`がimportエラーなく読み込めることを確認する**

Run: `cd training && python -c "import pipline"`
Expected: エラーなく終了する（exit code 0、出力なし）

- [ ] **Step 10: commit**

```bash
git add training/pipline.py training/tests/test_pipline_skip_flags.py
git rm training/tests/deploy/test_ftp_upload_characterization.py
git commit -m "$(cat <<'EOF'
refactor(training-pipline): ONNXモデルFTPアップロードをdeploy公開API経由にリダイレクト

TrainingPipeline.execute()からのFTPアップロード呼び出しを
deploy.upload_model(cfg, target_color, mode)に変更し、
pipline.py内のFTPManager.upload_onnx_model/MultiFTPManager.upload_onnx_model
（旧実装）を削除。skip_uploadガードとstdout文言は変更なし。
test_pipline_skip_flags.pyのパッチ対象を新境界(deploy.upload_model)に
付け替え、検証意図（skip_upload時に非呼び出し）は維持。
Task1のcharacterization testは対象メソッド削除に伴い削除。
EOF
)"
```

---

## Task 4: CI Gate — deploy境界の逆行を防ぐテスト

**Files:**
- Create: `training/tests/ci_gates/__init__.py`（空）
- Create: `training/tests/ci_gates/test_deploy_boundary.py`

**Interfaces:**
- Consumes: `training/` 配下の`*.py`ファイル群（ソースコード自体を検査対象とする。`backend/`等は対象外＝設計書ADR-app4）
- Produces: 回帰防止用のCI gate（新たなランタイムAPIは提供しない）

- [ ] **Step 1: 境界テストを書く**

```python
# training/tests/ci_gates/test_deploy_boundary.py
"""training/deployステージの境界を守るCI gate。

utils.ftp_common.upload_file_to_ftp（ONNXモデルアップロードの低レベル関数）を
直接importできるのは training/deploy パッケージ内のみであることを保証する。
他のモジュールは deploy.upload_model の公開APIのみを使用すること。

走査対象は training/ 配下のみに限定する（app_ver2はEfficientADと異なり、
同一リポジトリに backend/ 等の無関係なPythonコードを含むため。設計書ADR-app4）。
"""
import ast
from pathlib import Path

TRAINING_ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIR_NAMES = {"tests", "deploy", "__pycache__"}


def _imported_names(file_path):
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.name)
    return names


def test_pipline_does_not_import_ftp_upload_helper_directly():
    """pipline.py は utils.ftp_common.upload_file_to_ftp を直接importしてはいけない。
    ONNXモデルのFTPアップロードは deploy モジュールの公開APIを経由すること。"""
    pipline_path = TRAINING_ROOT / "pipline.py"
    assert "upload_file_to_ftp" not in _imported_names(pipline_path)


def test_only_deploy_module_imports_ftp_upload_helper():
    """utils.ftp_common.upload_file_to_ftp を直接importしているのは
    training/deploy パッケージ内のみであること（境界の逆行を防ぐラチェット）。"""
    offenders = []
    for py_file in TRAINING_ROOT.rglob("*.py"):
        rel_parts = py_file.relative_to(TRAINING_ROOT).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if "upload_file_to_ftp" in _imported_names(py_file):
            offenders.append(str(py_file.relative_to(TRAINING_ROOT)))
    assert offenders == [], f"deploy外からのupload_file_to_ftp直接importを検出: {offenders}"
```

- [ ] **Step 2: 実行してPASSを確認する**

Run: `cd training && python -m pytest tests/ci_gates/test_deploy_boundary.py -v`
Expected: `test_pipline_does_not_import_ftp_upload_helper_directly PASSED`, `test_only_deploy_module_imports_ftp_upload_helper PASSED`

- [ ] **Step 3: ラチェットが実際に機能することを手動で確認する**

`training/pipline.py`の20行目を一時的に以下へ変更する（確認用、最終的に元に戻す）:

```python
from utils.ftp_common import upload_file_to_ftp, download_ftp_selected, is_directory, AnnotationDownloader
```

Run: `cd training && python -m pytest tests/ci_gates/test_deploy_boundary.py -v`
Expected: `test_pipline_does_not_import_ftp_upload_helper_directly FAILED`（ゲートが正しく違反を検出することの確認）

確認後、`training/pipline.py`の20行目を元に戻す:

```python
from utils.ftp_common import download_ftp_selected, is_directory, AnnotationDownloader
```

Run: `cd training && python -m pytest tests/ci_gates/test_deploy_boundary.py -v`
Expected: 再び全てPASSする

- [ ] **Step 4: commit**

```bash
git add training/tests/ci_gates/__init__.py training/tests/ci_gates/test_deploy_boundary.py
git commit -m "$(cat <<'EOF'
test(training-deploy): deploy境界の逆行を防ぐCI gateテストを追加

utils.ftp_common.upload_file_to_ftp を直接importできるのは
training/deployパッケージ内のみであることを検証するテストを追加。
走査対象はtraining/配下に限定（backend/等の無関係なPythonコードを
誤検出しないため。設計書ADR-app4）。
Seam1（deployのFTPアップロード境界化）の完了条件として、
以後の境界逆行をCIで検出できるようにする。
EOF
)"
```

---

## 完了条件（このSeamのDone）

- `deploy.upload_model(cfg, target_color, mode)` が公開APIとして存在し、`training/pipline.py`はこれ経由でのみFTPアップロードを行う
- `training/pipline.py`から`FTPManager.upload_onnx_model` / `MultiFTPManager.upload_onnx_model`が削除されている
- `skip_upload`ガードと`print`文言（設計書§1のstdout保存対象）が変更されていない
- `training/tests/test_pipline_skip_flags.py`が新境界（`pipline.deploy.upload_model`）に対して緑化されている
- CI gate（`training/tests/ci_gates/test_deploy_boundary.py`）が導入され、境界の逆行を検出できることをTask4 Step3で確認済み
- `cd training && python -m pytest tests/ -v` が全件PASS（Task3 Step8で確認、計7件）
- 設計書（`docs/superpowers/specs/2026-07-21-training-modular-monolith-migration-design.md`）§8のSeam1が完了としてマークできる状態になっている
