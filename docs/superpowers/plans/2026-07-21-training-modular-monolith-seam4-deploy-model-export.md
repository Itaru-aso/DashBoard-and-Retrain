# training/ モジュラモノリス移行 Seam4: deploy(model_exporter.py)境界確立 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `training/model_exporter.py`にある`ModelExporter`クラス(ONNXエクスポート処理)を、既存の`training/deploy/`パッケージ(Seam1で作成済み)に`deploy/model_export.py`として移動し、`deploy.export_model(cfg)`という公開関数を新設する。`training/pipline.py`はこの公開APIのみを経由するようにし、CI gateで境界の逆行を防ぐ。

**Architecture:** strangler-fig方式。Seam1/2と同じ「挙動保存の抽出」(Seam3のような意図的な挙動変更ではない)。`ModelExporter`のロジックは無変更でそのまま移動する。先行実装 `D:\0032011\GitLab\shisui\EfficientAD` の同名Seam（`docs/superpowers/plans/2026-07-15-modular-monolith-seam4-deploy-model-export.md`）を参照。

**Tech Stack:** Python, PyTorch, ONNX(1.16.0)/onnxruntime(1.18.0、いずれもこのマシンに導入済み・追加インストール不要)、pytest。

## Global Constraints

- これは挙動保存のリファクタリングである。`ModelExporter`クラスのロジックは1文字も変更しない
- `print(f"Exported ONNX: {onnx_path}")`の文言は1文字も変更しない（設計書ADR-app2のstdout保存対象マーカー、`^Exported ONNX:`。ver2フロントエンドのステージ検出に使われている）
- 検証方法はcharacterization test: エクスポートされたONNXの推論結果が、`training/model.py`の`EfficientADFullModel`のeager実行結果と一致すること。この一致は移動前(Task1)にまず確立し、移動後(Task2)も変わらないことを確認する
- CI gate: `training/tests/ci_gates/test_deploy_boundary.py`に、`deploy.model_export`への外部からの直接importを禁止するモジュール名ベースの検査を追加する(既存の`upload_file_to_ftp`関数名ベースの検査パターンは維持)
- CI gateの走査対象は`training/`配下に限定する（設計書ADR-app4）
- 日本語コミットメッセージ、Conventional Commits形式(`<type>(<scope>): <subject>`)
- `training/tests/`配下は`__init__.py`を作らない(既存方針、conftest.py方式。ただしSeam1で作成済みの`training/tests/deploy/__init__.py`等は残す)
- `training/pipline.py`には本Seamと無関係な既存WIP（`_spawn_with_gpu_env`のspawn-context修正）が作業ツリーに残っている。各タスクのコミット前に混入がないことを確認する
- 対象ファイルの現状(2026-07-21時点、Seam1〜3完了後の状態、app_ver2の実ソースで確認済み):
  - `training/model_exporter.py`(192行): `class ModelExporter`(`__init__(self, cfg)`, `load_models()`, `load_parameters()`, `export_onnx() -> str`)。`cfg`は`training/pipline.py`の`build_sub_cfg(cfg, mode, gpu_id)`が返すflatなOmegaConf DictConfig(`cfg.model_dir`, `cfg.target_color`, `cfg.mode`, `cfg.image_size_height`, `cfg.image_size_width`, `cfg.out_channels`(`.get('out_channels', 384)`で既定384)、`cfg.gpu_id`を属性として持つ)。`export_onnx()`は`{color}_{mode}_model.onnx`という固定ファイル名でONNXを出力し、`onnx_model.metadata_props`にthreshold/channel_weights_enabled/edge_mask_w/cand1_enabled/cand1_T/score_typeを追記する
  - `training/pipline.py`: **27行目**`from model_exporter import ModelExporter`、**29行目**`import deploy`(Seam1で追加済み)、**623-624行目**`exporter = ModelExporter(sub_cfg); exporter.export_onnx()`(戻り値は使用されていない)、**632行目**`self.ftp_manager`ではなく既に`deploy.upload_model(self.cfg, color, sub_mode)`(Seam1で切替済み)。`model_exporter`の呼び出し元はこのファイルのみ(grep確認済み)
  - `training/deploy/__init__.py`: 現在`from deploy.ftp_upload import upload_model`のみを公開、`__all__ = ["upload_model"]`
  - `training/deploy/ftp_upload.py`: Seam1で作成済み、本計画では変更不要
  - `training/tests/ci_gates/test_deploy_boundary.py`: 現状は`upload_file_to_ftp`という関数名ベースの直接import検査のみ(`_imported_names()`がImport/ImportFromのalias名を集める方式。`TRAINING_ROOT`ベース)
  - `training/tests/deploy/test_ftp_upload.py`: Seam1で作成済み、本計画では変更不要
  - `training/utils/common.py`の`get_pdn_small(out_channels, padding=False, dropout_rate=0.2)`・`get_autoencoder(out_channels=384, image_size_height=256, image_size_width=512)`: teacher/student/autoencoderの構築関数(既存、変更不要)
  - `training/model.py`の`EfficientADFullModel(mode, height, width, teacher, student, autoencoder, teacher_mean, teacher_std, st_para, ae_para, q_st_start=None, q_st_end=None, q_ae_start=None, q_ae_end=None, channel_weights=None, threshold=None, edge_mask_w=0, cand1=None)`: forward()は`utils.scoring_transform.compute_anomaly_score`に委譲済み(Seam3完了)。本計画ではこのクラスを直接構築してeager実行の比較対象として使う(変更不要)
  - ベースラインテスト: `cd training && python -m pytest tests/ -v` で **28 passed**（2026-07-21時点、Seam1〜3完了後。実測済み。うち2件は本Seamと無関係な既存WIP由来）

