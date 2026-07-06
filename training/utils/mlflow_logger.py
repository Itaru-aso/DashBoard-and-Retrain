"""MLflow 実験管理ユーティリティ

パイプライン全体を親 run、各段階 (train/cw_compute/power_sweep/threshold_optimization/
final_evaluation) を nested 子 run として記録する。
色番号ごとに experiment を分離 (`efficientad_color_{color}`)。
"""
from __future__ import annotations

import logging
import os
import mlflow
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from omegaconf import DictConfig, OmegaConf

logger = logging.getLogger(__name__)


class ParallelRunLockError(RuntimeError):
    """同一色で並行実行を検出したとき発生"""


class MLflowManager:
    """MLflow による実験管理。enabled=False で全メソッドが no-op 化する。"""

    SECRET_KEY_PATTERNS = ("password", "secret", "token", "apikey", "api_key")
    EXCLUDE_KEY_PATTERNS = ("ftp_info",)  # 接続情報は丸ごと除外

    DEFAULT_CONFIG = {
        "enabled": True,
        "tracking_uri": "./mlruns",
        "experiment_name_template": "efficientad_color_{color}",
        "run_name_template": "pipeline_{timestamp}_{variant}",
        "run_name": None,
        "variant": None,
        "targets": {"fpr": 0.03, "fnr": 0.05},
        "log": {
            "train_step_interval": 500,
            "onnx_model": True,
            "fp_fn_samples": True,
            "fp_fn_samples_max": 10,
            "fp_fn_samples_annotate": True,
            "heatmaps": False,
            "score_distribution": True,
            "roc_curve": True,
            "confusion_matrix": True,
        },
        "extra_tags": {},
    }

    def __init__(self, cfg: DictConfig):
        mlflow_cfg = cfg.get("mlflow", OmegaConf.create({}))
        # デフォルトとのマージ
        defaults = OmegaConf.create(self.DEFAULT_CONFIG)
        merged = OmegaConf.merge(defaults, mlflow_cfg)
        self.cfg = merged
        self.full_cfg = cfg

        self.enabled: bool = bool(merged.enabled)
        self.tracking_uri: str = str(merged.tracking_uri)
        self.target_color: str = str(cfg.target_color)
        self.parent_run_id: str | None = None

    # -----------------------------------------------------------------------
    # Task 14: 並行実行ロック
    # -----------------------------------------------------------------------

    def _lock_path(self) -> Path:
        """ロックファイルのパスを返す。"""
        return Path(self.tracking_uri) / f".mlflow_pipeline_{self.target_color}.lock"

    def _acquire_lock(self):
        """ロックを取得する。既にロックが存在する場合は ParallelRunLockError を発生させる。"""
        if not self.enabled:
            return
        lock_path = self._lock_path()
        if lock_path.exists():
            raise ParallelRunLockError(
                f"並行実行を検出: ロックファイルが存在します: {lock_path}"
            )
        lock_path.write_text(str(os.getpid()))

    def _release_lock(self):
        """ロックを解放する。失敗時は warn して無視。"""
        if not self.enabled:
            return
        lock_path = self._lock_path()
        try:
            if lock_path.exists():
                lock_path.unlink()
        except Exception as e:
            logger.warning(f"[mlflow] ロックファイル削除失敗: {e}")

    def start_pipeline_run(self, variant: str, run_name: str | None = None) -> str:
        """親 run を開始。experiment が無ければ作成。"""
        if not self.enabled:
            return ""

        # tracking_uri ディレクトリ作成 (相対パスは絶対パスに解決)
        tracking_path = Path(self.tracking_uri).resolve()
        tracking_path.mkdir(parents=True, exist_ok=True)

        # 並行実行チェック
        self._acquire_lock()

        try:
            # Windows 絶対パスは file:// URI に変換して mlflow に渡す
            mlflow.set_tracking_uri(tracking_path.as_uri())

            # experiment 名
            experiment_name = self.cfg.experiment_name_template.format(color=self.target_color)
            mlflow.set_experiment(experiment_name)

            # run_name 決定: 引数 > config override > auto
            if run_name is None:
                run_name = self.cfg.run_name  # config からの override
            if run_name is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                run_name = self.cfg.run_name_template.format(
                    timestamp=timestamp, variant=variant, color=self.target_color
                )

            run = mlflow.start_run(run_name=run_name)
            self.parent_run_id = run.info.run_id
            return run.info.run_id
        except Exception:
            self._release_lock()
            raise

    def end_pipeline_run(self, status: str = "FINISHED"):
        """親 run を指定ステータスで終了。"""
        if not self.enabled:
            return
        try:
            mlflow.end_run(status=status)
        finally:
            self.parent_run_id = None
            self._release_lock()

    # -----------------------------------------------------------------------
    # Task 13: start_nested_run (context manager)
    # -----------------------------------------------------------------------

    @contextmanager
    def start_nested_run(self, stage: str):
        """nested run を context manager として開始。例外発生時は自動で FAILED 終了。"""
        if not self.enabled:
            yield None
            return
        run = mlflow.start_run(nested=True, run_name=stage)
        try:
            mlflow.set_tag("stage", stage)
            yield run
        except Exception as e:
            mlflow.set_tag("error", str(e)[:500])
            mlflow.end_run(status="FAILED")
            raise
        else:
            mlflow.end_run(status="FINISHED")

    def infer_variant(self, cw_method: str | None, power: int | None) -> str:
        """cw_method + power から variant 識別子を自動生成。cfg.mlflow.variant がセット済みならそれを返す。"""
        if self.cfg.get("variant"):
            return str(self.cfg.variant)
        if cw_method is None or power is None:
            return "baseline"
        prefix = "sup" if cw_method == "supervised" else "unsup"
        return f"{prefix}_cw_p{power}"

    # -----------------------------------------------------------------------
    # Task 5: Config ログ (flatten + secrets 除外)
    # -----------------------------------------------------------------------

    def _flatten(self, d: dict, prefix: str = "") -> dict:
        """ネスト dict を `model.lr` 形式にフラット化する。"""
        out = {}
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(self._flatten(v, key))
            else:
                out[key] = v
        return out

    def _is_excluded(self, key: str) -> bool:
        """シークレットキーまたは除外プレフィックスにマッチする場合 True。"""
        key_lower = key.lower()
        if any(p in key_lower for p in self.SECRET_KEY_PATTERNS):
            return True
        if any(key_lower.startswith(p) for p in self.EXCLUDE_KEY_PATTERNS):
            return True
        return False

    def log_config(self, cfg: DictConfig, flatten: bool = True):
        """Config を mlflow params としてログする。secrets 除外・100件バッチ分割あり。"""
        if not self.enabled:
            return
        try:
            d = OmegaConf.to_container(cfg, resolve=True)
            flat = self._flatten(d) if flatten else d
            # シークレット・除外キーを除去
            filtered = {k: v for k, v in flat.items() if not self._is_excluded(k)}
            # 値を文字列化・500文字上限・None 除外
            params = {k: str(v)[:500] for k, v in filtered.items() if v is not None}
            # mlflow の log_params バッチ制限 (100) を考慮して分割送信
            items = list(params.items())
            for i in range(0, len(items), 100):
                mlflow.log_params(dict(items[i:i + 100]))
        except Exception as e:
            logger.warning(f"[mlflow] log_config failed: {e}")

    # -----------------------------------------------------------------------
    # Task 6: log_metrics + log_evaluation (正規化メトリクス)
    # -----------------------------------------------------------------------

    def log_metrics(self, metrics: dict, step: int | None = None):
        """メトリクスを mlflow に記録。None 値除外・float 化。"""
        if not self.enabled:
            return
        try:
            clean = {k: float(v) for k, v in metrics.items() if v is not None}
            mlflow.log_metrics(clean, step=step)
        except Exception as e:
            logger.warning(f"[mlflow] log_metrics failed: {e}")

    def log_evaluation(
        self,
        prefix: str,
        tp: int,
        fn: int,
        fp: int,
        tn: int,
        auc: float,
        threshold: float | None = None,
    ):
        """評価結果を正規化メトリクスと生件数の両方で記録する。"""
        if not self.enabled:
            return

        n_pos = tp + fn
        n_neg = fp + tn
        fpr = fp / n_neg if n_neg > 0 else 0.0
        fnr = fn / n_pos if n_pos > 0 else 0.0
        recall = 1.0 - fnr
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        target_fpr = float(self.cfg.targets.fpr)
        target_fnr = float(self.cfg.targets.fnr)

        metrics = {
            f"{prefix}_auc": auc,
            f"{prefix}_fpr": fpr,
            f"{prefix}_fnr": fnr,
            f"{prefix}_recall": recall,
            f"{prefix}_precision": precision,
            f"{prefix}_f1": f1,
            f"{prefix}_fp_count": float(fp),
            f"{prefix}_fn_count": float(fn),
            f"{prefix}_tp_count": float(tp),
            f"{prefix}_tn_count": float(tn),
            f"{prefix}_n_pos": float(n_pos),
            f"{prefix}_n_neg": float(n_neg),
            f"{prefix}_fpr_target_achieved": 1.0 if fpr < target_fpr else 0.0,
            f"{prefix}_fnr_target_achieved": 1.0 if fnr < target_fnr else 0.0,
        }
        if threshold is not None:
            metrics[f"{prefix}_threshold"] = float(threshold)

        self.log_metrics(metrics)

    # -----------------------------------------------------------------------
    # Task 7: log_sweep_results (power 別メトリクス)
    # -----------------------------------------------------------------------

    def log_sweep_results(self, sweep_name: str, results: list):
        """power 別の結果を {sweep_name}_{key}_p{power} 形式で記録する。

        results の各 dict は {'power': int, 'auc': float, ...} 形式。
        """
        if not self.enabled:
            return
        try:
            metrics = {}
            for r in results:
                power = r.get("power")
                if power is None:
                    continue
                for k, v in r.items():
                    if k == "power":
                        continue
                    if isinstance(v, (int, float)):
                        metrics[f"{sweep_name}_{k}_p{power}"] = float(v)
            if metrics:
                mlflow.log_metrics(metrics)
        except Exception as e:
            logger.warning(f"[mlflow] log_sweep_results failed: {e}")

    # -----------------------------------------------------------------------
    # Task 8: set_tags + apply_default_tags
    # -----------------------------------------------------------------------

    def set_tags(self, tags: dict):
        """タグを str 化して mlflow に記録する。"""
        if not self.enabled:
            return
        try:
            mlflow.set_tags({k: str(v) for k, v in tags.items() if v is not None})
        except Exception as e:
            logger.warning(f"[mlflow] set_tags failed: {e}")

    def apply_default_tags(self, cw_method: str | None = None):
        """extra_tags + target_color + cw_method + operator を自動付与する。"""
        if not self.enabled:
            return
        tags: dict = {"target_color": self.target_color}
        if cw_method:
            tags["cw_method"] = cw_method
        tags["operator"] = (
            os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
        )
        extra = OmegaConf.to_container(
            self.cfg.get("extra_tags", OmegaConf.create({})), resolve=True
        ) or {}
        tags.update({str(k): str(v) for k, v in extra.items()})
        self.set_tags(tags)

    # -----------------------------------------------------------------------
    # Task 9: log_artifact / log_artifacts (存在確認付き)
    # -----------------------------------------------------------------------

    def log_artifact(self, path, artifact_subdir: str | None = None):
        """ファイルを mlflow に保存する。存在しない場合は warn して skip。"""
        if not self.enabled:
            return
        p = Path(path)
        if not p.exists():
            logger.warning(f"[mlflow] log_artifact skipped (file not found): {p}")
            return
        try:
            mlflow.log_artifact(str(p), artifact_path=artifact_subdir)
        except Exception as e:
            logger.warning(f"[mlflow] log_artifact failed: {e}")

    def log_artifacts(self, dir_path, artifact_subdir: str | None = None):
        """ディレクトリ全体を mlflow に保存する。存在しない場合は warn して skip。"""
        if not self.enabled:
            return
        d = Path(dir_path)
        if not d.exists():
            logger.warning(f"[mlflow] log_artifacts skipped (dir not found): {d}")
            return
        try:
            mlflow.log_artifacts(str(d), artifact_path=artifact_subdir)
        except Exception as e:
            logger.warning(f"[mlflow] log_artifacts failed: {e}")

    # -----------------------------------------------------------------------
    # Task 10: log_fp_fn_samples
    # -----------------------------------------------------------------------

    def _save_image_with_annotation(self, src: Path, dst: Path, score: float, threshold: float):
        """PIL でスコアを左上に焼き込んで保存する。失敗時は shutil.copy フォールバック。"""
        try:
            from PIL import Image, ImageDraw
            img = Image.open(str(src)).convert("RGB")
            draw = ImageDraw.Draw(img)
            text = f"Score: {score:.4f} / Thr: {threshold:.4f}"
            # textbbox で背景矩形サイズ取得
            bbox = draw.textbbox((0, 0), text)
            # 白背景矩形
            draw.rectangle(
                [bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2],
                fill=(255, 255, 255),
            )
            # 黒テキスト
            draw.text((0, 0), text, fill=(0, 0, 0))
            img.save(str(dst))
        except Exception as e:
            logger.warning(f"[mlflow] _save_image_with_annotation failed, fallback copy: {e}")
            import shutil
            shutil.copy(str(src), str(dst))

    def log_fp_fn_samples(
        self,
        fp_samples: list,
        fn_samples: list,
        threshold: float,
        cw_power: int,
        cw_method: str,
    ):
        """FP/FN サンプル画像 + manifest.json を mlflow に保存する。"""
        if not self.enabled:
            return
        if not self.cfg.log.get("fp_fn_samples", True):
            return
        try:
            import json
            import shutil
            import tempfile

            max_samples = int(self.cfg.log.get("fp_fn_samples_max", 10))
            annotate = bool(self.cfg.log.get("fp_fn_samples_annotate", True))

            # score 降順ソート + 件数制限
            fp_sorted = sorted(fp_samples, key=lambda x: x[1], reverse=True)[:max_samples]
            fn_sorted = sorted(fn_samples, key=lambda x: x[1], reverse=True)[:max_samples]

            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir_path = Path(tmpdir)
                fp_dir = tmpdir_path / "fp_samples"
                fn_dir = tmpdir_path / "fn_samples"
                fp_dir.mkdir()
                fn_dir.mkdir()

                def _save_samples(samples, kind, out_dir, true_label):
                    entries = []
                    for rank, (img_path, score) in enumerate(samples, start=1):
                        src = Path(img_path)
                        stem = src.stem
                        filename = (
                            f"{kind}_rank{rank:02d}"
                            f"_score{score:.4f}"
                            f"_thr{threshold:.4f}"
                            f"_orig_{stem}.png"
                        )
                        dst = out_dir / filename
                        if annotate:
                            self._save_image_with_annotation(src, dst, score, threshold)
                        else:
                            shutil.copy(str(src), str(dst))
                        entries.append({
                            "rank": rank,
                            "filename": filename,
                            "original_path": str(src),
                            "score": float(score),
                            "threshold": float(threshold),
                            "distance_from_threshold": float(score - threshold),
                            "true_label": true_label,
                        })
                    return entries

                fp_entries = _save_samples(fp_sorted, "fp", fp_dir, true_label=0)
                fn_entries = _save_samples(fn_sorted, "fn", fn_dir, true_label=1)

                manifest = {
                    "threshold": float(threshold),
                    "cw_power": int(cw_power),
                    "cw_method": str(cw_method),
                    "fp_samples": fp_entries,
                    "fn_samples": fn_entries,
                }
                manifest_path = tmpdir_path / "manifest.json"
                manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

                mlflow.log_artifacts(str(tmpdir_path), artifact_path="samples")

        except Exception as e:
            logger.warning(f"[mlflow] log_fp_fn_samples failed: {e}")

    # -----------------------------------------------------------------------
    # Task 11: log_onnx_model
    # -----------------------------------------------------------------------

    def log_onnx_model(self, onnx_path):
        """ONNX モデルファイルを onnx/ サブディレクトリに保存する。"""
        if not self.enabled:
            return
        if not self.cfg.log.get("onnx_model", True):
            return
        self.log_artifact(onnx_path, artifact_subdir="onnx")

    # -----------------------------------------------------------------------
    # Task 12: log_figure (matplotlib)
    # -----------------------------------------------------------------------

    def log_figure(self, fig, filename: str):
        """matplotlib figure を figures/ サブディレクトリに保存する。"""
        if not self.enabled:
            return
        try:
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                dst = Path(tmpdir) / filename
                fig.savefig(str(dst), dpi=120, bbox_inches="tight")
                mlflow.log_artifact(str(dst), artifact_path="figures")
        except Exception as e:
            logger.warning(f"[mlflow] log_figure failed: {e}")
