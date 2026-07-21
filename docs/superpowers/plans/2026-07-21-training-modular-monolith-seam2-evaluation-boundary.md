# training/ モジュラモノリス移行 Seam2: evaluationのモジュール境界確立 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `training/pipline.py`に定義されている`Evaluator`クラスと、それが依存する`training/utils/evaluation_pipeline.py`・`training/utils/evaluation.py`を、新設の`training/evaluation`パッケージの公開API (`evaluation.Evaluator`) に切り出し、CI gateで境界の逆行を防止する。Seam1（deployのFTPアップロード境界化）は完了済み。

**Architecture:** strangler-fig方式。(1) 現状挙動をcharacterization testで固定 → (2) `training/evaluation`パッケージに同一内容を新設（旧コードは残したまま並存） → (3) `pipline.py`を新APIへリダイレクトし旧実装（`pipline.py`内の`Evaluator`クラス、`utils/evaluation_pipeline.py`、`utils/evaluation.py`）を削除 → (4) 境界の逆行を防ぐCI gateテストを追加。設計根拠は `docs/superpowers/specs/2026-07-21-training-modular-monolith-migration-design.md` §2・§8（Seam2）、および先行実装 `D:\0032011\GitLab\shisui\EfficientAD` の同名Seam（`docs/superpowers/plans/2026-07-14-modular-monolith-seam2-evaluation-boundary.md`）を参照。

**Tech Stack:** Python 3.11 / pytest 9.x（`training/`をcwdとして`python -m pytest`で実行可能、確認済み） / `unittest.mock`（標準ライブラリ） / OmegaConf（既存依存） / pytestの`tmp_path`フィクスチャ（標準）

## Global Constraints

- 内部アーキテクチャは全モジュール layered に統一する（hexagonal不採用。設計書ADR-1継承）
- 新規の外部依存パッケージは追加しない
- スコアリングロジック自体（`load_model`/`score_images`/`compute_metrics`/`find_optimal_threshold`/`predict`/`compute_image_score`の内部実装）は変更しない。挙動は現状と完全に同一（数値計算ロジックの統合はSeam3で扱う。本Seamはモジュール境界の移動のみ）
- `evaluate()`の結果がdeployを止めるゲートになっていない現状の挙動は維持する（設計書ADR-2継承。変更しない）
- `training/utils/common.py`・`training/utils/edge_mask.py`・`training/utils/split_manager.py`は複数ステージ（train/deploy/dataset）で共有されるため、`evaluation`パッケージへは移動せず`training/utils/`に残す
- テストは`training/`をcwdとして`python -m pytest`で実行すること（`cd training && python -m pytest tests/... -v`）
- CI gateの走査対象は`training/`配下に限定する（設計書ADR-app4。`backend/`等の無関係なPythonコードを誤検出しないため）
- `training/tests/__init__.py`（Seam1で追加済み）がpytestのimport-mode名前衝突を既に予防解消しているため、本Seamで同種の対応を再度行う必要はない
- コミットメッセージは日本語、`<type>(<scope>): <subject>`形式（Conventional Commits）

---

## 事前調査で確認した事実（実装者は前提として使ってよい。2026-07-21、app_ver2の実ソースで確認済み）

- `training/utils/evaluation_pipeline.py`の`load_model`/`score_images`/`compute_metrics`/`find_optimal_threshold`を呼んでいるのは、`training/pipline.py`の`Evaluator.evaluate()`メソッド内のローカルimport（522行目）のみ（他に呼び出し元はない。`grep -rn "evaluation_pipeline" training/*.py training/utils/*.py`で確認済み。`utils/edge_mask.py`に1件ヒットするが、これはコメント内の言及のみでimportではない）
- `training/utils/evaluation.py`の`predict`/`compute_image_score`を呼んでいるのは`training/utils/evaluation_pipeline.py:16`のみ（他に呼び出し元はない）
- `training/utils/split_manager.py`は`pipline.py`のdatasetステージ（`split_pool_to_train_test`、22行目でimport）と`utils/evaluation_pipeline.py`内の未使用関数`evaluate_model`（`load_split`使用、`pipline.py`からは呼ばれていない）の両方から参照されているため、`utils/`に残す
- `training/utils/predict.py`（`utils/evaluation.py`とほぼ同名の別関数）は`training/`配下で参照箇所がゼロ（既存のdead code）。本Seamでは触らない
- `training/pipline.py`の`Evaluator`クラスは**501〜566行目**に定義されている（Seam1でFTPアップロード関連コードが削除されたため、EfficientAD側の527〜593行目から行数がシフトしている）
- `training/pipline.py`の29行目は`import deploy`（Seam1で追加済み）
- **`training/tests/test_pipline_skip_flags.py`（Seam1で更新済み）の`_run()`内`patch.object(pipline, "Evaluator")`（51行目）は、`Evaluator`が`pipline.py`内のクラス定義からimportされた名前に変わっても、`pipline.Evaluator`という属性名は変わらないため、本Seamでは変更不要**（Seam1のFTPアップロードのように呼び出し形態が`self.ftp_manager.X()`→`deploy.X()`に変わるケースとは異なり、`Evaluator(...)`という呼び出し方自体は変化しない）