---

## Task 1: characterization test — ONNXエクスポート結果がeager実行と一致することを確認する(現状の`training/model_exporter.py`に対して)

**Files:**
- Create: `training/tests/test_model_exporter_onnx_parity.py`

**Interfaces:**
- Consumes: `model_exporter.ModelExporter`(既存)、`model.EfficientADFullModel`(既存)、`utils.common.get_pdn_small`/`get_autoencoder`(既存)
- Produces: `_build_synthetic_model_dir(tmp_path, mode, cand1_enabled, seed=0) -> dict` というテスト内ヘルパー関数。戻り値dict: `{'cfg': OmegaConf DictConfig, 'para': dict, 'image_np': np.ndarray (uint8, shape (H,W,3)), 'height': int, 'width': int}`。Task2でこのテストファイルの import 行のみを変更して再利用する

- [ ] **Step 1: テストファイルを作成する**

`training/tests/test_model_exporter_onnx_parity.py` を新規作成する:

```python
"""model_exporter.ModelExporter がエクスポートするONNXの推論結果が、
model.py の EfficientADFullModel のeager実行結果と一致することを保証する
characterization test。

Seam4でこのファイル(および対象クラス)がdeploy/model_export.pyへ移動した後も、
import行のみ変更してこのテストが変わらず通ることを確認する(挙動保存の証拠)。

実行: cd training && python -m pytest tests/test_model_exporter_onnx_parity.py -v
"""
import json
import os

import numpy as np
import onnxruntime
import torch
from omegaconf import OmegaConf

from model import EfficientADFullModel
from model_exporter import ModelExporter
from utils.common import get_autoencoder, get_pdn_small

OUT_CHANNELS = 384


def _build_synthetic_model_dir(tmp_path, mode, cand1_enabled, seed=0):
    """teacher/student/autoencoderの.pthファイルとpara.jsonをtmp_pathに書き出し、
    ModelExporterがそのまま読み込める構造を用意する。
    """
    torch.manual_seed(seed)
    np.random.seed(seed)

    height, width = 256, 512
    color = "841"

    teacher = get_pdn_small(OUT_CHANNELS)
    student = get_pdn_small(2 * OUT_CHANNELS)
    autoencoder = get_autoencoder(OUT_CHANNELS, image_size_height=height, image_size_width=width)
    teacher.eval()
    student.eval()
    autoencoder.eval()

    input_dir = tmp_path / color / mode
    input_dir.mkdir(parents=True, exist_ok=True)
    torch.save(teacher.state_dict(), input_dir / "teacher_state_best.pth")
    torch.save(student.state_dict(), input_dir / "student_state_best.pth")
    torch.save(autoencoder.state_dict(), input_dir / "autoencoder_state_best.pth")

    img_np = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)

    teacher_mean = torch.zeros(1, OUT_CHANNELS, 1, 1)
    teacher_std = torch.ones(1, OUT_CHANNELS, 1, 1)

    image_norm = torch.from_numpy(img_np.transpose(2, 0, 1)[None]).float() / 255.0
    imagenet_mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
    imagenet_std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
    image_norm = (image_norm - imagenet_mean) / imagenet_std

    with torch.no_grad():
        t_out = teacher(image_norm)
        t_out_n = (t_out - teacher_mean) / teacher_std
        s_out = student(image_norm)
        map_st = torch.mean((t_out_n - s_out[:, :OUT_CHANNELS]) ** 2, dim=1, keepdim=True)
        ae_out = autoencoder(image_norm)
        map_ae = torch.mean((ae_out - s_out[:, OUT_CHANNELS:]) ** 2, dim=1, keepdim=True)

    para = {
        "teacher_mean_1d": teacher_mean.view(-1).tolist(),
        "teacher_std_1d": teacher_std.view(-1).tolist(),
        "q_st_start": map_st.min().item(),
        "q_st_end": map_st.max().item(),
        "q_ae_start": map_ae.min().item(),
        "q_ae_end": map_ae.max().item(),
        "st_para": 1.0,
        "ae_para": 0.0,
        "threshold": 0.5,
        "edge_mask_w": 0,
        "image_size_height": height,
        "image_size_width": width,
    }
    if cand1_enabled:
        torch.manual_seed(seed + 1)
        map_h, map_w = map_st.shape[2], map_st.shape[3]
        mu = (torch.rand(map_h, map_w) * 0.05).numpy().astype(np.float32)
        sigma = (torch.rand(map_h, map_w) * 0.04 + 0.01).numpy().astype(np.float32)
        para["cand1_enabled"] = True
        para["cand1_mu"] = mu.tolist()
        para["cand1_sigma"] = sigma.tolist()
        para["cand1_A"] = 1.0
        para["cand1_Z"] = 3.0
        para["cand1_T"] = 1.0

    with open(input_dir / "para.json", "w", encoding="utf-8") as f:
        json.dump(para, f)

    cfg = OmegaConf.create({
        "model_dir": str(tmp_path),
        "target_color": color,
        "mode": mode,
        "image_size_height": height,
        "image_size_width": width,
        "out_channels": OUT_CHANNELS,
        "gpu_id": 0,
    })

    return {"cfg": cfg, "para": para, "image_np": img_np, "height": height, "width": width}


def _run_onnx(onnx_path, image_np):
    """ONNXモデルに raw pixel (0-255) の画像テンソルを与えて推論する。"""
    session = onnxruntime.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    image_t = image_np.transpose(2, 0, 1)[None].astype(np.float32)
    outputs = session.run(None, {"input": image_t})
    return outputs[0], session


def _run_eager(built, mode):
    """model.py の EfficientADFullModel を直接構築してeager実行する。"""
    cfg, para, image_np = built["cfg"], built["para"], built["image_np"]
    color, height, width = cfg.target_color, built["height"], built["width"]
    input_dir = os.path.join(cfg.model_dir, color, mode)

    teacher = get_pdn_small(OUT_CHANNELS)
    student = get_pdn_small(2 * OUT_CHANNELS)
    autoencoder = get_autoencoder(OUT_CHANNELS, image_size_height=height, image_size_width=width)
    teacher.load_state_dict(torch.load(os.path.join(input_dir, "teacher_state_best.pth")))
    student.load_state_dict(torch.load(os.path.join(input_dir, "student_state_best.pth")))
    autoencoder.load_state_dict(torch.load(os.path.join(input_dir, "autoencoder_state_best.pth")))
    teacher.eval()
    student.eval()
    autoencoder.eval()

    cand1 = None
    if para.get("cand1_enabled", False):
        cand1 = {
            "mu": np.array(para["cand1_mu"], dtype=np.float32),
            "sigma": np.array(para["cand1_sigma"], dtype=np.float32),
            "A": float(para["cand1_A"]),
            "Z": float(para["cand1_Z"]),
            "T": float(para["cand1_T"]),
        }

    model = EfficientADFullModel(
        mode, height, width, teacher, student, autoencoder,
        torch.tensor(para["teacher_mean_1d"]), torch.tensor(para["teacher_std_1d"]),
        st_para=para["st_para"], ae_para=para["ae_para"],
        q_st_start=torch.tensor(para["q_st_start"]), q_st_end=torch.tensor(para["q_st_end"]),
        q_ae_start=torch.tensor(para["q_ae_start"]), q_ae_end=torch.tensor(para["q_ae_end"]),
        threshold=para["threshold"], edge_mask_w=para.get("edge_mask_w", 0), cand1=cand1,
    ).eval()

    image_t = torch.from_numpy(image_np.transpose(2, 0, 1)[None]).float()
    with torch.no_grad():
        return model(image_t).numpy()


def test_export_onnx_matches_eager_model_color(tmp_path):
    """color構成(cand1無し)でONNX出力とeager実行が一致することを確認する。"""
    built = _build_synthetic_model_dir(tmp_path, mode="color", cand1_enabled=False)
    onnx_path = ModelExporter(built["cfg"]).export_onnx()

    onnx_output, session = _run_onnx(onnx_path, built["image_np"])
    eager_output = _run_eager(built, mode="color")

    np.testing.assert_allclose(onnx_output, eager_output, rtol=1e-3, atol=1e-3)

    # onnxruntimeはメタデータをget_modelmeta().custom_metadata_mapで公開する
    meta = dict(session.get_modelmeta().custom_metadata_map)
    assert meta["threshold"] == str(built["para"]["threshold"])
    assert meta["edge_mask_w"] == "0"
    assert meta["cand1_enabled"] == "false"
    assert meta["score_type"] == "raw"


def test_export_onnx_matches_eager_model_monochro_cand1(tmp_path):
    """monochro+cand1有効構成でONNX出力とeager実行が一致することを確認する。"""
    built = _build_synthetic_model_dir(tmp_path, mode="monochro", cand1_enabled=True)
    onnx_path = ModelExporter(built["cfg"]).export_onnx()

    onnx_output, session = _run_onnx(onnx_path, built["image_np"])
    eager_output = _run_eager(built, mode="monochro")

    np.testing.assert_allclose(onnx_output, eager_output, rtol=1e-3, atol=1e-3)

    meta = dict(session.get_modelmeta().custom_metadata_map)
    assert meta["threshold"] == str(built["para"]["threshold"])
    assert meta["cand1_enabled"] == "true"
    assert meta["cand1_T"] == str(built["para"]["cand1_T"])
    assert meta["score_type"] == "unified"
```

