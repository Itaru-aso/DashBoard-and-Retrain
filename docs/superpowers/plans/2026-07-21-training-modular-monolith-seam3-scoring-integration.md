# training/ モジュラモノリス移行 Seam3: evaluation⇄deploy スコアリング統合 (ADR-6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `training/model.py` の `EfficientADFullModel.forward()` が持つ anomaly score 計算ロジック（teacher-student diff → quantile正規化 → channel_weights → edge_mask → pad+interpolate または cand1統合 → max）を `training/utils/scoring_transform.py` の単一の共有関数として抽出し、`training/model.py` と `training/evaluation/scoring.py` の両方がこの1つの実装を呼ぶようにする。これにより evaluation の指標（AUC/F1/miss_rate/false_alarm_rate）が実際にデプロイされるモデルの判定と一致するようにする。

**Architecture:** strangler-fig方式。今回のSeamは「構造移動・挙動不変」ではなく**意図的な挙動変更**である（evaluationの計算結果が変わる。ユーザー承認済み・設計書§5）。ゲートは「新旧比較」ではなく「`model.py`のtorch eager実行 と 共有関数経由の新実装が一致すること」。単一実装への統合により、この一致は構造的に保証されるが、ワイヤリング（パラメータの渡し忘れ・形状不一致）を検出する回帰テストとして必要。先行実装 `D:\0032011\GitLab\shisui\EfficientAD` の同名Seam（`docs/superpowers/plans/2026-07-14-modular-monolith-seam3-scoring-integration.md`）を参照。

**Tech Stack:** Python, PyTorch（eager実行のみ、ONNX/onnxruntimeとの一致は本Seamのスコープ外）, pytest。

## Global Constraints

- パリティテストの比較対象は `training/model.py` の `EfficientADFullModel` の **torch eagerモード実行**。ONNXエクスポート後の onnxruntime 実行との一致は将来の任意タスクとし、本計画では扱わない
- 共有関数の配置先は `training/utils/scoring_transform.py`（新規ファイル）。既存の `training/utils/common.py`・`training/utils/edge_mask.py` と同じ「複数ステージ共有の低レベルヘルパー」の位置づけ
- 本Seamはevaluationの計算結果を変更する。Seam1/2で使った「characterization test: 旧==新」パターンは使わない。既存の `training/tests/evaluation/test_evaluator.py`（5件）は `evaluation.scoring.score_images` 等を丸ごとmockしているため本計画の変更で壊れない — 各タスクで実行して確認する
- `training/tests/test_pipline_skip_flags.py`は本Seamでは**変更不要**（`training/pipline.py`を一切変更しないため）
- `evaluate()`の結果がdeployを止めるゲートになっていない現状の挙動は維持する（設計書ADR-2継承。本Seamでも変更しない）
- テストは`training/`をcwdとして`python -m pytest`で実行する（`cd training && python -m pytest tests/... -v`）
- CI gateの走査対象は`training/`配下に限定する（設計書ADR-app4）
- 日本語コミットメッセージ、Conventional Commits形式（`<type>(<scope>): <subject>`）
- 対象ファイルの現状（2026-07-21時点、Seam1/2完了後の状態、app_ver2の実ソースで確認済み）:
  - `training/model.py`: `EfficientADFullModel.forward()` は**94-146行目**。`self.teacher_mean`/`self.teacher_std`/`self.q_st_start`等は`__init__`で`register_buffer`済みで、いずれも`(1, -1, 1, 1)`または`(1, 1, H, W)`形状にreshapeされた状態で保持されている
  - `training/evaluation/scoring.py`: `load_model()`（**138-207行目**）、`_predict_st_only()`（**210-231行目**）、`score_images()`（**234-302行目**）、`evaluate_model()`（**305-367行目**、**呼び出し元ゼロのdead code、本計画では変更しない**）
  - `training/evaluation/predict.py`: `predict()`・`compute_image_score()`・`compute_miss_and_false_alarm_rates()`。すべて`training/evaluation/scoring.py`経由でのみ使われており（16行目のimport）、本計画完了後は全関数が呼び出し元ゼロになる
  - `training/evaluation/evaluator.py`: `Evaluator.evaluate()`は`score_images(model_dict, test_good, good_files)`をst_para/ae_para引数無しで呼んでいる。**本計画ではこのファイルへの変更は不要**（修正は`score_images()`のデフォルト値の意味を変えることで行う。詳細はTask2）
  - `training/utils/edge_mask.py`: `apply_edge_mask_zero()`。共有関数からそのまま利用する（変更不要）
  - **確認済みの実害（設計書§5の前提が真であることを実測確認）**: `training/evaluation/scoring.py`の`score_images()`（`ae_para==0.0`時の`_predict_st_only`経路）は、quantile正規化後の縮小マップ（例: 56x120）に対して直接`compute_image_score`（`.max()`のみ、pad/interpolateなし）を呼んでいる。一方`training/model.py`の`forward()`はpad+bilinear補間で元画像サイズ（例: 256x512）に拡大した後に`.max()`を取る。bilinear補間はピーク値を変化させるため、これらは数値的に一致しない。加えて`training/evaluation/scoring.py`にはcand1（z-score OR統合）ロジックが一切存在しない。両者は`training/model.py`と`training/evaluation/scoring.py`（旧`utils/evaluation_pipeline.py`・`utils/evaluation.py`のコピー、Seam2で移動）で完全に同一コードであることをEfficientAD側と比較確認済み
  - ベースラインテスト: `cd training && python -m pytest tests/ -v` で **16 passed**（2026-07-21時点、Seam1/2完了後。実測済み）

---

## Task 1: `training/utils/scoring_transform.py` の抽出と `training/model.py` の切替

**Files:**
- Create: `training/tests/conftest.py`（テスト全体で共有するsynthetic modelビルダーfixture）
- Create: `training/utils/scoring_transform.py`
- Create: `training/tests/test_scoring_transform.py`
- Create: `training/tests/model/test_efficientad_full_model_regression.py`
- Modify: `training/model.py:1-9`（import追加）, `training/model.py:94-146`（forward本体を共有関数呼び出しに置換）

**Interfaces:**
- Produces: `utils.scoring_transform.compute_anomaly_score(x, teacher, student, autoencoder, teacher_mean, teacher_std, st_para, ae_para, q_st_start=None, q_st_end=None, q_ae_start=None, q_ae_end=None, channel_weights=None, edge_mask_w=0, cand1=None, height=None, width=None) -> Tensor`
  - `x`: 正規化済み画像テンソル `(B, 3, H, W)`
  - `teacher_mean`/`teacher_std`: 既に `(1, C, 1, 1)` にreshape済みのテンソル
  - `q_st_start`/`q_st_end`/`q_ae_start`/`q_ae_end`: 0-dimまたはブロードキャスト可能なテンソル、Noneなら正規化スキップ
  - `cand1`: `None` または `{'mu': Tensor(1,1,H',W'), 'sigma': Tensor(1,1,H',W'), 'A': float, 'Z': float}`。`None`でない場合は `height`/`width` を無視し、元グリッド上で統合スコアを返す
  - `cand1=None` の場合は `height`/`width` が必須（pad+interpolateに使用）
  - 戻り値: `Tensor` shape `(B, 1)`、画像ごとの anomaly score
- Produces (fixture): `training/tests/conftest.py` の pytest fixture `synthetic_scoring_components` — 呼び出すと `_build(image_h=256, image_w=512, seed=0)` 相当のbuilder関数を返す。builder呼び出しの戻り値は dict:
  `{'teacher', 'student', 'autoencoder', 'teacher_mean'(shape (1,C,1,1)), 'teacher_std'(shape (1,C,1,1)), 'image_np'(uint8 HWC), 'image_norm'(shape (1,3,H,W)), 'q_st_start', 'q_st_end', 'q_ae_start', 'q_ae_end', 'map_h', 'map_w', 'height', 'width'}`