---

## Task 1: 現状のEvaluator挙動を固定する characterization test

**Files:**
- Create: `training/tests/evaluation/__init__.py`（空。Seam1の`tests/deploy/`と同じ慣例に揃えるため。pytestの名前衝突は`training/tests/__init__.py`で既に解消済みなので必須ではないが、一貫性のため作成する）
- Create: `training/tests/evaluation/test_evaluator_characterization.py`

**Interfaces:**
- Consumes: `pipline.Evaluator`（現状の実装、変更しない）
- Produces: `evaluation.Evaluator`（Task2）が満たすべき期待値（`load_model`/`score_images`/`find_optimal_threshold`/`compute_metrics`の呼び出し形状、早期return条件）

- [ ] **Step 1: characterization testを書く**

```python
# training/tests/evaluation/test_evaluator_characterization.py
"""現状の pipline.Evaluator.evaluate() の挙動を固定するテスト。

Seam2移行（evaluationパッケージへの切り出し）前の挙動を記録し、
Task2で実装する新実装 (evaluation.Evaluator) が同じ結果を出すことの比較対象とする。

実行: cd training && python -m pytest tests/evaluation/test_evaluator_characterization.py -v
"""
import os
from unittest.mock import MagicMock, patch

from omegaconf import OmegaConf

import pipline


def _make_cfg(tmp_path):
    return OmegaConf.create({
        "common": {
            "dataset_path": str(tmp_path / "4_dataset"),
            "model_dir": str(tmp_path / "6_model"),
        }
    })


def _make_test_dirs(tmp_path, color="841", mode="color",
                     good_files=("g1.png",), defect_files=("d1.png",)):
    dataset_path = tmp_path / "4_dataset" / color / mode
    good_dir = dataset_path / "test" / "good" / "images"
    defect_dir = dataset_path / "test" / "defect" / "images"
    good_dir.mkdir(parents=True, exist_ok=True)
    defect_dir.mkdir(parents=True, exist_ok=True)
    for f in good_files:
        (good_dir / f).write_bytes(b"")
    for f in defect_files:
        (defect_dir / f).write_bytes(b"")


def _make_model_dir_with_para(tmp_path, color="841", mode="color"):
    model_dir = tmp_path / "6_model" / color / mode
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "para.json").write_text("{}")
    return str(model_dir)


def test_evaluate_computes_metrics_and_logs_when_test_data_present(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path)
    _make_model_dir_with_para(tmp_path)

    mgr = MagicMock()
    ev = pipline.Evaluator(cfg, color="841", mode="color", mgr=mgr)

    fake_metrics = {"AUC": 0.9, "F1": 0.8, "miss_rate": 0.1, "false_alarm_rate": 0.05}
    with patch("utils.evaluation_pipeline.load_model", return_value={"model": "dummy"}) as mock_load, \
         patch("utils.evaluation_pipeline.score_images") as mock_score, \
         patch("utils.evaluation_pipeline.find_optimal_threshold", return_value=0.5) as mock_thresh, \
         patch("utils.evaluation_pipeline.compute_metrics", return_value=fake_metrics) as mock_metrics:
        mock_score.side_effect = [{"g1.png": 0.1}, {"d1.png": 0.9}]
        result = ev.evaluate()

    mock_load.assert_called_once_with(ev.model_dir)
    assert mock_score.call_count == 2
    mock_thresh.assert_called_once_with([0.1], [0.9])
    mock_metrics.assert_called_once_with([0.1], [0.9], 0.5)
    mgr.log_metrics.assert_called_once_with(fake_metrics)
    assert result == fake_metrics


def test_evaluate_returns_none_when_test_directories_missing(tmp_path):
    cfg = _make_cfg(tmp_path)
    # test/good, test/defect ディレクトリを作らない
    ev = pipline.Evaluator(cfg, color="841", mode="color")

    result = ev.evaluate()

    assert result is None


def test_evaluate_returns_none_when_file_lists_empty(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path, good_files=(), defect_files=())
    ev = pipline.Evaluator(cfg, color="841", mode="color")

    result = ev.evaluate()

    assert result is None


def test_evaluate_returns_none_when_para_json_missing(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path)
    # para.json を作らない
    ev = pipline.Evaluator(cfg, color="841", mode="color")

    result = ev.evaluate()

    assert result is None


def test_evaluate_returns_none_when_scoring_raises(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path)
    _make_model_dir_with_para(tmp_path)
    ev = pipline.Evaluator(cfg, color="841", mode="color")

    with patch("utils.evaluation_pipeline.load_model", side_effect=RuntimeError("boom")):
        result = ev.evaluate()

    assert result is None
```

