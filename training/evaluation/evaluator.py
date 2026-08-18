# training/evaluation/evaluator.py
"""evaluationステージ: 学習済みモデルの test-set オフライン評価。"""
import json
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

    @staticmethod
    def _load_deployed_threshold(para_path):
        """`para.json` の `threshold`（ONNXに焼かれ実機へ配信される閾値）を返す。

        Args:
            para_path: para.json のパス。

        Returns:
            float | None: 取得できた閾値。読めない・数値でない場合は None。
        """
        try:
            with open(para_path, 'r', encoding='utf-8') as f:
                para = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        value = para.get('threshold')
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def evaluate(self):
        """評価を実行してメトリクスを返す。

        指標は **`para.json` の `threshold`（＝実機へ配信される閾値）** で算出する。
        同一データ上で F1 を最大化する後付け閾値は、評価対象そのものにフィットする
        ため楽観的に偏る（配信される挙動を表さない）。そのため `ref_f1_optimal_*`
        として参考値のみ併記し、主指標には使わない。

        Returns:
            dict: AUC, F1, miss_rate, false_alarm_rate 等を含む dict。
                  `threshold_from_para` は配信閾値を使えたかの指標（1.0/0.0）。
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

            deployed_threshold = self._load_deployed_threshold(para_path)
            if deployed_threshold is None:
                print(
                    f"⚠️ para.json に有効な threshold がありません: {para_path}"
                    "（同一データでのF1最大化閾値で代替します。楽観的に偏るため参考値扱い）"
                )
                threshold = find_optimal_threshold(scores_good, scores_defect)
                threshold_from_para = 0.0
            else:
                threshold = deployed_threshold
                threshold_from_para = 1.0

            metrics = compute_metrics(scores_good, scores_defect, threshold)
            metrics['threshold_from_para'] = threshold_from_para

            # 参考値: 同一データ上でF1を最大化する後付け閾値（配信判断には使わない）。
            ref_threshold = find_optimal_threshold(scores_good, scores_defect)
            ref_metrics = compute_metrics(scores_good, scores_defect, ref_threshold)
            metrics['ref_f1_optimal_threshold'] = ref_threshold
            metrics['ref_f1_optimal_F1'] = ref_metrics.get('F1', 0.0)

            source = '配信閾値' if threshold_from_para else 'F1最大化(代替)'
            print(
                f"[{self.mode}] 評価結果: AUC={metrics.get('AUC', 0.0):.4f}, "
                f"false_alarm_rate={metrics.get('false_alarm_rate', 0.0):.4f}, "
                f"miss_rate={metrics.get('miss_rate', 0.0):.4f}, "
                f"F1={metrics.get('F1', 0.0):.4f} "
                f"(閾値={threshold:.6f} / {source})"
            )
            print(
                f"[{self.mode}] 参考(同一データでのF1最大化・楽観バイアスあり): "
                f"閾値={ref_threshold:.6f}, F1={ref_metrics.get('F1', 0.0):.4f}"
            )
            if self.mgr is not None:
                self.mgr.log_metrics(metrics)
            return metrics
        except Exception as e:
            print(f"⚠️ 評価エラー: {e}")
            return None