- Consumes: `utils.common.get_pdn_small`, `utils.common.get_autoencoder`, `utils.edge_mask.apply_edge_mask_zero`（すべて既存、変更なし）

- [ ] **Step 1: 共有fixtureを作成する**

`training/tests/conftest.py` を新規作成する:

```python
"""テスト全体で共有するfixture。"""
import numpy as np
import pytest
import torch

from utils.common import get_autoencoder, get_pdn_small

OUT_CHANNELS = 384
IMAGENET_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
IMAGENET_STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


@pytest.fixture
def synthetic_scoring_components():
    """teacher/student/autoencoder(乱数初期化・seed固定)と、
    quantile境界・合成画像を含む辞書を返すbuilder関数を提供する。

    Seam3のスコアリング計算パリティテスト(model.py と
    utils.scoring_transform / evaluation.scoring の一致検証)で、
    実際の学習済み重み無しに再現可能な入力を用意するために使う。
    """
    def _build(image_h=256, image_w=512, seed=0):
        torch.manual_seed(seed)
        np.random.seed(seed)

        teacher = get_pdn_small(OUT_CHANNELS)
        student = get_pdn_small(2 * OUT_CHANNELS)
        autoencoder = get_autoencoder(
            OUT_CHANNELS, image_size_height=image_h, image_size_width=image_w)
        teacher.eval()
        student.eval()
        autoencoder.eval()

        img_np = np.random.randint(0, 256, (image_h, image_w, 3), dtype=np.uint8)

        teacher_mean = torch.zeros(1, OUT_CHANNELS, 1, 1)
        teacher_std = torch.ones(1, OUT_CHANNELS, 1, 1)

        with torch.no_grad():
            image_norm = torch.from_numpy(
                img_np.transpose(2, 0, 1)[None]).float() / 255.0
            image_norm = (image_norm - IMAGENET_MEAN) / IMAGENET_STD

            teacher_out = teacher(image_norm)
            teacher_out_n = (teacher_out - teacher_mean) / teacher_std
            student_out = student(image_norm)
            diff_st = (teacher_out_n - student_out[:, :OUT_CHANNELS]) ** 2
            map_st = torch.mean(diff_st, dim=1, keepdim=True)

            autoencoder_out = autoencoder(image_norm)
            map_ae = torch.mean(
                (autoencoder_out - student_out[:, OUT_CHANNELS:]) ** 2,
                dim=1, keepdim=True)

        return {
            'teacher': teacher,
            'student': student,
            'autoencoder': autoencoder,
            'teacher_mean': teacher_mean,
            'teacher_std': teacher_std,
            'image_np': img_np,
            'image_norm': image_norm,
            'q_st_start': map_st.min(),
            'q_st_end': map_st.max(),
            'q_ae_start': map_ae.min(),
            'q_ae_end': map_ae.max(),
            'map_h': map_st.shape[2],
            'map_w': map_st.shape[3],
            'height': image_h,
            'width': image_w,
        }

    return _build
```

- [ ] **Step 2: 失敗するテストを書く(共有関数がまだ存在しない)**

`training/tests/test_scoring_transform.py` を新規作成する:

```python
"""utils.scoring_transform.compute_anomaly_score の正当性を検証する。

model.py の EfficientADFullModel.forward() (Seam3抽出前) を字句通り
複製した参照実装 (_reference_compute) との数値一致を保証する。

実行: cd training && python -m pytest tests/test_scoring_transform.py -v
"""
import torch

from utils.edge_mask import apply_edge_mask_zero


def _reference_compute(x, teacher, student, autoencoder, teacher_mean, teacher_std,
                        st_para, ae_para, q_st_start, q_st_end, q_ae_start, q_ae_end,
                        channel_weights, edge_mask_w, cand1, height, width):
    """Seam3抽出前の model.py EfficientADFullModel.forward() 本体の字句通りの複製。

    teacher_mean/teacher_std は呼び出し側で (1, C, 1, 1) 形状に整えて渡すこと
    (model.py の register_buffer 済みバッファと同じ契約)。
    """
    teacher_output = teacher(x)
    teacher_output = (teacher_output - teacher_mean) / teacher_std
    student_output = student(x)
    out_channels = teacher_output.shape[1]

    diff_st = (teacher_output - student_output[:, :out_channels]) ** 2
    if channel_weights is not None:
        map_st = torch.sum(diff_st * channel_weights, dim=1, keepdim=True)
    else:
        map_st = torch.mean(diff_st, dim=1, keepdim=True)

    if ae_para > 0:
        autoencoder_output = autoencoder(x)
        map_ae = torch.mean(
            (autoencoder_output - student_output[:, out_channels:]) ** 2,
            dim=1, keepdim=True)
    else:
        map_ae = torch.zeros_like(map_st)

    if q_st_start is not None:
        map_st = 0.1 * (map_st - q_st_start) / (q_st_end - q_st_start)
    if q_ae_start is not None and ae_para > 0:
        map_ae = 0.1 * (map_ae - q_ae_start) / (q_ae_end - q_ae_start)

    map_combined = st_para * map_st + ae_para * map_ae

    edge_w = int(edge_mask_w)
    if edge_w > 0:
        map_combined = apply_edge_mask_zero(map_combined, edge_w)

    if cand1 is not None:
        raw = torch.max(torch.max(map_combined, dim=3)[0], dim=2)[0]
        zmap = (map_combined - cand1['mu']) / (cand1['sigma'] + 1e-6)
        zval = torch.max(torch.max(zmap, dim=3)[0], dim=2)[0]
        return torch.maximum(raw / cand1['A'], zval / cand1['Z'])

    map_combined = torch.nn.functional.pad(map_combined, (4, 4, 4, 4))
    map_combined = torch.nn.functional.interpolate(
        map_combined, (height, width), mode='bilinear')
    return torch.max(torch.max(map_combined, dim=3)[0], dim=2)[0]


def test_compute_anomaly_score_matches_reference_config_a(synthetic_scoring_components):
    """config A: ae_para=0, cand1無し (color相当・現状本番構成)。"""
    from utils.scoring_transform import compute_anomaly_score

    c = synthetic_scoring_components()
    kwargs = dict(
        x=c['image_norm'], teacher=c['teacher'], student=c['student'],
        autoencoder=c['autoencoder'], teacher_mean=c['teacher_mean'],
        teacher_std=c['teacher_std'], st_para=1.0, ae_para=0.0,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
        channel_weights=None, edge_mask_w=0, cand1=None,
        height=c['height'], width=c['width'],
    )
    expected = _reference_compute(**kwargs)
    actual = compute_anomaly_score(**kwargs)
    assert torch.allclose(actual, expected)


def test_compute_anomaly_score_matches_reference_config_b(synthetic_scoring_components):
    """config B: ae_para=0.7 (AE有効。config.yamlのmap_aeが将来0以外になった場合の回帰防止)。"""
    from utils.scoring_transform import compute_anomaly_score

    c = synthetic_scoring_components()
    kwargs = dict(
        x=c['image_norm'], teacher=c['teacher'], student=c['student'],
        autoencoder=c['autoencoder'], teacher_mean=c['teacher_mean'],
        teacher_std=c['teacher_std'], st_para=1.0, ae_para=0.7,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
        channel_weights=None, edge_mask_w=0, cand1=None,
        height=c['height'], width=c['width'],
    )
    expected = _reference_compute(**kwargs)
    actual = compute_anomaly_score(**kwargs)
    assert torch.allclose(actual, expected)


def test_compute_anomaly_score_matches_reference_config_c(synthetic_scoring_components):
    """config C: monochro相当、cand1有効 (現状本番の全monochroモデルの構成)。"""
    from utils.scoring_transform import compute_anomaly_score

    c = synthetic_scoring_components()
    torch.manual_seed(1)
    mu = torch.rand(1, 1, c['map_h'], c['map_w']) * 0.05
    sigma = torch.rand(1, 1, c['map_h'], c['map_w']) * 0.04 + 0.01
    cand1 = {'mu': mu, 'sigma': sigma, 'A': 1.0, 'Z': 3.0}

    kwargs = dict(
        x=c['image_norm'], teacher=c['teacher'], student=c['student'],
        autoencoder=c['autoencoder'], teacher_mean=c['teacher_mean'],
        teacher_std=c['teacher_std'], st_para=1.0, ae_para=0.0,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
        channel_weights=None, edge_mask_w=0, cand1=cand1,
        height=c['height'], width=c['width'],
    )
    expected = _reference_compute(**kwargs)
    actual = compute_anomaly_score(**kwargs)
    assert torch.allclose(actual, expected)
```

