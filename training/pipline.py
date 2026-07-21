import os
import shutil
import datetime
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
from ftplib import FTP
import torch
import cv2
from utils.ftp_common import download_ftp_selected, is_directory, AnnotationDownloader
from utils.image_preprocessing import load_image_as_byte_array, process_image
from utils.split_manager import split_pool_to_train_test
from utils.mlflow_logger import MLflowManager
from utils.log_tailer import LogTailer
from train_func_monochro import train_monochro
from train_func_color import train_color
from model_exporter import ModelExporter
from model_handler import ONNXModelHandler
import deploy


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


class DatasetManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.target_color = cfg.common.target_color
        # mode 別画像サイズ
        self.image_sizes = {
            "monochro": (cfg.monochro.image_size_height, cfg.monochro.image_size_width),
            "color": (cfg.color.image_size_height, cfg.color.image_size_width),
        }
        self.dataset_path = cfg.common.dataset_path
        self.model_dir = cfg.common.model_dir
        self.download_dir = cfg.common.download_dir
        self.backup_dir = cfg.common.backup_dir

        # モードごとのデータセットパス
        self.mode_paths = {
            "monochro": os.path.join(self.dataset_path, str(self.target_color), "monochro", "train"),
            "color": os.path.join(self.dataset_path, str(self.target_color), "color", "train"),
        }

        # モードごとのモデル保存パス
        self.model_paths = {
            "monochro": os.path.join(self.model_dir, str(self.target_color), "monochro"),
            "color": os.path.join(self.model_dir, str(self.target_color), "color"),
        }

        # モードごとのアノテーションデータ保存パス
        self.download_paths = {
            "monochro": os.path.join(self.download_dir, str(self.target_color), "monochro"),
            "color": os.path.join(self.download_dir, str(self.target_color), "color"),
        }

    def _backup(self, source_paths, backup_root, subfolder, color_folder=True):
        """
        共通のバックアップ処理
        source_paths: モードごとのコピー元パス辞書
        backup_root: バックアップのルートディレクトリ
        subfolder: コピー先の末尾パス（例："train"）
        color_folder:色番のフォルダを作成するかどうか
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if color_folder:
            backup_base_dir = os.path.join(backup_root, str(self.target_color), timestamp)
        else:
            backup_base_dir = os.path.join(backup_root, timestamp)

        for mode, src_dir in source_paths.items():
            dst_dir = os.path.join(backup_base_dir, mode, subfolder)
            if os.path.exists(src_dir):
                shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
                print(f"Copied from {src_dir} to {dst_dir}")
            else:
                print(f"Source directory {src_dir} does not exist.")

    def backup_dataset(self):
        """学習データのバックアップ作成"""
        self._backup(self.mode_paths, os.path.join(self.backup_dir, "dataset"), "train")

    def backup_model(self):
        """モデルファイルのバックアップ作成"""
        self._backup(self.model_paths, os.path.join(self.backup_dir, "model"), "")

    def backup_annotated_data(self):
        """アノテーションデータのバックアップ作成"""
        self._backup(
            self.download_paths,
            os.path.join(self.backup_dir, "download", self.cfg.common.mode),
            "",
            color_folder=False,
        )

    def accumulate_pool(self, mode: str, kind: str = "good"):
        """download/<mode>/<color>/<kind>/ → pool/<color>/<mode>/<kind>_pool/ へ差分コピー。

        kind: "good" or "defect"
        ディレクトリ構成:
            pool/<color>/color/good_pool/      (color 良品)
            pool/<color>/color/defect_pool/    (color 欠陥)
            pool/<color>/monochro/good_pool/   (monochro 良品)
            pool/<color>/monochro/defect_pool/ (monochro 欠陥)
        pool は永続層のため既存ファイルはスキップ (差分追加のみ)。
        """
        if mode not in ("color", "monochro"):
            return  # 他 mode は pool 未使用
        color = str(self.target_color)
        src_dir = os.path.join(self.cfg.common.download_dir, color, mode, kind)
        pool_dir = os.path.join(self.cfg.common.pool_base, color, mode, f"{kind}_pool")
        os.makedirs(pool_dir, exist_ok=True)
        if not os.path.isdir(src_dir):
            print(f"⚠️ {src_dir} が存在しません (skip)")
            return
        added = 0
        for f in os.listdir(src_dir):
            if not f.lower().endswith(('.bmp', '.png', '.jpg', '.jpeg', '.tiff')):
                continue
            src = os.path.join(src_dir, f)
            dst = os.path.join(pool_dir, f)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                added += 1
        print(f"✅ {mode}/{kind}: {added} 件を pool に追加 ({pool_dir})")

    def stage_defect(self, mode: str = "color"):
        """download/<mode>/<color>/defect/ → defect_staging[_<mode>]/<color>/ へ振り分け。

        - color:    defect_staging/<color>/
        - monochro: defect_staging_monochro/<color>/

        clear_before_download が True なら staging をクリアしてから追加 (デフォルト false)。
        """
        if mode not in ("color", "monochro"):
            return
        color = str(self.target_color)
        src_dir = os.path.join(self.cfg.common.download_dir, color, mode, "defect")
        if mode == "color":
            ds_cfg = self.cfg.color.defect_staging
        else:
            ds_cfg = self.cfg.monochro.defect_staging
        staging_dir = os.path.join(self.cfg.common.staging_dir, color, mode)
        os.makedirs(staging_dir, exist_ok=True)
        if not os.path.isdir(src_dir):
            print(f"⚠️ {src_dir} が存在しません (defect なしで続行)")
            return
        clear_flag = ds_cfg.get("clear_before_download", False)
        if clear_flag:
            shutil.rmtree(staging_dir, ignore_errors=True)
            os.makedirs(staging_dir, exist_ok=True)
        added = 0
        for f in os.listdir(src_dir):
            if not f.lower().endswith(('.bmp', '.png', '.jpg', '.jpeg', '.tiff')):
                continue
            src = os.path.join(src_dir, f)
            dst = os.path.join(staging_dir, f)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                added += 1
        print(f"✅ {mode} defect_staging: {added} 件を投入 ({staging_dir})")

    @staticmethod
    def _copy_if_new(image_array, dst_path):
        """OpenCV 画像配列を dst_path に書き込み (既存はスキップ)"""
        if not os.path.exists(dst_path):
            cv2.imwrite(dst_path, image_array)

    def process_annotated_images(self, modes=("monochro", "color")):
        """ダウンロード済み画像を前処理し、mode 別に pool/staging へ振り分け。

        - monochro/good   → pool/{color}/monochro/good_pool/   (差分追加)
        - monochro/defect → defect_staging_monochro/{color}/   (人手ゲート待ち)
        - color/good      → pool/{color}/color/good_pool/      (差分追加)
        - color/defect    → defect_staging/{color}/            (人手ゲート待ち)

        Args:
            modes: 処理対象 mode の iterable (既定 monochro+color)。
                   特定 mode のみ前処理したい場合に絞り込む (例: ("monochro",))。
        """
        color = str(self.target_color)

        for mode in modes:
            img_h, img_w = self.image_sizes[mode]
            if mode == "color":
                ds_cfg = self.cfg.color.defect_staging
            else:
                ds_cfg = self.cfg.monochro.defect_staging

            pool_good = os.path.join(self.cfg.common.pool_base, color, mode, "good_pool")
            staging = os.path.join(self.cfg.common.staging_dir, color, mode)
            os.makedirs(pool_good, exist_ok=True)
            os.makedirs(staging, exist_ok=True)

            base_dir = os.path.join(self.download_dir, color, mode)
            auto_split = ds_cfg.get("auto_split_halves", True)

            # good: 前処理 → pool に差分追加
            for root, dirs, files in os.walk(base_dir):
                parts = root.split(os.path.sep)
                if "good" in parts or "auto_good" in parts:
                    for f in files:
                        if not f.lower().endswith(('.bmp', '.png', '.jpg', '.jpeg', '.tiff')):
                            continue
                        p = os.path.join(root, f)
                        # 1 枚の破損 (0 byte / decode 失敗) で色番全体が落ちないよう個別捕捉してスキップ
                        try:
                            image_data = load_image_as_byte_array(p)
                            top, bottom, _ = process_image(image_data, img_w, img_h, mode)
                        except Exception as e:  # noqa: BLE001
                            print(f"⚠ [{mode}/good] スキップ {os.path.basename(p)}: {type(e).__name__}: {e}", flush=True)
                            continue
                        name, ext = os.path.splitext(os.path.basename(p))
                        self._copy_if_new(top, os.path.join(pool_good, f"{name}_0{ext}"))
                        self._copy_if_new(bottom, os.path.join(pool_good, f"{name}_1{ext}"))

            # defect: 前処理 → staging に追加 (auto_split_halves で分岐)
            clear_flag = ds_cfg.get("clear_before_download", False)
            if clear_flag:
                shutil.rmtree(staging, ignore_errors=True)
                os.makedirs(staging, exist_ok=True)
            for root, dirs, files in os.walk(base_dir):
                parts = root.split(os.path.sep)
                if "defect" in parts:
                    for f in files:
                        if not f.lower().endswith(('.bmp', '.png', '.jpg', '.jpeg', '.tiff')):
                            continue
                        p = os.path.join(root, f)
                        if auto_split:
                            try:
                                image_data = load_image_as_byte_array(p)
                                top, bottom, _ = process_image(image_data, img_w, img_h, mode)
                            except Exception as e:  # noqa: BLE001
                                print(f"⚠ [{mode}/defect] スキップ {os.path.basename(p)}: {type(e).__name__}: {e}", flush=True)
                                continue
                            name, ext = os.path.splitext(os.path.basename(p))
                            self._copy_if_new(top, os.path.join(staging, f"{name}_0{ext}"))
                            self._copy_if_new(bottom, os.path.join(staging, f"{name}_1{ext}"))
                        else:
                            dst = os.path.join(staging, f)
                            if not os.path.exists(dst):
                                shutil.copy2(p, dst)

            print(f"✅ {mode}: good→pool, defect→staging に振り分け完了")

    def split_pool_to_dataset(self, color: str, mode: str = "color"):
        """pool/{color}/{mode}/{good,defect}_pool/ → dataset/{color}/{mode}/{train,test}/* を生成。

        ディレクトリ構成 (color と monochro で対称):
            color:    pool/{color}/color/{good,defect}_pool/    → dataset/{color}/color/...
            monochro: pool/{color}/monochro/{good,defect}_pool/ → dataset/{color}/monochro/...

        utils.split_manager.split_pool_to_train_test を使って pool を train/test に振り分ける。
        既存の train/test データは保持し、pool のデータを差分追加する。

        Args:
            color: 色番号 (例: "841")
            mode: "color" or "monochro"
        Returns:
            dict: 振り分け結果 {'good_to_train', 'good_to_test', 'defect_to_train', 'defect_to_test', 'files'}
        """
        if mode not in ("color", "monochro"):
            raise ValueError(f"unknown mode: {mode}")

        good_pool = os.path.join(self.cfg.common.pool_base, str(color), mode, "good_pool")
        defect_pool = os.path.join(self.cfg.common.pool_base, str(color), mode, "defect_pool")
        dataset_path = os.path.join(self.cfg.common.dataset_path, str(color), mode)
        train_ratio = float(self.cfg[mode].get("pool_train_ratio", 0.7))
        seed = int(self.cfg.common.get("seed", 42))
        result = split_pool_to_train_test(
            defect_pool_path=defect_pool,
            good_pool_path=good_pool,
            dataset_path=dataset_path,
            train_ratio=train_ratio,
            seed=seed,
        )
        print(
            f"✅ {mode} split: {result['good_to_train']} good→train, "
            f"{result['good_to_test']} good→test, "
            f"{result['defect_to_train']} defect→train, "
            f"{result['defect_to_test']} defect→test"
        )
        return result


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

    def download_images(self):
        """検査PC にFTP接続し、アノテーション領域を走査して good/defect に振り分けてダウンロード。

        リモート階層: /cameraN_image/annotated_data/{color}/{year}/{month}/{day}/{PR_id}/{kind}/
        ローカル:     {download_dir}/{color}/{mode}/{good|defect}/<PC名>_<YYYYMMDD>_<kind>_<元名>
        """
        mode = self.cfg.common.mode
        target_color = str(self.cfg.common.target_color)

        if mode == "monochro":
            port = self.monochro_port
            remote_root = "/camera1_image/annotated_data"
        elif mode == "color":
            port = self.color_port
            remote_root = "/camera2_image/annotated_data"
        else:
            print(f"⚠ 未対応モード: {mode}")
            return

        local_good = os.path.join(
            self.cfg.common.download_dir, target_color, mode, "good"
        )
        local_defect = os.path.join(
            self.cfg.common.download_dir, target_color, mode, "defect"
        )
        os.makedirs(local_good, exist_ok=True)
        os.makedirs(local_defect, exist_ok=True)

        ftp = FTP()
        ftp.encoding = "utf-8"
        try:
            ftp.connect(self.host, port, timeout=10)
            ftp.login(user=self.username, passwd=self.password)
            downloader = AnnotationDownloader(
                ftp=ftp,
                remote_root=remote_root,
                target_color=target_color,
                local_good=local_good,
                local_defect=local_defect,
                pc_name=self.name,
            )
            result = downloader.download()
            print(
                f"📥 [{self.name}/{mode}] downloaded={result['downloaded']}, "
                f"skipped={result['skipped']}, errors={result['errors']}, "
                f"unknown_kinds={sorted(result['unknown_kinds'])}"
            )
        except Exception as e:
            print(f"⚠ [{self.name}/{mode}] 取得失敗 (skip): {e}")
        finally:
            try:
                ftp.quit()
            except Exception:
                pass


class MultiFTPManager:
    """複数検査PCへの一括FTP操作"""
    def __init__(self, cfg):
        self.cfg = cfg
        self.managers = [
            FTPManager(cfg, host_cfg)
            for host_cfg in cfg.common.ftp_hosts
        ]

    def download_images(self):
        # rmtree 廃止: AnnotationDownloader の差分ダウンロード (size+MDTM) を活かす。
        # ファイル名は <PC名>_<YYYYMMDD>_<kind>_<元名> でユニーク化されるため、
        # 複数 PC からのマージで衝突しない (同一画像なら上書きしても無害)。
        for mgr in self.managers:
            try:
                print(f"📥 [{mgr.name}] からダウンロード中...")
                mgr.download_images()
                print(f"✅ [{mgr.name}] ダウンロード完了")
            except Exception as e:
                print(f"⚠ [{mgr.name}] からのダウンロード失敗（スキップ）: {e}")


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