- [ ] **Step 2: 実行して現状コードに対してPASSすることを確認する**

Run: `cd training && python -m pytest tests/evaluation/test_evaluator_characterization.py -v`
Expected: 5件全てPASSする（現状コードの挙動を記録するテストなので、変更前のコードに対してPASSするのが正しい結果です）

- [ ] **Step 3: commit**

```bash
git add training/tests/evaluation/__init__.py training/tests/evaluation/test_evaluator_characterization.py
git commit -m "$(cat <<'EOF'
test(training-evaluation): Evaluatorの現状挙動を固定するcharacterization testを追加

training/ のモジュラモノリス移行Seam2（evaluation境界化）に先立ち、
pipline.Evaluator.evaluate()の現状挙動（正常系のメトリクス算出・MLflow記録、
test データ欠落時のNone返却、para.json欠落時のNone返却、
例外時のNone返却）をcharacterization testとして固定する。
EOF
)"
```

---

## Task 2: `training/evaluation`パッケージに公開APIを新規実装する（TDD red → green）

**Files:**
- Create: `training/evaluation/predict.py`（`training/utils/evaluation.py`のコピー、内容変更なし）
- Create: `training/evaluation/scoring.py`（`training/utils/evaluation_pipeline.py`のコピー、import 1行のみ変更）
- Create: `training/evaluation/evaluator.py`
- Create: `training/evaluation/__init__.py`
- Test: `training/tests/evaluation/test_evaluator.py`

**Interfaces:**
- Consumes: `evaluation.scoring.load_model/score_images/compute_metrics/find_optimal_threshold`（本タスクで新設）
- Produces:
  - `evaluation.Evaluator(cfg, color: str, mode: str = "color", mgr=None)`（evaluationステージの公開API）
  - `evaluation.Evaluator.evaluate() -> dict | None`

- [ ] **Step 1: 失敗するテストを書く**