- [ ] **Step 3: テストを実行し失敗を確認する**

Run: `cd training && python -m pytest tests/test_scoring_transform.py -v`
Expected: 3件とも `ModuleNotFoundError: No module named 'utils.scoring_transform'` でFAIL

- [ ] **Step 4: `training/utils/scoring_transform.py` を実装する**

```python
"""evaluation / deploy(model.py) 共有のスコア計算ロジック。

teacher-student diff -> quantile正規化 -> channel_weights -> edge_mask
-> (cand1 分岐 または pad+interpolate) -> max、という anomaly score
計算をここに集約する。model.py の EfficientADFullModel.forward() と
evaluation/scoring.py の score_images() の両方がこの関数を呼ぶことで、
evaluationとdeployのスコアリング実装重複(ADR-6)を解消する。
"""
import torch
import torch.nn.functional as F

from utils.edge_mask import apply_edge_mask_zero


def compute_anomaly_score(
    x,
    teacher,
    student,
    autoencoder,
    teacher_mean,
    teacher_std,
    st_para,
    ae_para,
    q_st_start=None,
    q_st_end=None,
    q_ae_start=None,
    q_ae_end=None,
    channel_weights=None,
    edge_mask_w=0,
    cand1=None,
    height=None,
    width=None,
):
    """正規化済み画像テンソル x から anomaly score を計算する。

    Args:
        x: 正規化済み画像テンソル (B, 3, H, W)。
        teacher_mean/teacher_std: (1, C, 1, 1) にreshape済みのテンソル。
        cand1: None、または {'mu', 'sigma', 'A', 'Z'} を含む dict。
            Noneでない場合、統合スコア max(raw/A, z/Z) を
            元のグリッド(pad/interpolate前)上で計算して返す。
        height/width: cand1=None の場合必須 (pad+interpolateの出力サイズ)。

    Returns:
        Tensor shape (B, 1): 画像ごとの anomaly score。
    """
    teacher_output = teacher(x)
    teacher_output = (teacher_output - teacher_mean) / teacher_std
    student_output = student(x)
    out_channels = teacher_output.shape[1]

    diff_st = (teacher_output - student_output[:, :out_channels]) ** 2
    if channel_weights is not None:
        map_st = torch.sum(diff_st * channel_weights, dim=1, keepdim=True)
    else:
        map_st = torch.mean(diff_st, dim=1, keepdim=True)

    if ae_para > 0:
        autoencoder_output = autoencoder(x)
        map_ae = torch.mean(
            (autoencoder_output - student_output[:, out_channels:]) ** 2,
            dim=1, keepdim=True)
    else:
        map_ae = torch.zeros_like(map_st)

    if q_st_start is not None:
        map_st = 0.1 * (map_st - q_st_start) / (q_st_end - q_st_start)
    if q_ae_start is not None and ae_para > 0:
        map_ae = 0.1 * (map_ae - q_ae_start) / (q_ae_end - q_ae_start)

    map_combined = st_para * map_st + ae_para * map_ae

    edge_w = int(edge_mask_w)
    if edge_w > 0:
        map_combined = apply_edge_mask_zero(map_combined, edge_w)

    if cand1 is not None:
        raw = torch.max(torch.max(map_combined, dim=3)[0], dim=2)[0]
        zmap = (map_combined - cand1['mu']) / (cand1['sigma'] + 1e-6)
        zval = torch.max(torch.max(zmap, dim=3)[0], dim=2)[0]
        return torch.maximum(raw / cand1['A'], zval / cand1['Z'])

    map_combined = F.pad(map_combined, (4, 4, 4, 4))
    map_combined = F.interpolate(map_combined, (height, width), mode='bilinear')
    return torch.max(torch.max(map_combined, dim=3)[0], dim=2)[0]
```

- [ ] **Step 5: テストを実行し成功を確認する**

Run: `cd training && python -m pytest tests/test_scoring_transform.py -v`
Expected: 3件とも PASS

- [ ] **Step 6: コミット**

```bash
git add training/tests/conftest.py training/utils/scoring_transform.py training/tests/test_scoring_transform.py
git commit -m "$(cat <<'EOF'
feat(training-scoring): evaluation/deploy共有のanomaly score計算をutils/scoring_transform.pyに抽出

training/model.pyのEfficientADFullModel.forward()が持つteacher-student
diff→quantile正規化→channel_weights→edge_mask→(cand1統合またはpad+
interpolate)→maxの計算ロジックを、utils/scoring_transform.compute_anomaly_score
として抽出。model.pyのforward()実装(Seam3抽出前)を字句通り複製した
参照実装との数値一致を検証する。
EOF
)"
```

- [ ] **Step 7: `training/model.py` の `forward()` を共有関数呼び出しに置換する**

`training/model.py:1-9` のimport部分に以下を追加する(既存のimportの後に追加):

変更前(1-9行目):
```python
import torch
import json
import os
import numpy as np
import torch.nn as nn
from torchvision import transforms

from utils.common import get_autoencoder, get_pdn_small
from utils.edge_mask import apply_edge_mask_zero
```

変更後:
```python
import torch
import json
import os
import numpy as np
import torch.nn as nn
from torchvision import transforms

from utils.common import get_autoencoder, get_pdn_small
from utils.edge_mask import apply_edge_mask_zero
from utils.scoring_transform import compute_anomaly_score
```

`training/model.py:94-146` の `forward()` メソッド全体を以下に置換する:

変更前:
```python
    def forward(self, x):
        x = x / 255.0
        x = (x - self.mean) / self.std

        teacher_output = self.teacher(x)
        teacher_output = (teacher_output - self.teacher_mean) / self.teacher_std
        student_output = self.student(x)

        # map_st: Teacher-Student 差異
        diff_st = (teacher_output - student_output[:, :self.out_channels]) ** 2
        if self.channel_weights is not None:
            map_st = torch.sum(diff_st * self.channel_weights, dim=1, keepdim=True)
        else:
            map_st = torch.mean(diff_st, dim=1, keepdim=True)

        # map_ae: AE無効 (ae_para=0) のときは計算しない
        # AE出力(56x120) と Student出力(64x128) のサイズ不一致を回避
        if self.ae_para > 0:
            autoencoder_output = self.autoencoder(x)
            map_ae = torch.mean(
                (autoencoder_output - student_output[:, self.out_channels:]) ** 2,
                dim=1, keepdim=True)
        else:
            map_ae = torch.zeros_like(map_st)

        # quantile 正規化
        if self.q_st_start is not None:
            map_st = 0.1 * (map_st - self.q_st_start) / (self.q_st_end - self.q_st_start)
        if self.q_ae_start is not None and self.ae_para > 0:
            map_ae = 0.1 * (map_ae - self.q_ae_start) / (self.q_ae_end - self.q_ae_start)

        map_combined = self.st_para * map_st + self.ae_para * map_ae

        # PDN padding artifact 抑制: anomaly map レベル (pad/interpolate 前) で両端 N 列を 0 化。
        # 学習側 (train_func_color.py) の slice_edge_excluded と対称適用。
        edge_w = int(self.edge_mask_w)
        if edge_w > 0:
            map_combined = apply_edge_mask_zero(map_combined, edge_w)

        # 候補1 (monochro 専用): 56x120 の map_combined で raw/z を算出し統合スコアを返す。
        # raw=max(map_combined), z=max((map_combined-μ)/σ), unified=max(raw/A, z/Z)。
        if self.cand1_enabled:
            raw = torch.max(torch.max(map_combined, dim=3)[0], dim=2)[0]          # (B,1)
            zmap = (map_combined - self.cand1_mu) / (self.cand1_sigma + 1e-6)
            zval = torch.max(torch.max(zmap, dim=3)[0], dim=2)[0]                 # (B,1)
            return torch.maximum(raw / self.cand1_A, zval / self.cand1_Z)        # (B,1)

        map_combined = torch.nn.functional.pad(map_combined, (4, 4, 4, 4))
        map_combined = torch.nn.functional.interpolate(
            map_combined, (self.height, self.width), mode='bilinear')

        output = torch.max(torch.max(map_combined, dim=3)[0], dim=2)[0]
        return output
```

