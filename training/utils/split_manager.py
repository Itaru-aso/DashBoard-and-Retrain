"""val/test 分割の作成・読み込み・管理モジュール"""
import hashlib
import json
import os
import random
import re
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
    """運用で蓄積した defect_pool/good_pool を train/test に振り分け、dataset を pool に同期する。

    各撮像の行き先は撮像キーのハッシュで決まり、ほかの画像の有無に依存しない。pool が増えても
    既存撮像の側は変わらない。良品・不良で同じ規則を使うため、片面だけ不良の撮像も良品面と不良面が
    同じ側に入る。行き先と違う側にある画像と pool に無い画像は dataset から削除する（pool が無い・空の
    クラスは削除しない）。
    詳細は @.kiro/specs/retraining/pool-dataset-sync-split.md 決定1・2。

    Args:
        defect_pool_path: 蓄積された不良画像 (TP+FN) のディレクトリ
        good_pool_path: 蓄積された正常画像 (FP) のディレクトリ
        dataset_path: データセットルート (train/, test/ を含む)
        train_ratio: 撮像が train に入る確率 (デフォルト 0.7。件数は期待値でありちょうどではない)
        seed: ハッシュに混ぜるシード

    Returns:
        dict: 振り分け結果 (追加枚数・削除枚数 `removed`・追加したファイルの移動元/先)
    """
    import shutil

    result = {'defect_to_train': 0, 'defect_to_test': 0,
              'good_to_train': 0, 'good_to_test': 0, 'removed': 0, 'files': []}

    for pool_path, cls in ((defect_pool_path, 'defect'), (good_pool_path, 'good')):
        train_dir = os.path.join(dataset_path, 'train', cls)
        test_dir = os.path.join(dataset_path, 'test', cls, 'images')
        train_key, test_key = f'{cls}_to_train', f'{cls}_to_test'
        os.makedirs(train_dir, exist_ok=True)
        os.makedirs(test_dir, exist_ok=True)
        pool_files = set(_list_images(pool_path))
        if not pool_files:
            # pool が無い・空のクラスは dataset を空へ同期しない（パス誤り・dataset にだけある画像の保護）
            continue
        to_train = {f for f in pool_files if _is_train_capture(_capture_key(f), train_ratio, seed)}
        wanted = {train_dir: to_train, test_dir: pool_files - to_train}

        for dest_dir, files in wanted.items():
            for f in _list_images(dest_dir):
                if f not in files:
                    os.remove(os.path.join(dest_dir, f))
                    result['removed'] += 1
            count_key = train_key if dest_dir == train_dir else test_key
            for f in sorted(files):
                src = os.path.join(pool_path, f)
                dst = os.path.join(dest_dir, f)
                if not os.path.exists(dst):
                    shutil.copy2(src, dst)
                    result[count_key] += 1
                    result['files'].append({'src': src, 'dst': dst})

    return result


def _capture_key(filename):
    """撮像キー（`OK_`/`NG_` 接頭辞と末尾の面番号を除いた名前）を返す。

    接頭辞は検査時の AI 判定であり良否クラスではないため、同一撮像の良品面と不良面で異なり得る。
    """
    return _extract_product_id(re.sub(r'^(OK|NG)_', '', filename))


def _is_train_capture(capture_key, train_ratio, seed):
    """撮像キーと seed のハッシュを [0,1) に写し、train_ratio 未満なら train とする。"""
    digest = hashlib.md5(f'{seed}:{capture_key}'.encode('utf-8')).hexdigest()
    return int(digest, 16) / 16 ** len(digest) < train_ratio


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


def split_files_by_product(filenames, train_ratio, seed):
    """ファイル一覧を**撮像単位**で train / test(val) の2つに分割する。

    1回の撮影は top/bottom の2ファイル（`_0`/`_1`）に分かれるが、両者は同一製品・
    同一照明・同一瞬間に由来し強く相関する。片面を学習に、他面を較正や評価に使うと
    リークになるため、`_extract_product_id` でまとめた撮像単位で振り分ける。

    `split_pool_to_train_test` の良品側と `train.monochro` の tight train/val 分割の
    両方から呼ばれる共有ロジック。
    詳細は @.kiro/specs/retraining/eval-calibration-leak-fixes.md 決定3。

    Args:
        filenames: 対象ファイル名のリスト（同一ディレクトリ内の名前）。
        train_ratio: train 側へ振る撮像（製品ID）の比率。
        seed: シャッフルの seed（再現性用）。

    Returns:
        tuple[list[str], list[str]]: (train 側ファイル名, test 側ファイル名)。
            いずれもソート済み。同一 product_id のファイルは必ず同じ側に入る。
    """
    groups = _group_by_product_id(filenames)
    group_ids = sorted(groups.keys())
    rng = random.Random(seed)
    rng.shuffle(group_ids)
    n_train_groups = max(1, round(len(group_ids) * train_ratio)) if group_ids else 0
    train_group_ids = set(group_ids[:n_train_groups])

    train_files, test_files = [], []
    for gid in sorted(groups.keys()):
        dest = train_files if gid in train_group_ids else test_files
        dest.extend(groups[gid])
    return sorted(train_files), sorted(test_files)


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