```python
# training/tests/evaluation/test_evaluator.py
"""evaluation.Evaluator の公開APIテスト。

Task1のcharacterization testと同じ期待値（呼び出し形状・早期return条件）を
検証することで、旧実装(pipline.Evaluator)との挙動の一致を保証する。

実行: cd training && python -m pytest tests/evaluation/test_evaluator.py -v
"""
import os
from unittest.mock import MagicMock, patch

from omegaconf import OmegaConf

import evaluation


def _make_cfg(tmp_path):
    return OmegaConf.create({
        "common": {
            "dataset_path": str(tmp_path / "4_dataset"),
            "model_dir": str(tmp_path / "6_model"),
        }
    })


def _make_test_dirs(tmp_path, color="841", mode="color",
                     good_files=("g1.png",), defect_files=("d1.png",)):
    dataset_path = tmp_path / "4_dataset" / color / mode
    good_dir = dataset_path / "test" / "good" / "images"
    defect_dir = dataset_path / "test" / "defect" / "images"
    good_dir.mkdir(parents=True, exist_ok=True)
    defect_dir.mkdir(parents=True, exist_ok=True)
    for f in good_files:
        (good_dir / f).write_bytes(b"")
    for f in defect_files:
        (defect_dir / f).write_bytes(b"")


def _make_model_dir_with_para(tmp_path, color="841", mode="color"):
    model_dir = tmp_path / "6_model" / color / mode
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "para.json").write_text("{}")
    return str(model_dir)


def test_evaluate_computes_metrics_and_logs_when_test_data_present(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path)
    _make_model_dir_with_para(tmp_path)

    mgr = MagicMock()
    ev = evaluation.Evaluator(cfg, color="841", mode="color", mgr=mgr)

    fake_metrics = {"AUC": 0.9, "F1": 0.8, "miss_rate": 0.1, "false_alarm_rate": 0.05}
    with patch("evaluation.scoring.load_model", return_value={"model": "dummy"}) as mock_load, \
         patch("evaluation.scoring.score_images") as mock_score, \
         patch("evaluation.scoring.find_optimal_threshold", return_value=0.5) as mock_thresh, \
         patch("evaluation.scoring.compute_metrics", return_value=fake_metrics) as mock_metrics:
        mock_score.side_effect = [{"g1.png": 0.1}, {"d1.png": 0.9}]
        result = ev.evaluate()

    mock_load.assert_called_once_with(ev.model_dir)
    assert mock_score.call_count == 2
    mock_thresh.assert_called_once_with([0.1], [0.9])
    mock_metrics.assert_called_once_with([0.1], [0.9], 0.5)
    mgr.log_metrics.assert_called_once_with(fake_metrics)
    assert result == fake_metrics


def test_evaluate_returns_none_when_test_directories_missing(tmp_path):
    cfg = _make_cfg(tmp_path)
    ev = evaluation.Evaluator(cfg, color="841", mode="color")

    result = ev.evaluate()

    assert result is None


def test_evaluate_returns_none_when_file_lists_empty(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path, good_files=(), defect_files=())
    ev = evaluation.Evaluator(cfg, color="841", mode="color")

    result = ev.evaluate()

    assert result is None


def test_evaluate_returns_none_when_para_json_missing(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path)
    ev = evaluation.Evaluator(cfg, color="841", mode="color")

    result = ev.evaluate()

    assert result is None


def test_evaluate_returns_none_when_scoring_raises(tmp_path):
    cfg = _make_cfg(tmp_path)
    _make_test_dirs(tmp_path)
    _make_model_dir_with_para(tmp_path)
    ev = evaluation.Evaluator(cfg, color="841", mode="color")

    with patch("evaluation.scoring.load_model", side_effect=RuntimeError("boom")):
        result = ev.evaluate()

    assert result is None
```

- [ ] **Step 2: 実行してFAILを確認する**

Run: `cd training && python -m pytest tests/evaluation/test_evaluator.py -v`
Expected: `ModuleNotFoundError: No module named 'evaluation'` によりFAIL（`training/evaluation`パッケージが未実装のため）

- [ ] **Step 3: `training/evaluation/predict.py`を作成する（`training/utils/evaluation.py`のコピー、内容変更なし）**

```bash
mkdir -p training/evaluation
cp training/utils/evaluation.py training/evaluation/predict.py
```

コピー後、`training/evaluation/predict.py`の内容は`training/utils/evaluation.py`と完全に同一であることを確認する（`from utils.edge_mask import apply_edge_mask_zero`のようなimportは変更不要。`utils/edge_mask.py`は複数ステージ共有のため`utils/`に残るため）。

- [ ] **Step 4: `training/evaluation/scoring.py`を作成する（`training/utils/evaluation_pipeline.py`のコピー、import 1行のみ変更）**

```bash
cp training/utils/evaluation_pipeline.py training/evaluation/scoring.py
```

コピー後、`training/evaluation/scoring.py`内の以下の1行（16行目）を変更する。

変更前:
```python
from utils.evaluation import predict as _predict, compute_image_score
```

変更後:
```python
from evaluation.predict import predict as _predict, compute_image_score
```

他の行（`from utils.common import get_pdn_small, get_autoencoder`、`from utils.edge_mask import apply_edge_mask_zero`、`from utils.split_manager import load_split`等）は変更しない（これらは複数ステージ共有のため`utils/`に残る）。

- [ ] **Step 5: コピーの忠実性を検証する**

以降のテストは全て`load_model`等をモックするため、実際のスコアリング数式（`training/evaluation/predict.py`・`training/evaluation/scoring.py`の中身）を実行しては検証しない。コピー・編集が意図通りであることを、この時点でdiffにより直接確認する。