変更後:
```python
    def forward(self, x):
        x = x / 255.0
        x = (x - self.mean) / self.std

        cand1 = None
        if self.cand1_enabled:
            cand1 = {
                'mu': self.cand1_mu,
                'sigma': self.cand1_sigma,
                'A': self.cand1_A,
                'Z': self.cand1_Z,
            }

        return compute_anomaly_score(
            x, self.teacher, self.student, self.autoencoder,
            self.teacher_mean, self.teacher_std,
            self.st_para, self.ae_para,
            q_st_start=self.q_st_start, q_st_end=self.q_st_end,
            q_ae_start=self.q_ae_start, q_ae_end=self.q_ae_end,
            channel_weights=self.channel_weights,
            edge_mask_w=int(self.edge_mask_w),
            cand1=cand1,
            height=self.height, width=self.width,
        )
```

- [ ] **Step 8: 失敗を確認するための回帰テストを先に書く**

`training/tests/model/test_efficientad_full_model_regression.py` を新規作成する(`training/tests/model/` は新規ディレクトリ、`__init__.py`は作成しない):

```python
"""EfficientADFullModel.forward() の Seam3抽出前後の一致を保証する回帰テスト。

_reference_forward は Seam3抽出直前の model.py forward() 本体を
字句通り複製した参照実装。抽出後もこの出力と一致することを保証する。

実行: cd training && python -m pytest tests/model/test_efficientad_full_model_regression.py -v
"""
import torch

from model import EfficientADFullModel


def _reference_forward(model, x):
    x = x / 255.0
    x = (x - model.mean) / model.std

    teacher_output = model.teacher(x)
    teacher_output = (teacher_output - model.teacher_mean) / model.teacher_std
    student_output = model.student(x)

    diff_st = (teacher_output - student_output[:, :model.out_channels]) ** 2
    if model.channel_weights is not None:
        map_st = torch.sum(diff_st * model.channel_weights, dim=1, keepdim=True)
    else:
        map_st = torch.mean(diff_st, dim=1, keepdim=True)

    if model.ae_para > 0:
        autoencoder_output = model.autoencoder(x)
        map_ae = torch.mean(
            (autoencoder_output - student_output[:, model.out_channels:]) ** 2,
            dim=1, keepdim=True)
    else:
        map_ae = torch.zeros_like(map_st)

    if model.q_st_start is not None:
        map_st = 0.1 * (map_st - model.q_st_start) / (model.q_st_end - model.q_st_start)
    if model.q_ae_start is not None and model.ae_para > 0:
        map_ae = 0.1 * (map_ae - model.q_ae_start) / (model.q_ae_end - model.q_ae_start)

    map_combined = model.st_para * map_st + model.ae_para * map_ae

    edge_w = int(model.edge_mask_w)
    if edge_w > 0:
        from utils.edge_mask import apply_edge_mask_zero
        map_combined = apply_edge_mask_zero(map_combined, edge_w)

    if model.cand1_enabled:
        raw = torch.max(torch.max(map_combined, dim=3)[0], dim=2)[0]
        zmap = (map_combined - model.cand1_mu) / (model.cand1_sigma + 1e-6)
        zval = torch.max(torch.max(zmap, dim=3)[0], dim=2)[0]
        return torch.maximum(raw / model.cand1_A, zval / model.cand1_Z)

    map_combined = torch.nn.functional.pad(map_combined, (4, 4, 4, 4))
    map_combined = torch.nn.functional.interpolate(
        map_combined, (model.height, model.width), mode='bilinear')
    return torch.max(torch.max(map_combined, dim=3)[0], dim=2)[0]


def _build_model(c, mode='color', cand1=None):
    return EfficientADFullModel(
        mode, c['height'], c['width'], c['teacher'], c['student'], c['autoencoder'],
        c['teacher_mean'].view(-1), c['teacher_std'].view(-1),
        st_para=1.0, ae_para=0.0 if cand1 is not None else 0.7,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
        channel_weights=None, threshold=None, edge_mask_w=0, cand1=cand1,
    ).eval()


def test_forward_matches_reference_no_cand1_branch(synthetic_scoring_components):
    """pad+interpolate分岐(cand1無し)。AE分岐(ae_para>0)も併せて被覆する。

    Task1のパリティテストのconfig A/B(ae_para=0 / ae_para=0.7)とは別軸の
    検証観点(model.py自身のforward委譲が正しいか)のためのテストであり、
    名称の対応関係は意図的に持たせていない。
    """
    c = synthetic_scoring_components()
    image_raw = torch.from_numpy(c['image_np'].transpose(2, 0, 1)[None]).float()
    model = _build_model(c, mode='color', cand1=None)

    with torch.no_grad():
        actual = model(image_raw)
        expected = _reference_forward(model, image_raw)

    assert torch.allclose(actual, expected)


def test_forward_matches_reference_cand1_branch(synthetic_scoring_components):
    """cand1統合スコア分岐(monochro相当)。"""
    c = synthetic_scoring_components()
    image_raw = torch.from_numpy(c['image_np'].transpose(2, 0, 1)[None]).float()
    torch.manual_seed(1)
    mu = torch.rand(c['map_h'], c['map_w']).numpy() * 0.05
    sigma = torch.rand(c['map_h'], c['map_w']).numpy() * 0.04 + 0.01
    cand1 = {'mu': mu, 'sigma': sigma, 'A': 1.0, 'Z': 3.0, 'T': 1.0}
    model = _build_model(c, mode='monochro', cand1=cand1)

    with torch.no_grad():
        actual = model(image_raw)
        expected = _reference_forward(model, image_raw)

    assert torch.allclose(actual, expected)
```

- [ ] **Step 9: テストを実行し成功を確認する**

Run: `cd training && python -m pytest tests/model/test_efficientad_full_model_regression.py -v`
Expected: 2件ともPASS(`EfficientADFullModel.forward()` が `compute_anomaly_score` に正しく委譲していることの確認)

- [ ] **Step 10: 全テストを実行し、コミット**

Run: `cd training && python -m pytest tests/ -v`
Expected: 全件PASS(Step6までの3件 + 新規2件 + 既存16件 = 21件)

**重要（無関係WIPの分離）**: 作業ツリーの`training/pipline.py`には本Seamと無関係な既存WIP（`_spawn_with_gpu_env`の`multiprocessing.get_context("spawn")`修正）が残っている想定。本Task1は`training/model.py`と新規ファイルのみを対象とするため`pipline.py`には触れないが、`git add`は対象ファイルを明示的に指定すること。

```bash
git add training/model.py training/tests/model/test_efficientad_full_model_regression.py
git commit -m "$(cat <<'EOF'
refactor(training-model): EfficientADFullModel.forwardをutils.scoring_transform.compute_anomaly_score呼び出しに置換

model.pyのforward()本体をutils.scoring_transform.compute_anomaly_score
への委譲に置き換え。Seam3抽出前のforward()を字句通り複製した参照実装
との数値一致をtest_efficientad_full_model_regression.pyで検証。
EOF
)"
```

---

