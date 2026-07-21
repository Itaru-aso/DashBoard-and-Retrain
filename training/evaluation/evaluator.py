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