Run: `git diff --no-index training/utils/evaluation.py training/evaluation/predict.py`
Expected: 出力なし（両ファイルが完全に同一）

Run: `git diff --no-index training/utils/evaluation_pipeline.py training/evaluation/scoring.py`
Expected: Step4で示した1行（`from utils.evaluation import ...` → `from evaluation.predict import ...`）の差分のみ。それ以外の差分があれば、意図しない変更が入っているためStep4を修正する。

- [ ] **Step 6: `training/evaluation/evaluator.py`を作成する**

```python
# training/evaluation/evaluator.py
"""evaluationステージ: 学習済みモデルの test-set オフライン評価。"""
import os


class Evaluator:
    """学習済みモデルに対して test/{good,defect}/images で評価指標を計算するクラス。

    test/{good,defect}/images が存在しない場合は警告だけで例外なし、None を返す。
    """

    def __init__(self, cfg, color: str, mode: str = "color", mgr=None):
        self.cfg = cfg
        self.color = str(color)
        self.mode = mode
        self.dataset_path = os.path.join(cfg.common.dataset_path, self.color, mode)
        self.model_dir = os.path.join(cfg.common.model_dir, self.color, mode)
        self.mgr = mgr

    def evaluate(self):
        """評価を実行してメトリクスを返す。

        Returns:
            dict: AUC, F1, miss_rate, false_alarm_rate 等を含む dict。
                  test データがない場合は None。
        """
        from evaluation.scoring import load_model, score_images, compute_metrics, find_optimal_threshold

        test_good = os.path.join(self.dataset_path, "test", "good", "images")
        test_defect = os.path.join(self.dataset_path, "test", "defect", "images")

        if not (os.path.isdir(test_good) and os.path.isdir(test_defect)):
            print(f"⚠️ test データが見つかりません: {test_good} / {test_defect}")
            return None

        IMAGE_EXTS = ('.bmp', '.png', '.jpg', '.jpeg', '.tiff')
        good_files = [f for f in os.listdir(test_good) if f.lower().endswith(IMAGE_EXTS)]
        defect_files = [f for f in os.listdir(test_defect) if f.lower().endswith(IMAGE_EXTS)]

        if not good_files or not defect_files:
            print(f"⚠️ test データが空です (good: {len(good_files)}, defect: {len(defect_files)})")
            return None

        try:
            para_path = os.path.join(self.model_dir, 'para.json')
            if not os.path.isfile(para_path):
                print(f"⚠️ para.json が見つかりません: {para_path}")
                return None

            model_dict = load_model(self.model_dir)
            scores_good_dict = score_images(model_dict, test_good, good_files)
            scores_defect_dict = score_images(model_dict, test_defect, defect_files)
            scores_good = list(scores_good_dict.values())
            scores_defect = list(scores_defect_dict.values())

            threshold = find_optimal_threshold(scores_good, scores_defect)
            metrics = compute_metrics(scores_good, scores_defect, threshold)

            print(
                f"[{self.mode}] 評価結果: AUC={metrics.get('AUC', 0.0):.4f}, "
                f"false_alarm_rate={metrics.get('false_alarm_rate', 0.0):.4f}, "
                f"miss_rate={metrics.get('miss_rate', 0.0):.4f}, "
                f"F1={metrics.get('F1', 0.0):.4f}"
            )
            if self.mgr is not None:
                self.mgr.log_metrics(metrics)
            return metrics
        except Exception as e:
            print(f"⚠️ 評価エラー: {e}")
            return None
```

（`training/pipline.py`内の現行実装（501〜566行目）と1文字単位で同一。`from utils.evaluation_pipeline import ...`だった箇所のみ`from evaluation.scoring import ...`に変更し、`evaluate()`メソッド内のローカルimportという構造もそのまま維持している。print文言も一切変更していない。）

- [ ] **Step 7: `training/evaluation/__init__.py`を作成する**

```python
# training/evaluation/__init__.py
"""evaluationステージの公開API。

evaluationパッケージ外からは `evaluation.Evaluator` のみを使用すること。
`evaluation.scoring` / `evaluation.predict` 内の関数を外部から
直接importしてはならない（境界はtests/ci_gates/test_evaluation_boundary.pyで検証）。
"""
from evaluation.evaluator import Evaluator

__all__ = ["Evaluator"]
```

- [ ] **Step 8: 実行してPASSを確認する**