## Task 2: `training/evaluation/scoring.py` を共有関数経由に切り替える

**Files:**
- Modify: `training/evaluation/scoring.py:1-19`（import部分）, `:138-207`（`load_model`）, `:210-231`（`_predict_st_only`、削除）, `:234-302`（`score_images`）
- Create: `training/tests/evaluation/test_scoring_parity.py`
- Create: `docs/superpowers/specs/2026-07-21-training-seam3-scoring-impact-report.md`

**Interfaces:**
- Consumes: `utils.scoring_transform.compute_anomaly_score`（Task1で作成）、`training/tests/conftest.py`の`synthetic_scoring_components`fixture（Task1で作成）
- Modifies public behavior: `evaluation.scoring.score_images(model_dict, image_dir, filenames, st_para=None, ae_para=None, device='cpu', edge_mask_w=None)` — `st_para`/`ae_para`のデフォルトが`None`になり、`None`の場合は`model_dict`(=`load_model()`の戻り値)に保存された、そのモデル自身のpara.json由来の値を使うようになる(従来は`st_para=1.0, ae_para=0.0`のハードコード値がデフォルトだった)
- Produces: `load_model()`の戻り値dictに新規キー `'height'`, `'width'`, `'st_para'`, `'ae_para'`, `'cand1'` を追加する

- [ ] **Step 1: パリティテストを先に書く(現状は不一致で失敗する)**

`training/tests/evaluation/test_scoring_parity.py` を新規作成する:

```python
"""evaluation.scoring.score_images() が model.py の EfficientADFullModel
(実際にデプロイされるスコア計算)と一致することを保証するパリティテスト。

Seam3(ADR-6)以前は evaluation.scoring.score_images() が
st_para=1.0/ae_para=0.0 を決め打ちし、pad+interpolateもcand1も
実装していなかったため、model.pyの実際のデプロイスコアと一致しなかった。

実行: cd training && python -m pytest tests/evaluation/test_scoring_parity.py -v
"""
import json

import numpy as np
import torch
from PIL import Image

from model import EfficientADFullModel


def _write_para_json(tmp_path, c, ae_para=0.0, cand1_enabled=False,
                      cand1_mu=None, cand1_sigma=None):
    para = {
        'teacher_mean_1d': c['teacher_mean'].view(-1).tolist(),
        'teacher_std_1d': c['teacher_std'].view(-1).tolist(),
        'q_st_start': c['q_st_start'].item(),
        'q_st_end': c['q_st_end'].item(),
        'q_ae_start': c['q_ae_start'].item(),
        'q_ae_end': c['q_ae_end'].item(),
        'st_para': 1.0,
        'ae_para': ae_para,
        'edge_mask_w': 0,
        'image_size_height': c['height'],
        'image_size_width': c['width'],
    }
    if cand1_enabled:
        para['cand1_enabled'] = True
        para['cand1_mu'] = cand1_mu.tolist()
        para['cand1_sigma'] = cand1_sigma.tolist()
        para['cand1_A'] = 1.0
        para['cand1_Z'] = 3.0
        para['cand1_T'] = 1.0

    model_dir = tmp_path / 'model'
    model_dir.mkdir()
    (model_dir / 'para.json').write_text(json.dumps(para), encoding='utf-8')
    torch.save(c['teacher'].state_dict(), model_dir / 'teacher_state_best.pth')
    torch.save(c['student'].state_dict(), model_dir / 'student_state_best.pth')
    torch.save(c['autoencoder'].state_dict(), model_dir / 'autoencoder_state_best.pth')
    return str(model_dir)


def _write_image(tmp_path, img_np, name='img.png'):
    image_dir = tmp_path / 'images'
    image_dir.mkdir(exist_ok=True)
    Image.fromarray(img_np).save(image_dir / name)
    return str(image_dir), name


def test_score_images_matches_model_forward_config_a(tmp_path, synthetic_scoring_components):
    """config A: ae_para=0, cand1無し (color相当・現状本番構成)。"""
    from evaluation.scoring import load_model, score_images

    c = synthetic_scoring_components()
    model_dir = _write_para_json(tmp_path, c, ae_para=0.0)
    image_dir, fname = _write_image(tmp_path, c['image_np'])

    model_dict = load_model(model_dir, image_size_height=c['height'],
                            image_size_width=c['width'])
    scores = score_images(model_dict, image_dir, [fname])

    full_model = EfficientADFullModel(
        'color', c['height'], c['width'], c['teacher'], c['student'], c['autoencoder'],
        c['teacher_mean'].view(-1), c['teacher_std'].view(-1),
        st_para=1.0, ae_para=0.0,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
    ).eval()
    image_raw = torch.from_numpy(c['image_np'].transpose(2, 0, 1)[None]).float()
    with torch.no_grad():
        expected = full_model(image_raw).item()

    assert abs(scores[fname] - expected) < 1e-4


def test_score_images_matches_model_forward_config_b_ae_enabled(
        tmp_path, synthetic_scoring_components):
    """config B: ae_para=0.7 (AE有効モデル)。旧実装はここで大きく不一致だった。"""
    from evaluation.scoring import load_model, score_images

    c = synthetic_scoring_components()
    model_dir = _write_para_json(tmp_path, c, ae_para=0.7)
    image_dir, fname = _write_image(tmp_path, c['image_np'])

    model_dict = load_model(model_dir, image_size_height=c['height'],
                            image_size_width=c['width'])
    scores = score_images(model_dict, image_dir, [fname])

    full_model = EfficientADFullModel(
        'color', c['height'], c['width'], c['teacher'], c['student'], c['autoencoder'],
        c['teacher_mean'].view(-1), c['teacher_std'].view(-1),
        st_para=1.0, ae_para=0.7,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
    ).eval()
    image_raw = torch.from_numpy(c['image_np'].transpose(2, 0, 1)[None]).float()
    with torch.no_grad():
        expected = full_model(image_raw).item()

    assert abs(scores[fname] - expected) < 1e-4


def test_score_images_matches_model_forward_config_c_cand1(
        tmp_path, synthetic_scoring_components):
    """config C: monochro相当、cand1有効 (現状本番の全monochroモデルの構成)。
    旧実装はcand1を一切実装していなかったため、ここは全く別スケールで不一致だった。"""
    from evaluation.scoring import load_model, score_images

    c = synthetic_scoring_components()
    torch.manual_seed(1)
    mu = (torch.rand(c['map_h'], c['map_w']) * 0.05).numpy().astype(np.float32)
    sigma = (torch.rand(c['map_h'], c['map_w']) * 0.04 + 0.01).numpy().astype(np.float32)

    model_dir = _write_para_json(tmp_path, c, ae_para=0.0, cand1_enabled=True,
                                  cand1_mu=mu, cand1_sigma=sigma)
    image_dir, fname = _write_image(tmp_path, c['image_np'])

    model_dict = load_model(model_dir, image_size_height=c['height'],
                            image_size_width=c['width'])
    scores = score_images(model_dict, image_dir, [fname])

    cand1 = {'mu': mu, 'sigma': sigma, 'A': 1.0, 'Z': 3.0, 'T': 1.0}
    full_model = EfficientADFullModel(
        'monochro', c['height'], c['width'], c['teacher'], c['student'], c['autoencoder'],
        c['teacher_mean'].view(-1), c['teacher_std'].view(-1),
        st_para=1.0, ae_para=0.0,
        q_st_start=c['q_st_start'], q_st_end=c['q_st_end'],
        q_ae_start=c['q_ae_start'], q_ae_end=c['q_ae_end'],
        cand1=cand1,
    ).eval()
    image_raw = torch.from_numpy(c['image_np'].transpose(2, 0, 1)[None]).float()
    with torch.no_grad():
        expected = full_model(image_raw).item()

    assert abs(scores[fname] - expected) < 1e-4
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd training && python -m pytest tests/evaluation/test_scoring_parity.py -v`
Expected: 3件ともFAIL(数値不一致。config_bは大きくズレ、config_cはcand1未実装のため全く別スケールでズレる)

