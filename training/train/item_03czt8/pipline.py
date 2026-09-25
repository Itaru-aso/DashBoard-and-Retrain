"""03CZT8専用の学習パイプライン(ステージ実行シーケンス)。

`training/pipline.py` の `TrainingPipeline` 系のコピーである。既存の
`training/pipline.py` は一切変更しない
（`.kiro/specs/retraining/new-item-03czt8-model-creation.md` v3.0 決定3）。

コピー元との差分は以下のみ:
    - `train.train_monochro`/`train.train_color` の代わりに
      `train.item_03czt8.train_monochro.train_monochro`/
      `train.item_03czt8.train_color.train_color` を使う。

`DatasetManager`（`dataset/manager.py`）・`deploy`・`evaluation.Evaluator`は
無変更でimportして使う（決定3の「無変更でimport」区分）。これらは色番non-の
汎用ロジックであり、`common.model_dir`/`common.pool_base`/`common.dataset_path`/
`common.splits_dir`/`common.backup_dir`を03CZT8専用パスに設定することで
（決定4）既存05CZT8アーティファクトとの混在を避ける。

保守負債に関する注記: `training/pipline.py` と設計・ロジックが大部分重複する。
`pipline.py`側に不具合修正・仕様変更が入る場合は、本ファイルへの影響有無を
確認すること（同ADR「リスク」節参照）。

実行: cd training && python -m train.item_03czt8.pipline
"""
import os
import multiprocessing
import warnings

# pydantic V2 系のサードパーティ依存 (MLflow 等) が発する schema_extra → json_schema_extra
# 改名警告を抑制 (機能影響なし、アプリ側で修正不可)
warnings.filterwarnings(
    "ignore",
    message=r"Valid config keys have changed in V2.*",
    category=UserWarning,
    module=r"pydantic\..*",
)

from omegaconf import OmegaConf
import torch
from utils.mlflow_logger import MLflowManager
from utils.log_tailer import LogTailer
from train.item_03czt8.train_color import train_color
from train.item_03czt8.train_monochro import train_monochro
from model_handler import ONNXModelHandler
import deploy
from evaluation import Evaluator
from dataset import DatasetManager


def build_sub_cfg(cfg, mode, gpu_id=0):
    """common と mode 別ブロックを merge して flat な sub_cfg を返す。"""
    sub = OmegaConf.merge(cfg.common, cfg[mode])
    sub.mode = mode
    sub.gpu_id = gpu_id
    return sub


class Trainer:
    def __init__(self, cfg, mode: str, gpu_id: int):
        self.cfg = cfg  # トップ cfg
        self.mode = mode
        self.gpu_id = gpu_id

    def run(self, mgr=None):
        """学習の実行。"""
        sub_cfg = build_sub_cfg(self.cfg, self.mode, self.gpu_id)
        phys = os.environ.get('CUDA_VISIBLE_DEVICES', 'all')
        if self.mode == "monochro":
            print(f"🟢 [03CZT8] モノクロAIの学習を開始します... (物理 GPU: {phys}, 論理 cuda:{self.gpu_id}, color: {sub_cfg.target_color})")
            train_monochro(sub_cfg, mgr=mgr)
        elif self.mode == "color":
            print(f"🔵 [03CZT8] カラーAIの学習を開始します... (物理 GPU: {phys}, 論理 cuda:{self.gpu_id}, color: {sub_cfg.target_color})")
            train_color(sub_cfg, mgr=mgr)
        else:
            print("⚠️ 不明なモードです。")


def run_trainer(cfg, mode, gpu_id, mgr=None, log_path=None):
    """学習を実行する (子プロセスのエントリポイント)。"""
    if log_path is not None:
        import sys
        try:
            _f = open(log_path, "w", encoding="utf-8", buffering=1)
            sys.stdout = _f
            sys.stderr = _f
        except Exception:
            pass
    trainer = Trainer(cfg, mode, gpu_id)
    trainer.run(mgr=mgr)


def _safe_cli_overrides(cli_args):
    """OmegaConf.from_dotlist 向けに CLI 引数を整形する。"""
    safe = []
    for arg in cli_args:
        if '=' not in arg:
            continue
        key, _, val = arg.partition('=')
        if key.endswith('target_color') and not (val.startswith("'") or val.startswith('"')):
            val = f"'{val}'"
        safe.append(f"{key}={val}")
    return safe


def _spawn_with_gpu_env(target, args, physical_gpu_id):
    """指定された物理 GPU で子プロセスを spawn する (CUDA_VISIBLE_DEVICES 切替版)。"""
    orig_cvd = os.environ.get('CUDA_VISIBLE_DEVICES')
    os.environ['CUDA_VISIBLE_DEVICES'] = str(physical_gpu_id)
    try:
        p = multiprocessing.get_context("spawn").Process(target=target, args=args)
        p.start()
        return p
    finally:
        if orig_cvd is None:
            os.environ.pop('CUDA_VISIBLE_DEVICES', None)
        else:
            os.environ['CUDA_VISIBLE_DEVICES'] = orig_cvd


