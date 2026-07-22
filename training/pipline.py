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
from train import train_color, train_monochro
from model_handler import ONNXModelHandler
import deploy
from evaluation import Evaluator
from dataset import DatasetManager, MultiFTPManager


def build_sub_cfg(cfg, mode, gpu_id=0):
    """common と mode 別ブロックを merge して flat な sub_cfg を返す。

    Args:
        cfg: トップレベルの OmegaConf cfg (common / monochro / color を含む)
        mode: "color" or "monochro"
        gpu_id: GPU 番号

    Returns:
        DictConfig: flat な sub_cfg (cfg.image_size_height 等で参照可能)
    """
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
        """学習の実行。

        Args:
            mgr: MLflowManager インスタンス (color/monochro どちらも対応)
        """
        sub_cfg = build_sub_cfg(self.cfg, self.mode, self.gpu_id)
        phys = os.environ.get('CUDA_VISIBLE_DEVICES', 'all')
        if self.mode == "monochro":
            print(f"🟢 モノクロAIの学習を開始します... (物理 GPU: {phys}, 論理 cuda:{self.gpu_id}, color: {sub_cfg.target_color})")
            train_monochro(sub_cfg, mgr=mgr)
        elif self.mode == "color":
            print(f"🔵 カラーAIの学習を開始します... (物理 GPU: {phys}, 論理 cuda:{self.gpu_id}, color: {sub_cfg.target_color})")
            train_color(sub_cfg, mgr=mgr)
        else:
            print("⚠️ 不明なモードです。")


def run_trainer(cfg, mode, gpu_id, mgr=None, log_path=None):
    """学習を実行する (子プロセスのエントリポイント)。

    parallel 並列学習では、親プロセス側で _spawn_with_gpu_env が
    CUDA_VISIBLE_DEVICES を切り替えてから子を spawn するため、子プロセス内では
    論理 cuda:0 のみを使う前提。gpu_id は論理デバイス番号 (CUDA_VISIBLE_DEVICES
    でフィルタ済の番号空間で 0 基点)。
    """
    # 並列学習の子プロセスは stdout/stderr が親 GUI に繋がらない。
    # log_path 指定時は専用ファイルへリダイレクトし、親の LogTailer が拾う。
    if log_path is not None:
        import sys
        try:
            _f = open(log_path, "w", encoding="utf-8", buffering=1)
            sys.stdout = _f
            sys.stderr = _f
        except Exception:
            pass  # 失敗時は従来動作 (リダイレクトなし) にフォールバック
    trainer = Trainer(cfg, mode, gpu_id)
    trainer.run(mgr=mgr)