- [ ] **Step 3: `training/evaluation/scoring.py` を修正する**

`training/evaluation/scoring.py:14-17` のimport部分を以下に置換する(現状):

```python
from utils.common import get_pdn_small, get_autoencoder
from utils.edge_mask import apply_edge_mask_zero
from evaluation.predict import predict as _predict, compute_image_score
from utils.split_manager import load_split
```

置換後:

```python
from utils.common import get_pdn_small, get_autoencoder
from utils.scoring_transform import compute_anomaly_score
from utils.split_manager import load_split
```

`training/evaluation/scoring.py:138-207` の `load_model()` を以下に置換する(`para`辞書のパース部分を拡張して`height`/`width`/`st_para`/`ae_para`/`cand1`を返すようにする):

```python
def load_model(model_dir, device='cpu', image_size_height=256, image_size_width=512):
    """model_dir からモデルとパラメータをロードする。

    para.json に ``image_size_height`` / ``image_size_width`` が含まれていれば
    それを優先。なければ引数 (既定 256×512) を採用。

    Returns:
        dict: teacher, student, autoencoder, teacher_mean, teacher_std,
              q_st_start, q_st_end, q_ae_start, q_ae_end, channel_weights,
              height, width, st_para, ae_para, cand1, edge_mask_w, para
    """
    para_path = os.path.join(model_dir, 'para.json')
    with open(para_path, 'r') as f:
        para = json.load(f)

    img_h = int(para.get('image_size_height', image_size_height))
    img_w = int(para.get('image_size_width', image_size_width))

    teacher = get_pdn_small(out_channels)
    student = get_pdn_small(2 * out_channels)
    autoencoder = get_autoencoder(out_channels,
                                  image_size_height=img_h,
                                  image_size_width=img_w)

    teacher.load_state_dict(torch.load(
        os.path.join(model_dir, 'teacher_state_best.pth'), map_location=device))
    student.load_state_dict(torch.load(
        os.path.join(model_dir, 'student_state_best.pth'), map_location=device))
    autoencoder.load_state_dict(torch.load(
        os.path.join(model_dir, 'autoencoder_state_best.pth'), map_location=device))

    teacher.eval()
    student.eval()
    autoencoder.eval()

    # teacher_mean_1d があれば使用（新形式）、なければ旧形式から reshape
    if 'teacher_mean_1d' in para:
        teacher_mean = torch.tensor(para['teacher_mean_1d']).reshape(1, -1, 1, 1).to(device)
        teacher_std = torch.tensor(para['teacher_std_1d']).reshape(1, -1, 1, 1).to(device)
    else:
        # 旧形式: [tensor.numpy()] でラップされ [1,1,C,1,1] の5次元になっている
        teacher_mean = torch.tensor(para['teacher_mean']).reshape(1, -1, 1, 1).to(device)
        teacher_std = torch.tensor(para['teacher_std']).reshape(1, -1, 1, 1).to(device)
    q_st_start = torch.tensor(para['q_st_start']).squeeze().to(device)
    q_st_end = torch.tensor(para['q_st_end']).squeeze().to(device)
    q_ae_start = torch.tensor(para['q_ae_start']).squeeze().to(device)
    q_ae_end = torch.tensor(para['q_ae_end']).squeeze().to(device)

    # チャネル重み (あれば)
    channel_weights = None
    if 'channel_weights' in para:
        cw = np.array(para['channel_weights'])
        channel_weights = torch.tensor(cw, dtype=torch.float32).reshape(1, -1, 1, 1).to(device)

    # edge_mask_w (Phase H): para から自動取得。旧 para.json は 0 として扱う。
    edge_mask_w = int(para.get('edge_mask_w', 0))

    # 候補1 (z-score OR, monochro 専用): cand1_enabled があれば μ,σ,A,Z を読む。
    # model.py の load_para() と同じ変換 (mu/sigma を (1,1,H,W) にreshape)。
    cand1 = None
    if para.get('cand1_enabled', False):
        mu = np.array(para['cand1_mu'], dtype=np.float32)
        sigma = np.array(para['cand1_sigma'], dtype=np.float32)
        cand1 = {
            'mu': torch.tensor(mu, dtype=torch.float32).view(1, 1, *mu.shape).to(device),
            'sigma': torch.tensor(sigma, dtype=torch.float32).view(1, 1, *sigma.shape).to(device),
            'A': float(para['cand1_A']),
            'Z': float(para['cand1_Z']),
        }

    return {
        'teacher': teacher.to(device),
        'student': student.to(device),
        'autoencoder': autoencoder.to(device),
        'teacher_mean': teacher_mean,
        'teacher_std': teacher_std,
        'q_st_start': q_st_start,
        'q_st_end': q_st_end,
        'q_ae_start': q_ae_start,
        'q_ae_end': q_ae_end,
        'channel_weights': channel_weights,
        'height': img_h,
        'width': img_w,
        'st_para': para.get('st_para', 1.0),
        'ae_para': para.get('ae_para', 0.0),
        'cand1': cand1,
        'edge_mask_w': edge_mask_w,
        'para': para,
    }
```

`training/evaluation/scoring.py:210-231` の `_predict_st_only()` 関数を削除する(丸ごと削除、この関数は共有関数への切替で不要になる)。

`_predict_st_only()`があった位置の後、`score_images()`(修正前234-302行目)を以下に置換する:

```python
def score_images(model_dict, image_dir, filenames, st_para=None, ae_para=None,
                 device='cpu', edge_mask_w=None):
    """画像リストに対してスコアを算出する。

    model.py の EfficientADFullModel が実際にデプロイされる際と同じ
    utils.scoring_transform.compute_anomaly_score を使ってスコアを計算する。

    Args:
        model_dict: load_model の返り値
        image_dir: 画像が格納されたディレクトリ
        filenames: 画像ファイル名のリスト
        st_para: map_st の重み。None なら model_dict['st_para'] (= para.json 由来) を使用。
        ae_para: map_ae の重み。None なら model_dict['ae_para'] (= para.json 由来) を使用。
        edge_mask_w: anomaly map 両端 N 列を 0 化してから max (PDN padding artifact 抑制)。
            None なら model_dict['edge_mask_w'] (= para.json 由来) を使用、明示指定で上書き可。

    Returns:
        dict: {filename: score} の辞書
    """
    from PIL import Image

    tf = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ])

    if st_para is None:
        st_para = model_dict.get('st_para', 1.0)
    if ae_para is None:
        ae_para = model_dict.get('ae_para', 0.0)
    if edge_mask_w is None:
        edge_mask_w = int(model_dict.get('edge_mask_w', 0))
    else:
        edge_mask_w = int(edge_mask_w)

    cand1 = model_dict.get('cand1')

    scores = {}
    for fname in tqdm(filenames, desc=f'Scoring {os.path.basename(image_dir)}'):
        path = os.path.join(image_dir, fname)
        image = Image.open(path).convert('RGB')
        image_t = tf(image).unsqueeze(0).to(device)

        with torch.no_grad():
            score_t = compute_anomaly_score(
                image_t,
                model_dict['teacher'],
                model_dict['student'],
                model_dict['autoencoder'],
                model_dict['teacher_mean'],
                model_dict['teacher_std'],
                st_para,
                ae_para,
                q_st_start=model_dict['q_st_start'],
                q_st_end=model_dict['q_st_end'],
                q_ae_start=model_dict['q_ae_start'],
                q_ae_end=model_dict['q_ae_end'],
                channel_weights=model_dict['channel_weights'],
                edge_mask_w=edge_mask_w,
                cand1=cand1,
                height=model_dict['height'],
                width=model_dict['width'],
            )
        scores[fname] = float(score_t.item())

    return scores
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd training && python -m pytest tests/evaluation/test_scoring_parity.py -v`
Expected: 3件ともPASS

- [ ] **Step 5: 既存の evaluation テストが壊れていないことを確認する**