- [ ] **Step 2: テストを実行して成功を確認する**

Run: `cd training && python -m pytest tests/test_model_exporter_onnx_parity.py -v`
Expected: 2件ともPASS。`model_exporter.ModelExporter`が現状正しくONNXをエクスポートしており、そのONNX推論結果がeager実行(`model.py`の`EfficientADFullModel`)と数値的に一致することが確認できる

- [ ] **Step 3: コミット**

```bash
git add training/tests/test_model_exporter_onnx_parity.py
git commit -m "$(cat <<'EOF'
test(training-deploy): model_exporterのONNXエクスポートとeager実行の一致を検証するcharacterization testを追加

Seam4(deploy境界確立)に先立ち、training/model_exporter.pyの
ModelExporter.export_onnx()がエクスポートするONNXの推論結果が、
training/model.pyのEfficientADFullModelのeager実行結果と一致することを
characterization testとして固定する。
EOF
)"
```

---

## Task 2: `deploy/model_export.py`への移動、`pipline.py`のリダイレクト、CI gate更新

**Files:**
- Create: `training/deploy/model_export.py`
- Modify: `training/deploy/__init__.py`
- Modify: `training/pipline.py:27`(import削除), `training/pipline.py:623-624`(呼び出し置換)
- Modify: `training/tests/ci_gates/test_deploy_boundary.py`
- Move: `training/tests/test_model_exporter_onnx_parity.py` → `training/tests/deploy/test_model_export_onnx_parity.py`(import行のみ変更)
- Delete: `training/model_exporter.py`

