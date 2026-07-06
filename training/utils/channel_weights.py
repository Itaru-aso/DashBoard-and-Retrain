#!/usr/bin/python
# -*- coding: utf-8 -*-
"""チャネル重み計算モジュール

- defectフォルダあり → 教師あり方式 (pAUC max_fpr=0.05, power=5)
- defectフォルダなし → 教師なし方式 (逆CV power=3)
"""
import math
import os
import torch
import numpy as np
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from PIL import Image
from tqdm import tqdm
from sklearn.metrics import roc_auc_score

from utils.common import ImageFolderWithPath

out_channels = 384


class _FlatImageFolder(Dataset):
    """フラットなフォルダ（サブフォルダなし）から画像を読み込む"""
    EXTENSIONS = ('.bmp', '.png', '.jpg', '.jpeg', '.tiff')

    def __init__(self, root, transform=None):
        self.root = root
        self.transform = transform
        self.samples = sorted([
            os.path.join(root, f) for f in os.listdir(root)
            if f.lower().endswith(self.EXTENSIONS)
        ])

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        path = self.samples[index]
        image = Image.open(path).convert('RGB')
        if self.transform:
            image = self.transform(image)
        return image, 0, path


def _make_dataset(dataset_path, transform):
    """サブフォルダ構造があればImageFolderWithPath、なければ_FlatImageFolderを返す"""
    has_subdirs = any(
        os.path.isdir(os.path.join(dataset_path, d))
        for d in os.listdir(dataset_path)
    )
    if has_subdirs:
        return ImageFolderWithPath(dataset_path, transform=transform)
    else:
        return _FlatImageFolder(dataset_path, transform=transform)


def _collect_channel_max(teacher, student, teacher_mean, teacher_std,
                          dataset_path, device, batch_size=1):
    """データセットの各画像について、チャネルごとの最大差異値を収集する"""
    tf = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ])
    ds = _make_dataset(dataset_path, transform=tf)
    results = []
    with torch.no_grad():
        for image, _, path in ds:
            image = image.unsqueeze(0).to(device)
            t = teacher(image)
            t = (t - teacher_mean) / teacher_std
            s = student(image)
            diff = (t - s[:, :out_channels]) ** 2
            ch_max = diff.squeeze(0).amax(dim=[1, 2])  # [384]
            results.append(ch_max.cpu().numpy())
    return np.array(results)  # [N, 384]


def _collect_channel_max_from_dataset(teacher, student, teacher_mean, teacher_std,
                                      dataset, device):
    """変換済みテンソルを yield する dataset から、チャネルごとの最大差異を収集する。

    _collect_channel_max のパス版に対し、こちらは Dataset を直接受ける
    (例: RawShiftImageFolder で 1_download の生画像を shift=0 でクロップ済テンソル化したもの)。
    dataset の各要素は (image_tensor, ...) で、先頭がモデル入力テンソル (ToTensor+Normalize済) とする。
    """
    results = []
    with torch.no_grad():
        for item in dataset:
            image = item[0] if isinstance(item, (tuple, list)) else item
            image = image.unsqueeze(0).to(device)
            t = teacher(image)
            t = (t - teacher_mean) / teacher_std
            s = student(image)
            diff = (t - s[:, :out_channels]) ** 2
            ch_max = diff.squeeze(0).amax(dim=[1, 2])  # [384]
            results.append(ch_max.cpu().numpy())
    return np.array(results)  # [N, 384]


def compute_channel_weights_supervised(good_scores_or_teacher, defect_scores_or_student,
                                        teacher_mean_or_good_path=None, teacher_std_or_defect_path=None,
                                        good_path_or_device=None, defect_path=None,
                                        device=None, power=5, *, max_fpr=0.05):
    """教師あり方式: pAUC (partial AUC, McClish 正規化) に基づくチャネル重み計算

    2つの呼び出し形式をサポート:

    形式1 (numpy配列): compute_channel_weights_supervised(good_scores, defect_scores, power=N)
        - good_scores: [N_good, 384] numpy array
        - defect_scores: [N_defect, 384] numpy array

    形式2 (モデル): compute_channel_weights_supervised(teacher, student, teacher_mean, teacher_std,
                                                         good_path, defect_path, device, power=N)

    Returns:
        weights: [384] numpy array (合計1に正規化済み)
        ch_aucs: [384] numpy array (各チャネルのpAUC。フィールド名は後方互換のため ch_aucs)
    """
    # 形式1: numpy配列で直接渡す場合 (good_scores_or_teacher が ndarray)
    if isinstance(good_scores_or_teacher, np.ndarray):
        good_ch = good_scores_or_teacher
        defect_ch = defect_scores_or_student
        # powerは teacher_mean_or_good_path に入る場合がある
        if isinstance(teacher_mean_or_good_path, int):
            power = teacher_mean_or_good_path
        return _compute_supervised_from_scores(good_ch, defect_ch, power, max_fpr=max_fpr)

    # 形式2: モデルを渡す場合
    teacher = good_scores_or_teacher
    student = defect_scores_or_student
    teacher_mean = teacher_mean_or_good_path
    teacher_std = teacher_std_or_defect_path
    good_path = good_path_or_device
    # defect_path, device, power はそのまま使用

    print('チャネル重み計算 (教師あり方式: pAUC max_fpr={}, power={})'.format(max_fpr, power))
    good_ch = _collect_channel_max(teacher, student, teacher_mean, teacher_std,
                                    good_path, device)
    defect_ch = _collect_channel_max(teacher, student, teacher_mean, teacher_std,
                                      defect_path, device)
    return _compute_supervised_from_scores(good_ch, defect_ch, power, max_fpr=max_fpr)


