"""val/test 分割の作成・読み込み・管理モジュール"""
import json
import os
import random
from collections import defaultdict


def create_split(dataset_path, seed=42, val_ratio=1/3, k_folds=5):
    """データセットを val/test に分割し、test/good の K-fold CV も作成する。

    Args:
        dataset_path: データセットルート（配下に test/defect/images/, test/good/images/）
        seed: 乱数シード
        val_ratio: defect の val 割合（デフォルト 1/3 ≈ 1:2 分割）
        k_folds: test/good の CV fold 数

    Returns:
        dict: val_defect_files, test_defect_files, val_good_files, test_good_files, cv_folds
    """
    defect_dir = os.path.join(dataset_path, 'test', 'defect', 'images')
    good_dir = os.path.join(dataset_path, 'test', 'good', 'images')

    # defect 画像を製品ID単位でグルーピング
    defect_files = _list_images(defect_dir)
    defect_groups = _group_by_product_id(defect_files)

    # 製品ID単位で val/test に分割
    group_ids = sorted(defect_groups.keys())
    rng = random.Random(seed)
    rng.shuffle(group_ids)

    n_val_groups = max(1, round(len(group_ids) * val_ratio))
    val_group_ids = set(group_ids[:n_val_groups])

    val_defect = []
    test_defect = []
    for gid in sorted(defect_groups.keys()):
        if gid in val_group_ids:
            val_defect.extend(sorted(defect_groups[gid]))
        else:
            test_defect.extend(sorted(defect_groups[gid]))

    # good 画像を分割 (同じ seed で再現可能)
    good_files = sorted(_list_images(good_dir))
    rng_good = random.Random(seed)
    good_shuffled = good_files[:]
    rng_good.shuffle(good_shuffled)

    n_val_good = max(1, round(len(good_shuffled) * val_ratio))
    val_good = sorted(good_shuffled[:n_val_good])
    test_good = sorted(good_shuffled[n_val_good:])

    # K-fold CV (test/good のみ)
    cv_folds = _create_kfold(test_good, k_folds, seed)

    return {
        'val_defect_files': val_defect,
        'test_defect_files': test_defect,
        'val_good_files': val_good,
        'test_good_files': test_good,
        'cv_folds': cv_folds,
        'seed': seed,
        'val_ratio': val_ratio,
        'k_folds': k_folds,
    }


def save_split(split_dict, split_path):
    """分割結果を JSON ファイルに保存する"""
    os.makedirs(os.path.dirname(split_path), exist_ok=True)
    with open(split_path, 'w', encoding='utf-8') as f:
        json.dump(split_dict, f, ensure_ascii=False, indent=2)


def load_split(split_path):
    """JSON ファイルから分割結果を読み込む"""
    with open(split_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def split_pool_to_train_test(defect_pool_path, good_pool_path, dataset_path,
                             train_ratio=0.7, seed=42):
    """運用で蓄積した defect_pool/good_pool を train/test に振り分ける。

    既存の train/test データは保持し、pool のデータを追加する。

    Args:
        defect_pool_path: 蓄積された不良画像 (TP+FN) のディレクトリ
        good_pool_path: 蓄積された正常画像 (FP) のディレクトリ
        dataset_path: データセットルート (train/, test/ を含む)
        train_ratio: train に振り分ける割合 (デフォルト 0.7)
        seed: 乱数シード

    Returns:
        dict: 振り分け結果 (移動先パスとファイル数)
    """
    import shutil

    rng = random.Random(seed)
    result = {'defect_to_train': 0, 'defect_to_test': 0,
              'good_to_train': 0, 'good_to_test': 0, 'files': []}

    # defect_pool → train/defect + test/defect/images
    train_defect_dir = os.path.join(dataset_path, 'train', 'defect')
    test_defect_dir = os.path.join(dataset_path, 'test', 'defect', 'images')
    os.makedirs(train_defect_dir, exist_ok=True)
    os.makedirs(test_defect_dir, exist_ok=True)

    defect_files = _list_images(defect_pool_path) if os.path.isdir(defect_pool_path) else []
    defect_groups = _group_by_product_id(defect_files)
    group_ids = sorted(defect_groups.keys())
    rng.shuffle(group_ids)
    n_train_groups = max(1, round(len(group_ids) * train_ratio)) if group_ids else 0
    train_group_ids = set(group_ids[:n_train_groups])

    for gid, files in defect_groups.items():
        dest_dir = train_defect_dir if gid in train_group_ids else test_defect_dir
        for f in files:
            src = os.path.join(defect_pool_path, f)
            dst = os.path.join(dest_dir, f)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                if gid in train_group_ids:
                    result['defect_to_train'] += 1
                else:
                    result['defect_to_test'] += 1
                result['files'].append({'src': src, 'dst': dst})

    # good_pool → train/good + test/good/images
    train_good_dir = os.path.join(dataset_path, 'train', 'good')
    test_good_dir = os.path.join(dataset_path, 'test', 'good', 'images')
    os.makedirs(train_good_dir, exist_ok=True)
    os.makedirs(test_good_dir, exist_ok=True)

    good_files = sorted(_list_images(good_pool_path)) if os.path.isdir(good_pool_path) else []
    rng_good = random.Random(seed)
    rng_good.shuffle(good_files)
    n_train_good = max(1, round(len(good_files) * train_ratio)) if good_files else 0

    for i, f in enumerate(good_files):
        dest_dir = train_good_dir if i < n_train_good else test_good_dir
        src = os.path.join(good_pool_path, f)
        dst = os.path.join(dest_dir, f)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
            if i < n_train_good:
                result['good_to_train'] += 1
            else:
                result['good_to_test'] += 1
            result['files'].append({'src': src, 'dst': dst})

    return result


def _list_images(directory):
    """ディレクトリ内の画像ファイル名を返す"""
    extensions = ('.bmp', '.png', '.jpg', '.jpeg', '.tiff')
    if not os.path.isdir(directory):
        return []
    return [f for f in os.listdir(directory) if f.lower().endswith(extensions)]


def _extract_product_id(filename):
    """ファイル名から製品IDを抽出する。

    例: '10_0.bmp' → '10', '18 (1)_1.bmp' → '18 (1)', '12_1_0.bmp' → '12'
    最後の '_数字.拡張子' をカメラ面として除去し、残りをIDとする。
    """
    name = os.path.splitext(filename)[0]  # 拡張子除去
    # 末尾の _数字 を除去（カメラ面）
    parts = name.rsplit('_', 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return name


def _group_by_product_id(filenames):
    """ファイル名を製品ID単位でグルーピング"""
    groups = defaultdict(list)
    for f in filenames:
        pid = _extract_product_id(f)
        groups[pid].append(f)
    return dict(groups)


def _create_kfold(files, k, seed):
    """ファイルリストを K-fold に分割する"""
    rng = random.Random(seed + 1)  # 分割と異なるシードで独立性を確保
    shuffled = files[:]
    rng.shuffle(shuffled)

    folds = [[] for _ in range(k)]
    for i, f in enumerate(shuffled):
        folds[i % k].append(f)

    # 各 fold をソート
    return [sorted(fold) for fold in folds]