**Interfaces:**
- Consumes: Task1で確立した`training/tests/test_model_exporter_onnx_parity.py`のテストロジック(移動して再利用)
- Produces: `deploy.export_model(cfg) -> str`(deployパッケージの公開API、既存の`deploy.upload_model`と同じスタイル)

- [ ] **Step 1: `training/deploy/model_export.py`を新規作成する**

`training/model_exporter.py`の内容をそのまま`training/deploy/model_export.py`にコピーし、末尾に`export_model()`関数を追加する:

```python
from __future__ import annotations

import json
import os
import re

import torch
import torch.nn as nn
from omegaconf import DictConfig, OmegaConf

from model import EfficientADFullModel, load_para
from utils.common import get_autoencoder, get_pdn_small


class ModelExporter:
    """EfficientAD 学習済みモデルを ONNX 形式にエクスポートするクラス。

    Teacher-Student ネットワークと AutoEncoder を統合した
    EfficientADFullModel を構築し、ONNX ファイルとして保存する。
    monochro（凹凸検査）/ color（色検査）の両モードに対応。

    対応機能:
    - チャネル重み (channel_weights) の組み込み
    - AE 無効時 (ae_para=0) の安全処理
    - threshold の組み込み
    - teacher_mean_1d (新形式) / teacher_mean (旧形式) の両対応
    - ONNX ファイル名: {color}_{mode}_model.onnx (検査PC FTP 互換)
    - ONNX メタデータ: threshold / channel_weights_enabled を追記
    """

    def __init__(self, cfg: DictConfig) -> None:
        self.cfg: DictConfig = cfg
        self.input_dir: str = os.path.join(
            self.cfg.model_dir, str(self.cfg.target_color), self.cfg.mode)

        self.height: int = self.cfg.image_size_height
        self.width: int = self.cfg.image_size_width
        self.out_channels: int = self.cfg.get('out_channels', 384)

        self.gpu_id: int = self.cfg.gpu_id
        self.device: torch.device = torch.device(
            f'cuda:{self.gpu_id}' if torch.cuda.is_available() else 'cpu')
        self.mode: str = self.cfg.mode

    def load_models(self) -> tuple[nn.Module, nn.Module, nn.Module]:
        """学習済みの Teacher, Student, AutoEncoder モデルを読み込む。"""
        teacher_model: nn.Module = get_pdn_small(self.out_channels)
        student_model: nn.Module = get_pdn_small(2 * self.out_channels)
        autoencoder_model: nn.Module = get_autoencoder(
            self.out_channels, image_size_height=self.height, image_size_width=self.width)

        teacher_model.load_state_dict(torch.load(
            os.path.join(self.input_dir, 'teacher_state_best.pth'),
            map_location=self.device))
        student_model.load_state_dict(torch.load(
            os.path.join(self.input_dir, 'student_state_best.pth'),
            map_location=self.device))
        autoencoder_model.load_state_dict(torch.load(
            os.path.join(self.input_dir, 'autoencoder_state_best.pth'),
            map_location=self.device))

        teacher_model.eval()
        student_model.eval()
        autoencoder_model.eval()

        return teacher_model, student_model, autoencoder_model

    def load_parameters(self) -> dict:
        """学習時に保存された正規化パラメータを para.json から読み込む。

        新形式 (teacher_mean_1d) と旧形式 (teacher_mean) の両方に対応。
        JSON が壊れている場合（ブラケット不整合）は自動修復を試みる。

        Returns:
            load_para() の返り値 (dict)
        """
        para_path: str = os.path.join(self.input_dir, 'para.json')

        # JSON 破損チェック・修復
        with open(para_path, 'r', encoding='utf-8') as f:
            raw = f.read()

        try:
            json.loads(raw)
        except json.JSONDecodeError:
            fixed = raw
            opens_brace = fixed.count('{')
            closes_brace = fixed.count('}')
            to_trim = max(0, closes_brace - opens_brace)
            if to_trim:
                fixed = re.sub(r"\s*}\s*$", "", fixed, count=to_trim)

            opens_bracket = fixed.count('[')
            closes_bracket = fixed.count(']')
            to_trim = max(0, closes_bracket - opens_bracket)
            if to_trim:
                fixed = re.sub(r"\s*]\s*$", "", fixed, count=to_trim)

            try:
                json.loads(fixed)
                with open(para_path, 'w', encoding='utf-8') as f:
                    f.write(fixed)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"JSON修正後も読み込み失敗: {e}")

        return load_para(para_path, device=self.device)

    def export_onnx(self) -> str:
        """EfficientADFullModel を ONNX 形式でエクスポートする。

        ファイル名: {color}_{mode}_model.onnx (検査PC FTP アップロード処理との互換維持)
        ONNX メタデータ: threshold / channel_weights_enabled を追記

        Returns:
            エクスポートした ONNX ファイルのパス
        """
        import onnx

        teacher_model, student_model, autoencoder_model = self.load_models()
        para = self.load_parameters()

        model = EfficientADFullModel(
            self.mode, self.height, self.width,
            teacher_model, student_model, autoencoder_model,
            para['teacher_mean'], para['teacher_std'],
            st_para=para['st_para'], ae_para=para['ae_para'],
            q_st_start=para['q_st_start'], q_st_end=para['q_st_end'],
            q_ae_start=para['q_ae_start'], q_ae_end=para['q_ae_end'],
            channel_weights=para['channel_weights'],
            threshold=para['threshold'],
            edge_mask_w=para.get('edge_mask_w', 0),
            cand1=para.get('cand1'),  # monochro+cand1 のとき z-OR 統合スコアを出力
        ).to(self.device)
        model.eval()

        dummy_input: torch.Tensor = torch.randn(
            1, 3, self.height, self.width).to(self.device) * 255

        # 検査PCのFTPアップロード処理との互換のため {color}_{mode}_model.onnx を維持
        onnx_path: str = os.path.join(
            self.input_dir, f"{self.cfg.target_color}_{self.cfg.mode}_model.onnx")

        torch.onnx.export(
            model, dummy_input, onnx_path,
            input_names=["input"],
            output_names=["output"],
            opset_version=11,
            dynamic_axes={
                "input": {0: "batch_size"},
                "output": {0: "batch_size"},
            }
        )

        # ONNX メタデータに threshold / channel_weights_enabled / edge_mask_w を追記
        onnx_model = onnx.load(onnx_path)
        if para.get('threshold') is not None:
            meta = onnx_model.metadata_props.add()
            meta.key = 'threshold'
            meta.value = str(para['threshold'])
        if para.get('channel_weights') is not None:
            meta = onnx_model.metadata_props.add()
            meta.key = 'channel_weights_enabled'
            meta.value = 'true'
        # edge_mask_w (Phase H): C# 側でのトレース用にメタデータに記録 (推論挙動自体は ONNX に内包済)
        edge_mask_w = int(para.get('edge_mask_w', 0))
        meta = onnx_model.metadata_props.add()
        meta.key = 'edge_mask_w'
        meta.value = str(edge_mask_w)
        # 候補1 (z-score OR): C# 側で出力の意味・閾値を判別するためメタに記録。
        # score_type=unified のとき output は統合スコア (NG if >= cand1_T)。raw のとき従来通り。
        cand1 = para.get('cand1')
        c1_enabled = (self.mode == 'monochro' and cand1 is not None)
        for k, v in (('cand1_enabled', 'true' if c1_enabled else 'false'),
                     ('cand1_T', str(cand1['T']) if c1_enabled else ''),
                     ('score_type', 'unified' if c1_enabled else 'raw')):
            m = onnx_model.metadata_props.add(); m.key = k; m.value = v
        onnx.save(onnx_model, onnx_path)

        print(f"Exported ONNX: {onnx_path}")
        print(f"  st_para={para['st_para']}, ae_para={para['ae_para']}")
        print(f"  channel_weights: {'あり' if para['channel_weights'] is not None else 'なし'}")
        print(f"  threshold: {para['threshold']}")
        print(f"  edge_mask_w: {edge_mask_w}")

        return onnx_path


def export_model(cfg: DictConfig) -> str:
    """学習済みモデルをONNX形式でエクスポートする（deployステージの公開API）。

    Args:
        cfg: build_sub_cfg() が返すflatなsub_cfg
            (model_dir/target_color/mode/image_size_height/image_size_width等を含む)

    Returns:
        エクスポートしたONNXファイルのパス
    """
    return ModelExporter(cfg).export_onnx()


if __name__ == '__main__':
    cfg: DictConfig = OmegaConf.load('./conf/config.yaml')
    exporter: ModelExporter = ModelExporter(cfg)
    exporter.export_onnx()
```