def _compute_supervised_from_scores(good_ch, defect_ch, power=5, max_fpr=0.05):
    """numpy スコア配列から教師あり (pAUC ベース) 重みを計算する内部実装。

    Args:
        good_ch: [N_good, 384] numpy array
        defect_ch: [N_defect, 384] numpy array
        power: 重み計算の冪乗 (clip(pAUC - 0.5, 0)^power)
        max_fpr: ROC で評価する FPR 上限 (default 0.05 = 5%)。
                 sklearn の roc_auc_score(max_fpr=...) は McClish 正規化済
                 (random=0.5, perfect=1.0) を返すため、baseline は 0.5 のまま。
    """
    labels = np.array([0] * len(good_ch) + [1] * len(defect_ch))
    all_ch = np.concatenate([good_ch, defect_ch], axis=0)

    n_ch = good_ch.shape[1]
    ch_aucs = np.zeros(n_ch)  # 中身は pAUC (フィールド名は後方互換のため維持)
    for c in range(n_ch):
        ch_aucs[c] = roc_auc_score(labels, all_ch[:, c], max_fpr=max_fpr)

    weights = np.clip(ch_aucs - 0.5, 0, None) ** power
    # pAUC は McClish 正規化で値域が AUC よりタイトなため (pAUC-0.5)^power の
    # raw_sum が極小になりうる。旧 `/(sum+1e-8)` は floor が支配的になり sum≠1
    # となるため、明示的に sum>0 判定し degenerate 時は一様分布にフォールバック。
    weight_sum = weights.sum()
    if weight_sum > 0:
        weights = weights / weight_sum
    else:
        weights = np.full(n_ch, 1.0 / n_ch)

    n_effective = np.sum(weights > 1e-6)
    print(f'  有効チャネル: {n_effective}/{n_ch}')
    print(f'  上位10chの重み合計: {np.sum(np.sort(weights)[-10:]):.4f}')

    return weights, ch_aucs


def compute_channel_weights_unsupervised(teacher_or_scores, student_or_power=None,
                                          teacher_mean=None, teacher_std=None,
                                          good_path=None, device=None, power=3):
    """教師なし方式: 正常画像の変動係数(CV)の逆数に基づくチャネル重み計算

    2つの呼び出し形式をサポート:

    形式1 (numpy配列): compute_channel_weights_unsupervised(good_scores, power=N)
        - good_scores: [N_good, 384] numpy array

    形式2 (モデル): compute_channel_weights_unsupervised(teacher, student, teacher_mean,
                                                           teacher_std, good_path, device, power=N)

    Returns:
        weights: [384] numpy array (合計1に正規化済み)
    """
    # 形式1: numpy配列で直接渡す場合
    if isinstance(teacher_or_scores, np.ndarray):
        good_ch = teacher_or_scores
        if isinstance(student_or_power, int):
            power = student_or_power
        return _compute_unsupervised_from_scores(good_ch, power)

    # 形式2: モデルを渡す場合
    teacher = teacher_or_scores
    student = student_or_power

    print('チャネル重み計算 (教師なし方式: 逆CV power={})'.format(power))
    good_ch = _collect_channel_max(teacher, student, teacher_mean, teacher_std,
                                    good_path, device)
    return _compute_unsupervised_from_scores(good_ch, power)


def _compute_unsupervised_from_scores(good_ch, power=3):
    """numpy スコア配列から教師なし重みを計算する内部実装"""
    good_mean = good_ch.mean(axis=0)  # [C]
    good_std = good_ch.std(axis=0)    # [C]
    good_cv = good_std / (good_mean + 1e-8)  # 変動係数

    weights = 1.0 / (good_cv ** power + 1e-8)
    weights = weights / (weights.sum() + 1e-8)

    n_ch = good_ch.shape[1]
    n_effective = np.sum(weights > 1e-6)
    print(f'  有効チャネル: {n_effective}/{n_ch}')
    print(f'  上位10chの重み合計: {np.sum(np.sort(weights)[-10:]):.4f}')

    return weights