Run: `cd training && python -m pytest tests/evaluation/test_evaluator.py -v`
Expected: 5件全てPASSする

- [ ] **Step 9: commit**

```bash
git add training/evaluation/__init__.py training/evaluation/predict.py training/evaluation/scoring.py training/evaluation/evaluator.py training/tests/evaluation/test_evaluator.py
git commit -m "$(cat <<'EOF'
feat(training-evaluation): evaluationステージの公開APIを新設

evaluation.Evaluator(cfg, color, mode, mgr) を追加。
pipline.Evaluatorと同一の挙動（正常系のメトリクス算出・MLflow記録、
test データ欠落時のNone返却、para.json欠落時のNone返却、
例外時のNone返却）を tests/evaluation/test_evaluator_characterization.py
と同じ期待値で検証。scoring/predictロジック自体は
utils/evaluation_pipeline.py・utils/evaluation.pyから変更なくコピー。
EOF
)"
```

---

## Task 3: `pipline.py`を`evaluation`公開API経由にリダイレクトし旧実装を削除する

**Files:**
- Modify: `training/pipline.py`（import文、`Evaluator`クラス削除）
- Delete: `training/tests/evaluation/test_evaluator_characterization.py`
- Delete: `training/utils/evaluation_pipeline.py`
- Delete: `training/utils/evaluation.py`

**Interfaces:**
- Consumes: `evaluation.Evaluator(cfg, color, mode, mgr)`（Task2で実装済み）
- Produces: `pipline.py`の観測可能な挙動は変更なし（Task2のテストが引き続き回帰防止テストとして機能する）

- [ ] **Step 1: `pipline.py`のimport文を修正する**

29行目 `import deploy` の直後に1行追加する。

変更前:
```python
from model_handler import ONNXModelHandler
import deploy
```

変更後:
```python
from model_handler import ONNXModelHandler
import deploy
from evaluation import Evaluator
```

- [ ] **Step 2: `pipline.py`から`Evaluator`クラスを削除する**

削除対象（`class Evaluator:`から、その直後の`class TrainingPipeline:`の直前まで、501〜566行目）:
```python
class Evaluator:
    """学習済みモデルに対して test/{good,defect}/images で評価指標を計算するクラス。

    test/{good,defect}/images が存在しない場合は警告だけで例外なし、None を返す。
    """

    def __init__(self, cfg, color: str, mode: str = "color", mgr=None):
        self.cfg = cfg
        self.color = str(color)
        self.mode = mode
        self.dataset_path = os.path.join(cfg.common.dataset_path, self.color, mode)
        self.model_dir = os.path.join(cfg.common.model_dir, self.color, mode)
        self.mgr = mgr

    def evaluate(self):
        """評価を実行してメトリクスを返す。

        Returns:
            dict: AUC, F1, miss_rate, false_alarm_rate 等を含む dict。
                  test データがない場合は None。
        """
        from utils.evaluation_pipeline import load_model, score_images, compute_metrics, find_optimal_threshold

        test_good = os.path.join(self.dataset_path, "test", "good", "images")
        test_defect = os.path.join(self.dataset_path, "test", "defect", "images")

        if not (os.path.isdir(test_good) and os.path.isdir(test_defect)):
            print(f"⚠️ test データが見つかりません: {test_good} / {test_defect}")
            return None

        # 画像ファイル一覧を取得
        IMAGE_EXTS = ('.bmp', '.png', '.jpg', '.jpeg', '.tiff')
        good_files = [f for f in os.listdir(test_good) if f.lower().endswith(IMAGE_EXTS)]
        defect_files = [f for f in os.listdir(test_defect) if f.lower().endswith(IMAGE_EXTS)]

        if not good_files or not defect_files:
            print(f"⚠️ test データが空です (good: {len(good_files)}, defect: {len(defect_files)})")
            return None

        try:
            para_path = os.path.join(self.model_dir, 'para.json')
            if not os.path.isfile(para_path):
                print(f"⚠️ para.json が見つかりません: {para_path}")
                return None

            model_dict = load_model(self.model_dir)
            scores_good_dict = score_images(model_dict, test_good, good_files)
            scores_defect_dict = score_images(model_dict, test_defect, defect_files)
            scores_good = list(scores_good_dict.values())
            scores_defect = list(scores_defect_dict.values())

            threshold = find_optimal_threshold(scores_good, scores_defect)
            metrics = compute_metrics(scores_good, scores_defect, threshold)

            print(
                f"[{self.mode}] 評価結果: AUC={metrics.get('AUC', 0.0):.4f}, "
                f"false_alarm_rate={metrics.get('false_alarm_rate', 0.0):.4f}, "
                f"miss_rate={metrics.get('miss_rate', 0.0):.4f}, "
                f"F1={metrics.get('F1', 0.0):.4f}"
            )
            if self.mgr is not None:
                self.mgr.log_metrics(metrics)
            return metrics
        except Exception as e:
            print(f"⚠️ 評価エラー: {e}")
            return None
```