- [ ] **Step 2: `training/deploy/__init__.py`を更新する**

`training/deploy/__init__.py`を以下に全文置換する:

```python
"""deployステージの公開API。

deployパッケージ外からは `deploy.upload_model` / `deploy.export_model` のみを
使用すること。`deploy.ftp_upload` / `deploy.model_export` 内の関数を外部から
直接importしてはならない（境界はtests/ci_gates/test_deploy_boundary.pyで検証）。
"""
from deploy.ftp_upload import upload_model
from deploy.model_export import export_model

__all__ = ["upload_model", "export_model"]
```

- [ ] **Step 3: `training/pipline.py`を更新する**

`training/pipline.py:27`の以下の行を削除する:

```python
from model_exporter import ModelExporter
```

`training/pipline.py:623-624`の以下のコード:

```python
            exporter = ModelExporter(sub_cfg)
            exporter.export_onnx()
```

を以下に置換する:

```python
            deploy.export_model(sub_cfg)
```

- [ ] **Step 4: ルートの`training/model_exporter.py`を削除する**

```bash
git rm training/model_exporter.py
```

- [ ] **Step 5: characterization testを新しい場所へ移動する**

`training/tests/test_model_exporter_onnx_parity.py`を`training/tests/deploy/test_model_export_onnx_parity.py`へ移動する:

```bash
git mv training/tests/test_model_exporter_onnx_parity.py training/tests/deploy/test_model_export_onnx_parity.py
```

移動先ファイルの先頭import部分、以下の行:

```python
from model_exporter import ModelExporter
```

を以下に置換する(このファイルの他の箇所は一切変更しない):

```python
from deploy.model_export import ModelExporter
```

- [ ] **Step 6: 移動したテストを実行し、挙動が変わっていないことを確認する**

Run: `cd training && python -m pytest tests/deploy/test_model_export_onnx_parity.py -v`
Expected: 2件ともPASS(Task1と同じ2テストが、import先が`deploy.model_export`に変わっただけで変わらず成功する。これが移動による挙動保存の証拠)

- [ ] **Step 7: CI gateを拡張する**

`training/tests/ci_gates/test_deploy_boundary.py`を以下に全文置換する:

```python
"""deployステージの境界を守るCI gate。

utils.ftp_common.upload_file_to_ftp（ONNXモデルアップロードの低レベル関数）と
deploy.model_export（ONNXエクスポートの低レベルモジュール）を直接importできるのは
deployパッケージ内のみであることを保証する。他のモジュールは
deploy.upload_model / deploy.export_model の公開APIのみを使用すること。

走査対象は training/ 配下のみに限定する（app_ver2はEfficientADと異なり、
同一リポジトリに backend/ 等の無関係なPythonコードを含むため。設計書ADR-app4）。
"""
import ast
from pathlib import Path

TRAINING_ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIR_NAMES = {"tests", "deploy", "__pycache__"}
INTERNAL_MODULES = {"deploy.model_export"}


def _imported_names(file_path):
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.name)
    return names


def _imported_module_names(file_path):
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
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
    deploy パッケージ内のみであること（境界の逆行を防ぐラチェット）。"""
    offenders = []
    for py_file in TRAINING_ROOT.rglob("*.py"):
        rel_parts = py_file.relative_to(TRAINING_ROOT).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if "upload_file_to_ftp" in _imported_names(py_file):
            offenders.append(str(py_file.relative_to(TRAINING_ROOT)))
    assert offenders == [], f"deploy外からのupload_file_to_ftp直接importを検出: {offenders}"


def test_pipline_does_not_import_model_export_internals_directly():
    """pipline.py は deploy.model_export を直接importしてはいけない。
    ONNXエクスポートは deploy モジュールの公開APIを経由すること。"""
    pipline_path = TRAINING_ROOT / "pipline.py"
    assert _imported_module_names(pipline_path).isdisjoint(INTERNAL_MODULES)


def test_only_deploy_module_imports_model_export_internals():
    """deploy.model_export を直接importしているのは
    deploy パッケージ内のみであること（境界の逆行を防ぐラチェット）。"""
    offenders = []
    for py_file in TRAINING_ROOT.rglob("*.py"):
        rel_parts = py_file.relative_to(TRAINING_ROOT).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if _imported_module_names(py_file) & INTERNAL_MODULES:
            offenders.append(str(py_file.relative_to(TRAINING_ROOT)))
    assert offenders == [], f"deploy外からのdeploy.model_export直接importを検出: {offenders}"
```