Run: `cd training && python -m pytest tests/evaluation/test_evaluator.py -v`
Expected: 5件ともPASS(`evaluation.scoring.score_images`等を丸ごとmockしているため、内部実装変更の影響を受けない)

- [ ] **Step 6: 影響範囲レポートを作成する**

旧実装(常に`ae_para=0`固定・pad/interpolateなし・cand1なし)と新実装(`evaluation.scoring.score_images`、Step3で修正済み)のスコアを、同じ合成フィクスチャ上で直接計算して差分を記録する。旧実装のロジックはgit履歴に依存せず、スクリプト内に直接書き下ろす(Step3で削除された`_predict_st_only`相当のロジックをそのまま複製)。

`training/`ディレクトリ内に一時スクリプトとして以下を実行する(コミット対象ではない):

```python
# scratch: 旧実装 vs 新実装のスコア差分を計測する(一時実行用、リポジトリにはコミットしない)
# 実行: cd training && python <このファイル>
import numpy as np
import torch
from torchvision import transforms
from PIL import Image

from utils.common import get_pdn_small, get_autoencoder
from utils.scoring_transform import compute_anomaly_score

torch.manual_seed(0)
np.random.seed(0)
H, W = 256, 512
OUT_CH = 384

teacher = get_pdn_small(OUT_CH)
student = get_pdn_small(2 * OUT_CH)
autoencoder = get_autoencoder(OUT_CH, image_size_height=H, image_size_width=W)
teacher.eval(); student.eval(); autoencoder.eval()

img_np = np.random.randint(0, 256, (H, W, 3), dtype=np.uint8)
pil_img = Image.fromarray(img_np)
tf = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])
image_t = tf(pil_img).unsqueeze(0)

teacher_mean = torch.zeros(1, OUT_CH, 1, 1)
teacher_std = torch.ones(1, OUT_CH, 1, 1)

with torch.no_grad():
    t_out = teacher(image_t)
    s_out = student(image_t)
    map_st_probe = torch.mean((t_out - s_out[:, :OUT_CH]) ** 2, dim=1, keepdim=True)
    ae_out = autoencoder(image_t)
    map_ae_probe = torch.mean((ae_out - s_out[:, OUT_CH:]) ** 2, dim=1, keepdim=True)
q_st_start, q_st_end = map_st_probe.min(), map_st_probe.max()
q_ae_start, q_ae_end = map_ae_probe.min(), map_ae_probe.max()


def old_score(ae_para):
    """旧score_images: 常にst_para=1.0/ae_para=0.0扱い、pad/interpolateなし、cand1なし。"""
    with torch.no_grad():
        t_out = teacher(image_t)
        t_out_n = (t_out - teacher_mean) / teacher_std
        s_out = student(image_t)
        diff_st = (t_out_n - s_out[:, :OUT_CH]) ** 2
        map_st = torch.mean(diff_st, dim=1, keepdim=True)
        map_st = 0.1 * (map_st - q_st_start) / (q_st_end - q_st_start)
        anomaly_map = 1.0 * map_st  # 旧実装は ae_para 引数を無視して常にこの式
        return anomaly_map.max().item()


def new_score(ae_para, cand1=None):
    with torch.no_grad():
        score = compute_anomaly_score(
            image_t, teacher, student, autoencoder, teacher_mean, teacher_std,
            st_para=1.0, ae_para=ae_para,
            q_st_start=q_st_start, q_st_end=q_st_end,
            q_ae_start=q_ae_start, q_ae_end=q_ae_end,
            cand1=cand1, height=H, width=W,
        )
    return score.item()


print("config A (ae_para=0, cand1無し): old=%.6f new=%.6f" % (old_score(0.0), new_score(0.0)))
print("config B (ae_para=0.7): old=%.6f new=%.6f" % (old_score(0.7), new_score(0.7)))

torch.manual_seed(1)
mu = torch.rand(1, 1, map_st_probe.shape[2], map_st_probe.shape[3]) * 0.05
sigma = torch.rand(1, 1, map_st_probe.shape[2], map_st_probe.shape[3]) * 0.04 + 0.01
cand1 = {'mu': mu, 'sigma': sigma, 'A': 1.0, 'Z': 3.0}
print("config C (monochro+cand1): old=%.6f new=%.6f" % (old_score(0.0), new_score(0.0, cand1=cand1)))
```

Run: `cd training && python <上記スクリプトのパス>`

出力される実際の `old=` / `new=` の値をそのまま次のレポートの表に埋める。`docs/superpowers/specs/2026-07-21-training-seam3-scoring-impact-report.md` を新規作成する(表の数値はスクリプト実行結果の実測値に置き換えること):

```markdown
# Seam3(training/) スコアリング統合の影響範囲レポート

ADR-6(evaluationとdeployのスコアリング実装重複の統合)実施により、
`evaluation.scoring.score_images()` の計算結果が変わる。合成フィクスチャ
(seed=0)での実測(スクリプト出力の`old=`/`new=`を転記):

| 構成 | 旧実装スコア | 新実装スコア | 備考 |
|---|---|---|---|
| A: ae_para=0, cand1無し(color相当) | (スクリプト出力のold) | (スクリプト出力のnew) | pad+bilinear補間後にmaxを取るようになり、全color modelで恒常的なズレが解消される |
| B: ae_para=0.7(AE有効) | (スクリプト出力のold) | (スクリプト出力のnew) | 旧実装は常にae_para=0扱いでAE項を無視していた潜在バグを解消 |
| C: monochro+cand1有効 | (スクリプト出力のold) | (スクリプト出力のnew) | cand1コード自体が存在しなかったため、全monochroモデルでスケールが根本的に変わる |

**運用上の注意:** この修正後にrecordされるAUC/F1/miss_rate/false_alarm_rateは、
修正前の履歴データと直接比較できない(スコアのスケール・分布が変わるため)。
既存の閾値(para.jsonのthreshold)は`find_optimal_threshold`で評価時に
再計算されるため、この点は自動的に追随する。

設計書（`docs/superpowers/specs/2026-07-21-training-modular-monolith-migration-design.md`）
§5で事前承認済みの挙動変更に対応する実測レポート。
```

- [ ] **Step 7: コミット**

```bash
git add training/evaluation/scoring.py training/tests/evaluation/test_scoring_parity.py \
        docs/superpowers/specs/2026-07-21-training-seam3-scoring-impact-report.md
git commit -m "$(cat <<'EOF'
fix(training-evaluation): scoringをutils.scoring_transform経由に統一しmodel.pyのデプロイスコアと一致させる

evaluation.scoring.score_images()がutils.scoring_transform.compute_anomaly_score
を使ってスコアを計算するように変更。旧実装はst_para=1.0/ae_para=0.0を決め打ち、
pad+interpolateもcand1も未実装だったため、model.pyの実際のデプロイスコアと
不一致だった(設計書§5, ADR-6)。この修正でevaluationの評価指標
(AUC/F1/miss_rate/false_alarm_rate)は変わる(cand1有効なmonochroモデルで
特に顕著)。影響範囲は docs/superpowers/specs/2026-07-21-training-seam3-scoring-impact-report.md
に実測値として記録。ユーザー承認済みの意図的な挙動変更。
EOF
)"
```

---

## Task 3: dead code削除とCI gate更新

**Files:**
- Delete: `training/evaluation/predict.py`
- Modify: `training/tests/ci_gates/test_evaluation_boundary.py`

**Interfaces:**
- Consumes: Task1/2で完成した `utils.scoring_transform.compute_anomaly_score` への一本化
- Produces: CI gateが「`evaluation/scoring.py`が`utils.scoring_transform`を経由してスコアを計算していること」「pad/interpolateロジックを直接再実装していないこと」を検証する

- [ ] **Step 1: `training/evaluation/predict.py` に残存する呼び出し元がないことを確認する**