このクラス全体を削除する（削除後、直前の`_spawn_with_gpu_env`関数の直後に空行2行を挟んで`class TrainingPipeline:`が続く形にする。`execute()`メソッド内の`ev = Evaluator(self.cfg, color, mode=sub_mode, mgr=mgr)` / `ev.evaluate()`の呼び出しコードは変更しない——`Evaluator`という名前は今後Step1で追加したimportにより解決される）。

- [ ] **Step 3: Task1のcharacterization testを削除する**

対象（`pipline.Evaluator`）が削除されたため、これを対象としていたテストは役目を終える。Task2のテスト(`training/tests/evaluation/test_evaluator.py`)が同じ期待値を検証しているため、回帰防止の役割はそちらに引き継がれている。

```bash
git rm training/tests/evaluation/test_evaluator_characterization.py
```

- [ ] **Step 4: 旧実装ファイルを削除する**

`training/evaluation/scoring.py`・`training/evaluation/predict.py`にコピー済みで、他に参照元がないことを確認済み（本計画冒頭の「事前調査で確認した事実」参照）。

```bash
git rm training/utils/evaluation_pipeline.py training/utils/evaluation.py
```

- [ ] **Step 5: `training/tests/test_pipline_skip_flags.py`が変更なく緑化することを確認する**

本Seamでは`patch.object(pipline, "Evaluator")`（51行目）の対象を変更する必要はない（`Evaluator`が`pipline.py`のimport名になっても属性名は変わらないため。本計画冒頭の「事前調査で確認した事実」参照）。ファイルは変更しないが、回帰していないことを確認する。

Run: `cd training && python -m pytest tests/test_pipline_skip_flags.py -v`
Expected: 3件全てPASSする（変更なし・後方互換）

- [ ] **Step 6: Task2のテストを再実行し、回帰していないことを確認する**

Run: `cd training && python -m pytest tests/evaluation/test_evaluator.py -v`
Expected: 5件全てPASSする（リダイレクト後も変わらずPASSする）

- [ ] **Step 7: `pipline.py`がimportエラーなく読み込めることを確認する**

Run: `cd training && python -c "import pipline"`
Expected: エラーなく終了する（exit code 0、出力なし）

- [ ] **Step 8: `training/`配下で`utils.evaluation_pipeline`・`utils.evaluation`への参照が残っていないことを確認する**

Run: `cd training && grep -rn "utils.evaluation_pipeline\|utils\.evaluation\b" --include="*.py" .`
Expected: 一致なし（削除したファイルへの参照が残っていない。コメント内言及も含めて残っていないことを確認する）

- [ ] **Step 9: 全テストを再実行する**

Run: `cd training && python -m pytest tests/ -v`
Expected: 全件PASS（Seam1由来の9件 + Task2の`tests/evaluation/test_evaluator.py`5件 = 14件。※作業ツリーにSeam1完了時点の既存WIP(`_spawn_with_gpu_env`のspawn-context修正、`test_pipline_spawn_context.py`)が残っている前提での件数）

- [ ] **Step 10: commit**

```bash
git add training/pipline.py
git rm training/tests/evaluation/test_evaluator_characterization.py training/utils/evaluation_pipeline.py training/utils/evaluation.py
git commit -m "$(cat <<'EOF'
refactor(training-pipline): 評価処理をevaluation公開API経由にリダイレクト

pipline.py内のEvaluatorクラス定義をevaluation.Evaluatorへの
importに置き換え、旧実装（pipline.py内のEvaluatorクラス、
utils/evaluation_pipeline.py、utils/evaluation.py）を削除。
挙動は変更なし（tests/evaluation/test_evaluator.pyで検証済み）。
test_pipline_skip_flags.pyは変更不要（Evaluatorという属性名は不変）。
Task1のcharacterization testは対象クラス削除に伴い削除。
EOF
)"
```