def compute_channel_weights(teacher, student, teacher_mean, teacher_std,
                             test_path, device,
                             supervised_power=5, unsupervised_power=3,
                             blend_n_mid=30, blend_scale=10.0,
                             max_fpr=0.05,
                             good_dataset=None, defect_path=None):
    """テストデータの defect 枚数に応じて supervised / unsupervised を sigmoid blend する。

    挙動:
      - defect=0   → unsupervised 100% (早期 return、後方互換)
      - defect>=1 → blend (sigmoid で連続混合)
                    w_sup(N) = 1 / (1 + exp(-(N - blend_n_mid) / blend_scale))
                    weights  = w_sup * sup_w + (1-w_sup) * unsup_w

    Args:
        test_path: テストデータのルートパス (例: ./4_dataset/841/color/test)
                   配下に good/ と (任意で) defect/ フォルダがある想定
        blend_n_mid: 50/50 ブレンドになる defect 枚数 (cfg.channel_weights.blend_n_mid)
        blend_scale: sigmoid の遷移急峻さ (cfg.channel_weights.blend_scale)
        max_fpr: pAUC で見る FPR 上限 (cfg.channel_weights.max_fpr, default 0.05)

    Returns:
        weights: [384] numpy array (合計1に正規化済み)
        method: 'unsupervised' (defect=0) or 'blended' (defect>=1)
        ch_aucs: [384] numpy array (blended のみ、unsupervised は None)
        w_sup: float (sigmoid 値、unsupervised は 0.0)
    """
    if blend_n_mid <= 0:
        raise ValueError("blend_n_mid must be positive")
    if blend_scale <= 0:
        raise ValueError("blend_scale must be positive")

    # good: good_dataset(変換済テンソルを yield) が与えられればそれを優先 (A2: 1_download 由来)。
    #       未指定なら従来どおり test_path/good から収集 (color はこちら)。
    # defect: defect_path 明示があればそれ、未指定なら test_path/defect。
    if defect_path is None:
        defect_path = os.path.join(test_path, 'defect')

    if good_dataset is not None:
        good_ch = _collect_channel_max_from_dataset(
            teacher, student, teacher_mean, teacher_std, good_dataset, device)
    else:
        good_path = os.path.join(test_path, 'good')
        if not os.path.isdir(good_path):
            raise FileNotFoundError(f'goodフォルダが見つかりません: {good_path}')
        good_ch = _collect_channel_max(teacher, student, teacher_mean, teacher_std,
                                       good_path, device)

    n_defect = _count_defect_images(defect_path)

    if n_defect == 0:
        print('defect=0 → unsupervised 100% (後方互換)')
        weights = _compute_unsupervised_from_scores(good_ch, unsupervised_power)
        return weights, 'unsupervised', None, 0.0

    defect_ch = _collect_channel_max(teacher, student, teacher_mean, teacher_std,
                                      defect_path, device)
    sup_w, ch_aucs = _compute_supervised_from_scores(
        good_ch, defect_ch, supervised_power, max_fpr=max_fpr
    )
    unsup_w = _compute_unsupervised_from_scores(good_ch, unsupervised_power)
    weights, w_sup = _blend_weights(sup_w, unsup_w, n_defect, blend_n_mid, blend_scale)

    print(f'channel weights: blend (n_defect={n_defect}, w_sup={w_sup:.4f}, '
          f'n_mid={blend_n_mid}, scale={blend_scale}, max_fpr={max_fpr})')
    return weights, 'blended', ch_aucs, w_sup


def _count_defect_images(defect_path):
    """defect ディレクトリ配下を再帰 walk で画像枚数 count。

    存在しない or ディレクトリでない場合は 0 を返す。
    対応拡張子: .bmp / .png / .jpg / .jpeg / .tiff (大文字小文字両方)。
    """
    if not os.path.isdir(defect_path):
        return 0
    extensions = ('.bmp', '.png', '.jpg', '.jpeg', '.tiff')
    count = 0
    for root, _, files in os.walk(defect_path):
        count += sum(1 for f in files if f.lower().endswith(extensions))
    return count


def _blend_weights(sup_w, unsup_w, n_defect, n_mid, scale):
    """sigmoid blend: defect 数に応じて supervised と unsupervised を混合。

    Args:
        sup_w: [out_channels] numpy array (supervised 重み、pAUC ベース)
        unsup_w: [out_channels] numpy array (unsupervised 重み、逆 CV ベース)
        n_defect: int (実際の defect 枚数、test/defect 配下を count した値)
        n_mid: int (sigmoid 中点、cfg.channel_weights.blend_n_mid)
        scale: float (sigmoid の遷移急峻さ、cfg.channel_weights.blend_scale)

    Returns:
        weights: [out_channels] numpy array (合計1に正規化済み)
        w_sup: float (sigmoid 値、説明可能性のため返す)
    """
    w_sup = 1.0 / (1.0 + math.exp(-(n_defect - n_mid) / scale))
    weights = w_sup * sup_w + (1.0 - w_sup) * unsup_w
    weights = weights / (weights.sum() + 1e-8)
    return weights, w_sup