def _safe_cli_overrides(cli_args):
    """OmegaConf.from_dotlist 向けに CLI 引数を整形する。

    target_color 等の色番号は文字列として扱う必要があるが、OmegaConf の値推論で
    '076' は 8 進数 0o76 = 10 進数 62 (int) に変換されてしまう。これを回避する
    ため、target_color 系のキーは値を明示的にシングルクォートで囲んで文字列化する。

    Args:
        cli_args: sys.argv[1:] 由来の "key=value" 形式リスト (= を含まない要素は無視)

    Returns:
        OmegaConf.from_dotlist にそのまま渡せる "key=value" 形式リスト
    """
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
    """指定された物理 GPU で子プロセスを spawn する (CUDA_VISIBLE_DEVICES 切替版)。

    親プロセスの CUDA_VISIBLE_DEVICES を一時的に切替 → Process.start → 元に戻す。
    spawn 子は親の env スナップショットを継承するため、子の import 段階から
    指定された GPU 1 枚のみを認識する (PyTorch CUDA 初期化のタイミング問題を回避)。

    Args:
        target: 子プロセスで実行する callable
        args: target に渡す位置引数 tuple
        physical_gpu_id: 子に見せる物理 GPU 番号

    Returns:
        起動済の multiprocessing.Process (呼出元で join すること)
    """
    orig_cvd = os.environ.get('CUDA_VISIBLE_DEVICES')
    os.environ['CUDA_VISIBLE_DEVICES'] = str(physical_gpu_id)
    try:
        p = multiprocessing.Process(target=target, args=args)
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
        self.ftp_manager = MultiFTPManager(self.cfg)

    def execute(self):
        """パイプラインを実行する。

        pipeline_mode=stage_only: FTP取得 + 前処理 (pool/staging 振り分け) のみ実施。
        pipeline_mode=train: split → 並列学習 → ONNX → 評価 → アップロード まで実施。
        """
        mode = self.cfg.common.get("pipeline_mode", "train")
        color = str(self.cfg.common.target_color)
        print(f"学習パイプラインを開始します (mode={mode}, color={color})...")

        # 1. バックアップ
        print("バックアップ作成中...")
        self.dataset_manager.backup_model()
        print("バックアップ完了")

        # 2. FTP ダウンロード (color/monochro どちらも good+defect を集約取得)
        # stage_only モードでは 1_download に手動配置した既存データを使うためスキップする
        # (新仕様では rmtree しないので技術的には実行可能だが、人手配置ユースケースを尊重)
        # skip_download=true でも DL をスキップする (ver2 連携: 画像は別機能が 1_download に事前配置)
        skip_download = self.cfg.common.get("skip_download", False)
        if mode == "stage_only":
            print("stage_only モード: FTP ダウンロードをスキップし、既存の 1_download を使用します")
        elif skip_download:
            print("skip_download=true: FTP ダウンロードをスキップし、既存の 1_download を使用します")
        else:
            for sub_mode in ["monochro", "color"]:
                self.cfg.common.mode = sub_mode
                self.ftp_manager.download_images()

        # 3. 前処理 (color/monochro どちらも pool/staging へ振り分け)
        self.dataset_manager.process_annotated_images()

        if mode == "stage_only":
            staging_color = os.path.join(self.cfg.common.staging_dir, color, "color")
            staging_mono = os.path.join(self.cfg.common.staging_dir, color, "monochro")
            color_count = len(os.listdir(staging_color)) if os.path.isdir(staging_color) else 0
            mono_count = len(os.listdir(staging_mono)) if os.path.isdir(staging_mono) else 0
            print(
                f"stage_only モード:\n"
                f"  color staging: {color_count} 件 ({staging_color})\n"
                f"  monochro staging: {mono_count} 件 ({staging_mono})\n"
                f"人手レビュー後、train モードで再実行してください。"
            )
            return

        # 4. split_pool_to_dataset (color + monochro)
        self.dataset_manager.split_pool_to_dataset(color, mode="color")
        self.dataset_manager.split_pool_to_dataset(color, mode="monochro")

        # 5. MLflow Manager 生成 (color または monochro の mlflow.enabled=true 時)
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

        # 5b. 並列 or 直列学習
        # MLflow 有効時 (どちらか一方でも) は multiprocessing で mgr を渡せないため自動的に直列化
        parallel = self.cfg.common.get("parallel_train", True)
        any_mlflow = color_mlflow_enabled or monochro_mlflow_enabled
        if any_mlflow and parallel:
            print("⚠️ MLflow 有効時は parallel_train を OFF にします")
            parallel = False

        if parallel:
            # GPU 枚数を検出して並列実行プロセスに別の物理 GPU を割り当てる。
            # 2 枚以上なら monochro→GPU0 / color→GPU1、1 枚なら両方 GPU0 (旧挙動)。
            gpu_count = torch.cuda.device_count() if torch.cuda.is_available() else 0
            if gpu_count >= 2:
                mono_gpu, color_gpu = 0, 1
            else:
                mono_gpu, color_gpu = 0, 0
            print(f"並列学習 GPU 割当: monochro=GPU{mono_gpu}, color=GPU{color_gpu} (検出: {gpu_count}枚)")
            # 親で env を切替してから spawn することで、子の import 段階から
            # 指定された物理 GPU 1 枚のみが見える状態にする (PyTorch CUDA 初期化の
            # タイミング問題を回避、本セッションで 181 学習にて確証)。
            # 子プロセスのログを専用ファイルへ出し、親が tail して GUI に集約する。
            mono_log = color_log = None
            tailer = None
            try:
                logs_dir = os.path.join(".", "logs")
                os.makedirs(logs_dir, exist_ok=True)
                mono_log = os.path.join(logs_dir, f"train_{color}_monochro.log")
                color_log = os.path.join(logs_dir, f"train_{color}_color.log")
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

        # 6. ONNX エクスポート + 評価 (両 mode) + アップロード
        # skip_upload=true では FTP 配信をスキップする (ver2 連携: 配信は deployment_service が担う)
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

        print("パイプライン完了")


if __name__ == '__main__':
    import sys
    from omegaconf import OmegaConf
    cfg = OmegaConf.load("./conf/config.yaml")
    # CLI dotlist override (例: common.target_color=076 color.mlflow.enabled=true)
    cli_overrides = [arg for arg in sys.argv[1:] if '=' in arg]
    if cli_overrides:
        # target_color の 8 進数解釈 (例: '076' → 62) を回避するため値をクォート
        cli_cfg = OmegaConf.from_dotlist(_safe_cli_overrides(cli_overrides))
        cfg = OmegaConf.merge(cfg, cli_cfg)
        print(f"CLI overrides 適用: {cli_overrides}")
    pipeline = TrainingPipeline(cfg)
    pipeline.execute()