- [ ] **Step 8: CI gateテストを実行する**

Run: `cd training && python -m pytest tests/ci_gates/test_deploy_boundary.py -v`
Expected: 4件ともPASS(既存2件 + 今回追加2件)

`training/tests/deploy/test_model_export_onnx_parity.py`が`training/tests/deploy/`配下に置かれているため`EXCLUDED_DIR_NAMES`(`{"tests", "deploy", "__pycache__"}`)の除外対象になり、このテストファイル自身が`deploy.model_export`をimportしていてもCI gateには抵触しない。

- [ ] **Step 9: プロジェクト全体のテストを実行する**

Run: `cd training && python -m pytest tests/ -v`
Expected: 全件PASS(32件: Seam3完了時点で28件 + Task1で追加した2件のcharacterization test = 30件 + Task2 Step7で追加した2件のCI gateテスト = 32件)

**重要（無関係WIPの分離）**: `git add`前に`git diff training/pipline.py`で、本Task2の変更（import削除・呼び出し置換の2箇所）のみが含まれ、本Seamと無関係な既存WIP（`_spawn_with_gpu_env`のspawn-context修正）が混入していないことを確認すること。Seam1/2/3のTask3で行った「一時的にWIPを元に戻す→コミット→復元する」手順を同様に踏むこと。