**重要（無関係WIPの分離）**: Seam1と同様、作業ツリーの`training/pipline.py`には本Seamと無関係な既存WIP（`_spawn_with_gpu_env`の`multiprocessing.get_context("spawn")`修正）が残っている想定。`git add training/pipline.py`の前に`git diff training/pipline.py`で本Task3の変更（Step1・Step2）のみが含まれることを確認し、無関係なWIPを混入させないこと。

---

## Task 4: CI Gate — evaluation境界の逆行を防ぐテスト

**Files:**
- Create: `training/tests/ci_gates/test_evaluation_boundary.py`

**Interfaces:**
- Consumes: `training/`配下の`*.py`ファイル群（ソースコード自体を検査対象とする。`backend/`等は対象外＝設計書ADR-app4）
- Produces: 回帰防止用のCI gate（新たなランタイムAPIは提供しない）

`training/tests/ci_gates/__init__.py`はSeam1で作成済み（新規作成不要）。

- [ ] **Step 1: 境界テストを書く**

```python
# training/tests/ci_gates/test_evaluation_boundary.py
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

- [ ] **Step 2: 実行してPASSを確認する**

Run: `cd training && python -m pytest tests/ci_gates/test_evaluation_boundary.py -v`
Expected: `test_pipline_does_not_import_evaluation_internals_directly PASSED`, `test_only_evaluation_module_imports_scoring_internals PASSED`

- [ ] **Step 3: ラチェットが実際に機能することを手動で確認する**

`training/pipline.py`のimport文（Task3 Step1で追加した箇所）を一時的に以下へ変更する（確認用、最終的に元に戻す）:

```python
from model_handler import ONNXModelHandler
import deploy
from evaluation import Evaluator
from evaluation.scoring import load_model
```

Run: `cd training && python -m pytest tests/ci_gates/test_evaluation_boundary.py -v`
Expected: `test_pipline_does_not_import_evaluation_internals_directly FAILED`（ゲートが正しく違反を検出することの確認）

確認後、`training/pipline.py`のimport文を元に戻す:

```python
from model_handler import ONNXModelHandler
import deploy
from evaluation import Evaluator
```

Run: `cd training && python -m pytest tests/ci_gates/test_evaluation_boundary.py -v`
Expected: 再び全てPASSする

- [ ] **Step 4: commit**

```bash
git add training/tests/ci_gates/test_evaluation_boundary.py
git commit -m "$(cat <<'EOF'
test(training-evaluation): evaluation境界の逆行を防ぐCI gateテストを追加

evaluation.scoring / evaluation.predict を直接importできるのは
training/evaluationパッケージ内のみであることを検証するテストを追加。
走査対象はtraining/配下に限定（backend/等の無関係なPythonコードを
誤検出しないため。設計書ADR-app4）。
Seam2（evaluationのモジュール境界確立）の完了条件として、
以後の境界逆行をCIで検出できるようにする。
EOF
)"
```

**重要（無関係WIPの分離）**: Step3の一時変更・確認後は必ず元に戻し、`git add`前に`git diff training/pipline.py`が本Seamの変更（Task3で加えたimport1行のみ）＋Seam1完了時点の既存WIPのみであることを確認すること。

---

## 完了条件（このSeamのDone）

- `evaluation.Evaluator(cfg, color, mode, mgr)` が公開APIとして存在し、`training/pipline.py`はこれ経由でのみ評価処理を行う
- `training/pipline.py`から`Evaluator`クラス定義が削除され、`training/utils/evaluation_pipeline.py`・`training/utils/evaluation.py`が削除されている
- Task2のテストが、Task1のcharacterization testと同一の期待値でPASSしている（挙動が変わっていないことの証拠）
- `training/tests/test_pipline_skip_flags.py`が無変更のまま緑化している（Evaluatorの呼び出し形態が変わらないことの証拠）
- CI gate（`training/tests/ci_gates/test_evaluation_boundary.py`）が導入され、境界の逆行を検出できることをTask4 Step3で確認済み
- `cd training && python -m pytest tests/ -v` が全件PASS
- 設計書（`docs/superpowers/specs/2026-07-21-training-modular-monolith-migration-design.md`）§8のSeam2が完了としてマークできる状態になっている