Run: `cd training && grep -rn "evaluation.predict\|evaluation\.predict" --include="*.py" .`
Expected: `training/evaluation/predict.py` 自身の定義以外に一致なし(Task2 Step3で`training/evaluation/scoring.py`のimportを削除済みのため)

- [ ] **Step 2: `training/evaluation/predict.py` を削除する**

```bash
git rm training/evaluation/predict.py
```

- [ ] **Step 3: 失敗するCI gateテストを先に書く**

`training/tests/ci_gates/test_evaluation_boundary.py` の全文を以下に置換する:

変更前(全文):
```python
"""training/evaluationステージの境界を守るCI gate。

evaluation.scoring / evaluation.predict（評価ロジックの低レベルモジュール）を
直接importできるのは training/evaluation パッケージ内のみであることを保証する。
他のモジュールは evaluation.Evaluator の公開APIのみを使用すること。

走査対象は training/ 配下のみに限定する（app_ver2はEfficientADと異なり、
同一リポジトリに backend/ 等の無関係なPythonコードを含むため。設計書ADR-app4）。
"""
import ast
from pathlib import Path

TRAINING_ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIR_NAMES = {"tests", "evaluation", "__pycache__"}
INTERNAL_MODULES = {"evaluation.scoring", "evaluation.predict"}


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


def test_pipline_does_not_import_evaluation_internals_directly():
    """pipline.py は evaluation.scoring / evaluation.predict を直接importしてはいけない。
    評価処理は evaluation.Evaluator の公開APIを経由すること。"""
    pipline_path = TRAINING_ROOT / "pipline.py"
    assert _imported_module_names(pipline_path).isdisjoint(INTERNAL_MODULES)


def test_only_evaluation_module_imports_scoring_internals():
    """evaluation.scoring / evaluation.predict を直接importしているのは
    training/evaluation パッケージ内のみであること（境界の逆行を防ぐラチェット）。"""
    offenders = []
    for py_file in TRAINING_ROOT.rglob("*.py"):
        rel_parts = py_file.relative_to(TRAINING_ROOT).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if _imported_module_names(py_file) & INTERNAL_MODULES:
            offenders.append(str(py_file.relative_to(TRAINING_ROOT)))
    assert offenders == [], f"evaluation外からのevaluation.scoring/predict直接importを検出: {offenders}"
```

変更後(全文):
```python
"""training/evaluationステージの境界を守るCI gate。

evaluation.scoring（評価ロジックの低レベルモジュール）を直接importできるのは
training/evaluation パッケージ内のみであることを保証する。他のモジュールは
evaluation.Evaluator の公開APIのみを使用すること。

加えて、evaluation.scoring が anomaly score 計算を utils.scoring_transform
に一本化していること(ADR-6: evaluationとdeployのスコアリング実装重複の
解消)をラチェットとして検証する。

走査対象は training/ 配下のみに限定する（app_ver2はEfficientADと異なり、
同一リポジトリに backend/ 等の無関係なPythonコードを含むため。設計書ADR-app4）。
"""
import ast
from pathlib import Path

TRAINING_ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIR_NAMES = {"tests", "evaluation", "__pycache__"}
INTERNAL_MODULES = {"evaluation.scoring"}


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


def test_pipline_does_not_import_evaluation_internals_directly():
    """pipline.py は evaluation.scoring を直接importしてはいけない。
    評価処理は evaluation.Evaluator の公開APIを経由すること。"""
    pipline_path = TRAINING_ROOT / "pipline.py"
    assert _imported_module_names(pipline_path).isdisjoint(INTERNAL_MODULES)


def test_only_evaluation_module_imports_scoring_internals():
    """evaluation.scoring を直接importしているのは
    training/evaluation パッケージ内のみであること（境界の逆行を防ぐラチェット）。"""
    offenders = []
    for py_file in TRAINING_ROOT.rglob("*.py"):
        rel_parts = py_file.relative_to(TRAINING_ROOT).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if _imported_module_names(py_file) & INTERNAL_MODULES:
            offenders.append(str(py_file.relative_to(TRAINING_ROOT)))
    assert offenders == [], f"evaluation外からのevaluation.scoring直接importを検出: {offenders}"


def test_evaluation_scoring_imports_shared_transform():
    """evaluation/scoring.py は utils.scoring_transform.compute_anomaly_score を
    介してスコアを計算すること（ADR-6: 実装重複再発防止のラチェット）。"""
    scoring_path = TRAINING_ROOT / "evaluation" / "scoring.py"
    assert "utils.scoring_transform" in _imported_module_names(scoring_path)


def test_evaluation_scoring_does_not_reimplement_transform_math():
    """evaluation/scoring.py が pad+interpolate 等の transform ロジックを
    直接書いていないこと（共有関数の呼び出しに一本化されているかの検査）。"""
    scoring_path = TRAINING_ROOT / "evaluation" / "scoring.py"
    source = scoring_path.read_text(encoding="utf-8")
    forbidden_snippets = ["F.pad", "functional.pad", "F.interpolate", "functional.interpolate"]
    offenders = [s for s in forbidden_snippets if s in source]
    assert offenders == [], f"evaluation/scoring.py に transform ロジックの再実装を検出: {offenders}"
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd training && python -m pytest tests/ci_gates/test_evaluation_boundary.py -v`
Expected: 4件ともPASS(既存2件 + 今回追加2件)

- [ ] **Step 5: プロジェクト全体のテストを実行する**

Run: `cd training && python -m pytest tests/ -v`
Expected: 全件PASS(26件: Task1完了時点で21件 + Task2で`test_scoring_parity.py`3件追加=24件 + Task3で`test_evaluation_boundary.py`に2件追加=26件)

**重要（無関係WIPの分離）**: `training/pipline.py`は本Taskで変更しない。コミット前に`git diff training/pipline.py`を確認し、本Seamと無関係な既存WIP（`_spawn_with_gpu_env`のspawn-context修正）が誤って含まれていないことを確認すること（触っていないので通常は問題ないが、確認を怠らないこと）。

- [ ] **Step 6: コミット**

`git rm`(Step 2)で削除は既にステージ済みのため、変更したCI gateファイルのみ追加する:

```bash
git add training/tests/ci_gates/test_evaluation_boundary.py
git commit -m "$(cat <<'EOF'
chore(training-evaluation): dead codeとなったevaluation/predict.pyを削除しCI gateをADR-6準拠に更新

evaluation/scoring.pyがutils.scoring_transform経由に統一されたことで
呼び出し元がゼロになったevaluation/predict.pyを削除。CI gateに
evaluation.scoringがutils.scoring_transformを経由すること、
pad/interpolateロジックを再実装していないことを検証するテストを追加。
EOF
)"
```

---

## 完了条件（このSeamのDone）

- `training/model.py`の`EfficientADFullModel.forward()`と`training/evaluation/scoring.py`の`score_images()`が同一の`utils.scoring_transform.compute_anomaly_score`を呼ぶ
- `training/evaluation/predict.py`（dead code）が削除されている
- パリティテスト（`training/tests/test_scoring_transform.py`・`training/tests/model/test_efficientad_full_model_regression.py`・`training/tests/evaluation/test_scoring_parity.py`）が全てPASSし、model.pyのeager実行と共有関数経由の新実装が一致することを実証している
- 影響範囲レポート（`docs/superpowers/specs/2026-07-21-training-seam3-scoring-impact-report.md`）が実測値で作成され、evaluationの評価指標が変わることが明文化されている
- CI gate（`training/tests/ci_gates/test_evaluation_boundary.py`）が4件に拡張され、`evaluation.scoring`が`utils.scoring_transform`を経由することをラチェットとして検証する
- `cd training && python -m pytest tests/ -v` が全件PASS（26件）
- `training/pipline.py`・`training/tests/test_pipline_skip_flags.py`は本Seamで変更されていない
- 設計書（`docs/superpowers/specs/2026-07-21-training-modular-monolith-migration-design.md`）§8のSeam3が完了としてマークできる状態になっている