- [ ] **Step 10: コミット**

```bash
git add training/deploy/model_export.py training/deploy/__init__.py training/pipline.py \
        training/tests/ci_gates/test_deploy_boundary.py \
        training/tests/deploy/test_model_export_onnx_parity.py
git rm training/model_exporter.py training/tests/test_model_exporter_onnx_parity.py
git commit -m "$(cat <<'EOF'
refactor(training-deploy): model_exporter.pyをdeploy/model_export.pyへ移動しexport_model公開APIを追加

training/model_exporter.pyのModelExporterクラスをtraining/deploy/model_export.pyへ
移動し、deploy.export_model(cfg)公開APIを新設。training/pipline.pyはこの
公開API経由でのみONNXエクスポートを行う。ロジックは1文字も変更なし
（tests/deploy/test_model_export_onnx_parity.pyで移動前後の一致を検証）。
print("Exported ONNX: ...")の文言も変更なし（ver2フロントエンドのステージ検出対象）。
CI gate(test_deploy_boundary.py)にdeploy.model_export境界の逆行防止テストを追加。
EOF
)"
```

`training/model_exporter.py`・`training/tests/test_model_exporter_onnx_parity.py`(git mvにより実体はもう存在しないが、明示のためgit rmも記載)の削除は上記コミットに含まれる。

---

## 完了条件（このSeamのDone）

- `deploy.export_model(cfg)`が公開APIとして存在し、`training/pipline.py`はこれ経由でのみONNXエクスポートを行う
- `training/model_exporter.py`が削除され、`training/deploy/model_export.py`に移動済み
- characterization test（ONNX出力とeager実行の一致）が移動前(Task1)・移動後(Task2)の両方でPASSし、挙動保存を実証している
- `print("Exported ONNX: ...")`の文言が1文字も変更されていない
- CI gate（`training/tests/ci_gates/test_deploy_boundary.py`）が4件に拡張され、`deploy.model_export`の境界逆行を検出できる
- `cd training && python -m pytest tests/ -v` が全件PASS（32件）
- `training/pipline.py`の無関係な既存WIP（spawn-context修正）が本Seamのコミットに混入していない
- 設計書（`docs/superpowers/specs/2026-07-21-training-modular-monolith-migration-design.md`）§8のSeam4が完了としてマークできる状態になっている
