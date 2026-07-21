"""統一評価パイプライン

モデルロード → 推論 → スコア算出 → FP/FN判定 → メトリクス集約 を一括で行う。
"""
import json
import os

import numpy as np
import torch
from sklearn.metrics import roc_auc_score
from torchvision import transforms
from tqdm import tqdm

from utils.common import get_pdn_small, get_autoencoder
from utils.scoring_transform import compute_anomaly_score
from utils.split_manager import load_split

out_channels = 384


def compute_metrics(scores_good, scores_defect, threshold):
    """スコア列と閾値からメトリクスを計算する。

    Args:
        scores_good: 正常画像のスコアリスト
        scores_defect: 異常画像のスコアリスト
        threshold: 判定閾値 (score >= threshold → defect)

    Returns:
        dict: FP, FN, TP, TN, AUC, miss_rate, false_alarm_rate, threshold, F1
    """
    total_good = len(scores_good)
    total_defect = len(scores_defect)

    FP = sum(1 for s in scores_good if s >= threshold)
    TN = total_good - FP
    FN = sum(1 for s in scores_defect if s < threshold)
    TP = total_defect - FN

    miss_rate = FN / total_defect if total_defect > 0 else 0.0
    false_alarm_rate = FP / total_good if total_good > 0 else 0.0

    # F1
    precision = TP / (TP + FP) if (TP + FP) > 0 else 0.0
    recall = TP / (TP + FN) if (TP + FN) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # AUC
    labels = [0] * total_good + [1] * total_defect
    scores = list(scores_good) + list(scores_defect)
    auc = roc_auc_score(labels, scores) if total_good > 0 and total_defect > 0 else 0.0

    return {
        'FP': FP, 'FN': FN, 'TP': TP, 'TN': TN,
        'AUC': auc, 'F1': f1,
        'miss_rate': miss_rate, 'false_alarm_rate': false_alarm_rate,
        'threshold': threshold,
        'n_good': total_good, 'n_defect': total_defect,
    }


def find_optimal_threshold(scores_good, scores_defect, n_steps=1000):
    """F1 スコアを最大化する閾値を探索する。

    Args:
        scores_good: 正常画像のスコアリスト
        scores_defect: 異常画像のスコアリスト
        n_steps: 探索グリッドの分割数

    Returns:
        float: F1 最大化閾値
    """
    all_scores = sorted(set(scores_good + scores_defect))
    if len(all_scores) <= 1:
        return all_scores[0] if all_scores else 0.0

    lo, hi = min(all_scores), max(all_scores)
    candidates = np.linspace(lo, hi, n_steps)

    best_f1 = -1.0
    best_threshold = lo
    for t in candidates:
        m = compute_metrics(scores_good, scores_defect, t)
        if m['F1'] > best_f1:
            best_f1 = m['F1']
            best_threshold = t

    return float(best_threshold)


def find_threshold_for_fpr(scores_good, scores_defect, target_fpr):
    """false alarm rate (FPR) が target_fpr 以下になる最小の閾値を返す。

    閾値を下げると recall が増えるが FPR も増える。target_fpr の制約を
    満たしつつ recall を最大化したいので、「FPR ≤ target_fpr を満たす中で
    最も低い閾値」を返す。

    Args:
        scores_good: 正常画像のスコアリスト
        scores_defect: 異常画像のスコアリスト
        target_fpr: 許容 false alarm rate (例: 0.03)

    Returns:
        (threshold, achieved_fpr): 採用した閾値と実測 FPR
    """
    good = sorted(scores_good, reverse=True)  # 高い順
    n = len(good)
    if n == 0:
        # good が無ければ FPR は常に 0
        thr = max(scores_defect) + 1.0 if scores_defect else 0.0
        return float(thr), 0.0

    # FPR = (good 中 score >= threshold な個数) / n
    # target_fpr を満たす最大の FP 数 k_max を計算
    k_max = int(target_fpr * n)
    if k_max == 0:
        # FPR=0 を要求: threshold > max(good) にすれば good 一切超えない
        thr = max(good) + 1e-9
    else:
        if k_max >= n:
            thr = min(good) - 1e-9  # 全部許容
        elif good[k_max - 1] == good[k_max]:
            # 境界に同値タイ: 中点だと FP が k_max を超えてしまうので、
            # 同値より厳密に上にずらして保守側 (FP < k_max) に倒す
            thr = good[k_max - 1] + 1e-9
        else:
            # k_max 番目の good score と k_max+1 番目の good score の中点に閾値を置けば
            # FP = k_max 個丁度になる (>= threshold で k_max 個カウント)
            thr = (good[k_max - 1] + good[k_max]) / 2.0

    # 実測 FPR を確認
    fp = sum(1 for s in scores_good if s >= thr)
    achieved_fpr = fp / n
    return float(thr), float(achieved_fpr)


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


def evaluate_model(model_dir, split_path, dataset_path,
                   st_para=1.0, ae_para=0.0, threshold=None, device='cpu'):
    """モデルを split に基づいて評価し、メトリクスを返す。

    Args:
        model_dir: モデルファイルのディレクトリ
        split_path: test_val_split.json のパス
        dataset_path: データセットルート
        st_para: map_st の重み (デフォルト 1.0, AE無効)
        ae_para: map_ae の重み (デフォルト 0.0, AE無効)
        threshold: 判定閾値。None の場合は F1最大化で自動決定
        device: 推論デバイス

    Returns:
        dict: val_metrics, test_metrics, scores, threshold
    """
    split = load_split(split_path)
    model_dict = load_model(model_dir, device=device)

    good_dir = os.path.join(dataset_path, 'test', 'good', 'images')
    defect_dir = os.path.join(dataset_path, 'test', 'defect', 'images')

    # val スコア算出
    val_good_scores = score_images(model_dict, good_dir, split['val_good_files'],
                                    st_para=st_para, ae_para=ae_para, device=device)
    val_defect_scores = score_images(model_dict, defect_dir, split['val_defect_files'],
                                      st_para=st_para, ae_para=ae_para, device=device)

    # test スコア算出
    test_good_scores = score_images(model_dict, good_dir, split['test_good_files'],
                                     st_para=st_para, ae_para=ae_para, device=device)
    test_defect_scores = score_images(model_dict, defect_dir, split['test_defect_files'],
                                       st_para=st_para, ae_para=ae_para, device=device)

    val_good_list = list(val_good_scores.values())
    val_defect_list = list(val_defect_scores.values())
    test_good_list = list(test_good_scores.values())
    test_defect_list = list(test_defect_scores.values())

    # 閾値決定 (val から)
    if threshold is None:
        threshold = find_optimal_threshold(val_good_list, val_defect_list)

    val_metrics = compute_metrics(val_good_list, val_defect_list, threshold)
    test_metrics = compute_metrics(test_good_list, test_defect_list, threshold)

    return {
        'val_metrics': val_metrics,
        'test_metrics': test_metrics,
        'threshold': threshold,
        'scores': {
            'val_good': val_good_scores,
            'val_defect': val_defect_scores,
            'test_good': test_good_scores,
            'test_defect': test_defect_scores,
        },
        'config': {
            'model_dir': model_dir,
            'st_para': st_para,
            'ae_para': ae_para,
            'channel_weights': model_dict['channel_weights'] is not None,
        },
    }