class TrainingPipeline:
    def __init__(self, cfg):
        self.cfg = cfg
        self.dataset_manager = DatasetManager(self.cfg)

    def execute(self):
        """パイプラインを実行する。

        export_root（別機能が生成済み）→ pool振り分け → split → 並列学習 → ONNX → 評価 → アップロード。
        """
        color = str(self.cfg.common.target_color)
        print(f"[03CZT8] 学習パイプラインを開始します (color={color})...")

        # 1. バックアップ
        print("バックアップ作成中...")
        self.dataset_manager.backup_model()
        print("バックアップ完了")

        # 2. 前処理 (export_root → pool へ振り分け。画像取得は別機能が export_root に生成済み)
        self.dataset_manager.process_annotated_images()

        # 3. split_pool_to_dataset (color + monochro)
        self.dataset_manager.split_pool_to_dataset(color, mode="color")
        self.dataset_manager.split_pool_to_dataset(color, mode="monochro")

        # 4. MLflow Manager 生成 (color または monochro の mlflow.enabled=true 時)
        color_mlflow_enabled = self.cfg.color.mlflow.get("enabled", False)
        monochro_mlflow_enabled = self.cfg.monochro.mlflow.get("enabled", False)
        if color_mlflow_enabled:
            color_sub_cfg = build_sub_cfg(self.cfg, "color", gpu_id=0)
            mgr_color = MLflowManager(color_sub_cfg)
        else:
            mgr_color = None
        if monochro_mlflow_enabled:
            mono_sub_cfg = build_sub_cfg(self.cfg, "monochro", gpu_id=0)
            mgr_monochro = MLflowManager(mono_sub_cfg)
        else:
            mgr_monochro = None

        # 4b. 並列 or 直列学習
        parallel = self.cfg.common.get("parallel_train", True)
        any_mlflow = color_mlflow_enabled or monochro_mlflow_enabled
        if any_mlflow and parallel:
            print("⚠️ MLflow 有効時は parallel_train を OFF にします")
            parallel = False

        if parallel:
            gpu_count = torch.cuda.device_count() if torch.cuda.is_available() else 0
            if gpu_count >= 2:
                mono_gpu, color_gpu = 0, 1
            else:
                mono_gpu, color_gpu = 0, 0
            print(f"並列学習 GPU 割当: monochro=GPU{mono_gpu}, color=GPU{color_gpu} (検出: {gpu_count}枚)")
            mono_log = color_log = None
            tailer = None
            try:
                logs_dir = os.path.join(".", "logs")
                os.makedirs(logs_dir, exist_ok=True)
                mono_log = os.path.join(logs_dir, f"train_{color}_monochro_03czt8.log")
                color_log = os.path.join(logs_dir, f"train_{color}_color_03czt8.log")
                tailer = LogTailer(
                    [("monochro", mono_log), ("color", color_log)]).start()
            except Exception as e:
                print(f"⚠️ ログ集約の初期化に失敗 (学習は継続, 進捗は非表示): {e}")
                mono_log = color_log = None
                tailer = None

            p1 = _spawn_with_gpu_env(
                run_trainer, (self.cfg, "monochro", 0, None, mono_log), mono_gpu)
            p2 = _spawn_with_gpu_env(
                run_trainer, (self.cfg, "color", 0, None, color_log), color_gpu)
            p1.join()
            p2.join()
            if tailer is not None:
                tailer.stop()
        else:
            run_trainer(self.cfg, "monochro", 0, mgr=mgr_monochro)
            run_trainer(self.cfg, "color", 0, mgr=mgr_color)

        # 5. ONNX エクスポート + 評価 (両 mode) + アップロード
        skip_upload = self.cfg.common.get("skip_upload", False)
        for sub_mode in ["monochro", "color"]:
            sub_cfg = build_sub_cfg(self.cfg, sub_mode, gpu_id=0)
            deploy.export_model(sub_cfg)

            mgr = mgr_color if sub_mode == "color" else mgr_monochro
            ev = Evaluator(self.cfg, color, mode=sub_mode, mgr=mgr)
            ev.evaluate()

            self.cfg.common.mode = sub_mode
            if skip_upload:
                print(f"skip_upload=true: FTP アップロードをスキップ (mode={sub_mode})")
            else:
                deploy.upload_model(self.cfg, color, sub_mode)

        print("[03CZT8] パイプライン完了")


if __name__ == '__main__':
    import sys
    from omegaconf import OmegaConf
    config_path = os.path.join(os.path.dirname(__file__), 'conf_03czt8.yaml')
    cfg = OmegaConf.load(config_path)
    cli_overrides = [arg for arg in sys.argv[1:] if '=' in arg]
    if cli_overrides:
        cli_cfg = OmegaConf.from_dotlist(_safe_cli_overrides(cli_overrides))
        cfg = OmegaConf.merge(cfg, cli_cfg)
        print(f"CLI overrides 適用: {cli_overrides}")
    pipeline = TrainingPipeline(cfg)
    pipeline.execute()
