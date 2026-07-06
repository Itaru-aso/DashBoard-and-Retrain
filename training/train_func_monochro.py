#!/usr/bin/python
# -*- coding: utf-8 -*-
"""monochro 専用 Student-Teacher 学習スクリプト

color 版 (train_func_color.py) からの差分:
- dataset_path: {dataset_path}/{target_color}/monochro/ を参照
- train_output_dir: {model_dir}/{target_color}/monochro/ に保存
- Teacher 重みファイル名: teacher_{model_size}_monochro_{backbone}_final_state.pth
- 384×512 解像度では {H}_{W}_ prefix 付きの Teacher を参照
- augmentation の saturation=0, penalty_augmentation.grayscale_p=1.0 は config_monochro.yaml 側で設定
"""
import numpy as np
import torch
from torch.utils.data import DataLoader
from torchvision import transforms
import itertools
import os
import random
import json
from tqdm import tqdm
from torch.amp import GradScaler, autocast
from utils.common import (get_autoencoder, get_pdn_small, get_pdn_medium,
                          ImageFolderWithoutTarget, InfiniteDataloader)
from omegaconf import DictConfig
from utils.channel_weights import compute_channel_weights
from utils.edge_mask import slice_edge_excluded
from utils.raw_shift_dataset import RawShiftImageFolder
from utils.transforms import build_default_transform, resolve_normalize_mode


def numpy_encoder(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return json.JSONEncoder().default(obj)


seed = 42
random.seed(0)
on_gpu = torch.cuda.is_available()
out_channels = 384


def focal_feature_loss(distance, gamma=2.0):
    d_norm = distance / (distance.max().detach() + 1e-8)
    weights = d_norm ** gamma
    return torch.mean(weights * distance)


if os.name != 'nt':
    # expandable_segments は Linux 限定 (Windows では非対応で警告が出るため抑制)
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# 後方互換: normalize_mode='none' の transform をモジュールレベルで提供
default_transform = build_default_transform(normalize_mode='none')


class GaussianNoise:
    """ガウシアンノイズを付加する変換（pickle可能）"""
    def __init__(self, std=0.02):
        self.std = std

    def __call__(self, image):
        import torchvision.transforms.functional as TF
        tensor = TF.to_tensor(image)
        noise = torch.randn_like(tensor) * self.std
        tensor = torch.clamp(tensor + noise, 0.0, 1.0)
        return TF.to_pil_image(tensor)


def get_pre_transform(cfg):
    # retrain_app_CW では monochro 専用 sub_cfg は augmentation.monochro を持つ
    # (build_sub_cfg(cfg, "monochro") で merge 後の構造)
    aug = cfg.augmentation.get('monochro', cfg.augmentation.get('color', {}))
    choices = [
        transforms.ColorJitter(brightness=aug.get('ae_color_jitter_brightness', 0.2)),
        transforms.ColorJitter(contrast=aug.get('ae_color_jitter_contrast', 0.2)),
    ]
    # saturation: monochro では 0 設定される想定。0 以外の場合のみ追加
    sat = aug.get('ae_color_jitter_saturation', 0.0)
    if sat > 0:
        choices.append(transforms.ColorJitter(saturation=sat))
    blur_kernel = aug.get('ae_gaussian_blur_kernel', 0)
    if blur_kernel > 0:
        choices.append(transforms.GaussianBlur(
            kernel_size=blur_kernel,
            sigma=(aug.get('ae_gaussian_blur_sigma_min', 0.1),
                   aug.get('ae_gaussian_blur_sigma_max', 1.0))))
    noise_std = aug.get('ae_gaussian_noise_std', 0.0)
    if noise_std > 0:
        choices.append(GaussianNoise(std=noise_std))
    affine_degrees = aug.get('ae_random_affine_degrees', 0)
    if affine_degrees > 0:
        translate = tuple(aug.get('ae_random_affine_translate', [0.03, 0.03]))
        choices.append(transforms.RandomAffine(degrees=affine_degrees, translate=translate))
    return transforms.RandomChoice(choices)


def get_st_transform(cfg):
    st_cfg = cfg.get('st_augmentation', None)
    if st_cfg is None or not st_cfg.get('enabled', False):
        return None
    tf_list = []
    if st_cfg.get('horizontal_flip', False):
        tf_list.append(transforms.RandomHorizontalFlip())
    brightness = st_cfg.get('color_jitter_brightness', 0)
    contrast = st_cfg.get('color_jitter_contrast', 0)
    saturation = st_cfg.get('color_jitter_saturation', 0)
    if brightness > 0 or contrast > 0 or saturation > 0:
        tf_list.append(transforms.ColorJitter(
            brightness=brightness, contrast=contrast, saturation=saturation))
    if not tf_list:
        return None
    return transforms.Compose(tf_list)


class TrainTransform:
    def __init__(self, pre_tf, default_tf, st_tf=None):
        self.pre_tf = pre_tf
        self.default_tf = default_tf
        self.st_tf = st_tf

    def __call__(self, image):
        if self.st_tf is not None:
            st_image = self.default_tf(self.st_tf(image))
        else:
            st_image = self.default_tf(image)
        ae_image = self.default_tf(self.pre_tf(image))
        return st_image, ae_image


def _resolve_teacher_weights_path(cfg) -> str:
    """Teacher 重みファイルの絶対パスを解決する (color と対称)。

    cfg.teacher_weights が指定されていればそれを使い、
    なければ cfg.pretraining_dir 配下の命名規約から自動推定する。

    retrain_app_CW での想定配置 (常に {h}_{w}_ prefix を付ける):
        0_pretraining/256_512_teacher_small_monochro_wide_resnet101_final_state.pth
        0_pretraining/384_512_teacher_small_monochro_wide_resnet101_final_state.pth
    (実機運用前に手動配置が必要 — 別タスクの src_custom/monochro/pretraining_monochro.py で生成)
    """
    override = cfg.get('teacher_weights', None)
    if override:
        return override
    pretraining_dir = cfg.get('pretraining_dir', './0_pretraining')
    model_size = cfg.get('model_size', 'small')
    backbone = cfg.get('backbone', 'wide_resnet101')
    h = int(cfg.image_size_height)
    w = int(cfg.image_size_width)
    fname = f'{h}_{w}_teacher_{model_size}_monochro_{backbone}_final_state.pth'
    return os.path.join(pretraining_dir, fname)


def train_monochro(cfg: DictConfig, mgr=None):
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

    image_size_height = int(cfg.image_size_height)
    image_size_width = int(cfg.image_size_width)

    edge_mask_w = int(cfg.get('edge_mask_w', 0))
    if edge_mask_w > 0:
        print(f'[edge_mask_w={edge_mask_w}] 両端マスクを loss / quantile / threshold 計算から除外')

    # normalize_mode 解決 (後方互換: per_image_minmax=true → 'min_max')
    normalize_mode = resolve_normalize_mode({
        'normalize_mode': cfg.get('normalize_mode', None),
        'per_image_minmax': cfg.get('per_image_minmax', False),
    })
    target_mean = cfg.get('normalize_target_mean', None)
    target_std = cfg.get('normalize_target_std', None)
    if normalize_mode != 'none':
        print(f'[normalize_mode={normalize_mode}] 画像ごとの正規化を適用'
              + (f' (target_mean={target_mean}, target_std={target_std})'
                 if normalize_mode == 'mean_std' else ''))
    active_transform = build_default_transform(
        normalize_mode=normalize_mode,
        target_mean=list(target_mean) if target_mean is not None else None,
        target_std=list(target_std) if target_std is not None else None)

    output_dir = cfg.model_dir

    scaler = GradScaler(device='cuda')

    # monochro 専用: {model_dir}/{target_color}/{monochro_subdir}/ に保存
    # monochro_subdir は config で上書き可 (環境別学習時は monochro_<env> 等)
    monochro_subdir = cfg.get('monochro_subdir', 'monochro')
    train_output_dir = os.path.join(output_dir, str(cfg.target_color), monochro_subdir)

    gpu_id = int(cfg.get('gpu_id', 0))
    device = torch.device(f'cuda:{gpu_id}' if torch.cuda.is_available() else 'cpu')

    os.makedirs(train_output_dir, exist_ok=True)

    dataset_dir_path = cfg.dataset_path
    color_num = str(cfg.target_color)
    # monochro 専用: {dataset_path}/{target_color}/{monochro_subdir}/ を参照
    dataset_path = os.path.join(dataset_dir_path, color_num, monochro_subdir)

    pretrain_penalty = True

    pre_tf = get_pre_transform(cfg)
    st_tf = get_st_transform(cfg)
    train_tf = TrainTransform(pre_tf, active_transform, st_tf=st_tf)

    # raw 画像から random crop offset で前処理する augmentation を使うか判定。
    # 撮像系の水平シフト (再検証で +14 px 観測) に対する不変性を獲得するため、
    # raw 段階で crop_offset_x をランダム化して学習する。
    use_raw_shift = bool(cfg.get('use_raw_shift_dataset', False))
    crop_shift_max_px = int(cfg.get('crop_shift_max_px', 0))

    if use_raw_shift:
        raw_root_base = cfg.get('raw_image_root', cfg.get('download_dir', './1_download'))
        raw_root = os.path.join(str(raw_root_base), color_num, monochro_subdir, 'good')
        print(f'[raw_shift_dataset] raw 画像から random crop_offset (±{crop_shift_max_px} px) で学習: {raw_root}')
        # train 用: ±crop_shift_max_px で random shift augment
        train_full = RawShiftImageFolder(
            raw_root=raw_root, mode='monochro',
            image_size_width=image_size_width,
            image_size_height=image_size_height,
            crop_shift_max_px=crop_shift_max_px,
            transform=train_tf,
            seed=seed,
        )
        # validation 用: 同じ raw 画像、offset=0 固定 (C# 推論時と同じクロップ)。
        # val_loss / map_normalization の quantile / threshold が augment ノイズを受けないようにする。
        val_full = RawShiftImageFolder(
            raw_root=raw_root, mode='monochro',
            image_size_width=image_size_width,
            image_size_height=image_size_height,
            crop_shift_max_px=0,
            transform=train_tf,
            seed=seed,
        )
        assert len(train_full) == len(val_full), (
            f'train_full ({len(train_full)}) と val_full ({len(val_full)}) のサイズが一致しません'
        )
        full_size = len(train_full)
        train_size = int(0.8 * full_size)
        validation_size = full_size - train_size
        rng = torch.Generator().manual_seed(seed)
        indices = torch.randperm(full_size, generator=rng).tolist()
        train_set = torch.utils.data.Subset(train_full, indices[:train_size])
        validation_set = torch.utils.data.Subset(val_full, indices[train_size:])
        # 後続コード (teacher_normalization, train_step 計算等) は len(full_train_set) を参照するため保持
        full_train_set = train_full
    else:
        full_train_set = ImageFolderWithoutTarget(
            os.path.join(dataset_path, 'train'),
            transform=train_tf)
        train_size = int(0.8 * len(full_train_set))
        validation_size = len(full_train_set) - train_size
        rng = torch.Generator().manual_seed(seed)
        train_set, validation_set = torch.utils.data.random_split(
            full_train_set, [train_size, validation_size], rng)

    _nw = int(cfg.get('num_workers', 4))
    _pw = bool(cfg.get('persistent_workers', False)) and _nw > 0
    train_loader = DataLoader(train_set, batch_size=cfg.batch_size, shuffle=True,
                              num_workers=_nw, pin_memory=True, persistent_workers=_pw)
    validation_loader = DataLoader(validation_set, batch_size=cfg.batch_size)

    train_loader_infinite = InfiniteDataloader(train_loader)

    if pretrain_penalty:
        pen_aug = cfg.get('penalty_augmentation', {})
        penalty_transform_list = [
            transforms.Resize((2 * image_size_height, 2 * image_size_width)),
            # monochro: grayscale_p=1.0 で OOD も常時 grayscale 化 (config 側で指定)
            transforms.RandomGrayscale(pen_aug.get('grayscale_p', 1.0)),
            transforms.RandomCrop((image_size_height, image_size_width)),
        ]
        if pen_aug.get('horizontal_flip', True):
            penalty_transform_list.append(transforms.RandomHorizontalFlip())
        if pen_aug.get('color_jitter_brightness', 0.2) > 0 or \
                pen_aug.get('color_jitter_contrast', 0.2) > 0 or \
                pen_aug.get('color_jitter_saturation', 0.0) > 0:
            penalty_transform_list.append(transforms.ColorJitter(
                brightness=pen_aug.get('color_jitter_brightness', 0.2),
                contrast=pen_aug.get('color_jitter_contrast', 0.2),
                saturation=pen_aug.get('color_jitter_saturation', 0.0)))
        # ToTensor + 正規化 (active_transform と同じ正規化モードを後段に適用)
        penalty_transform_list.append(transforms.ToTensor())
        from utils.transforms import PerImageMinMax, PerImageMeanStd
        if normalize_mode == 'min_max':
            penalty_transform_list.append(PerImageMinMax())
            penalty_transform_list.append(transforms.Normalize(
                mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]))
        elif normalize_mode == 'mean_std':
            penalty_transform_list.append(PerImageMeanStd(
                target_mean=list(target_mean) if target_mean is not None else None,
                target_std=list(target_std) if target_std is not None else None))
        else:  # 'none'
            penalty_transform_list.append(transforms.Normalize(
                mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]))
        if pen_aug.get('random_erasing_p', 0.1) > 0:
            penalty_transform_list.append(transforms.RandomErasing(
                p=pen_aug.get('random_erasing_p', 0.1),
                scale=(0.02, 0.15)))
        penalty_transform = transforms.Compose(penalty_transform_list)
        penalty_set = ImageFolderWithoutTarget(cfg.imagenet_train_path,
                                               transform=penalty_transform)
        penalty_loader = DataLoader(penalty_set, batch_size=cfg.batch_size, shuffle=True,
                                    num_workers=_nw, pin_memory=True, persistent_workers=_pw)
        penalty_loader_infinite = InfiniteDataloader(penalty_loader)
        print(f"The size of training_set is {len(full_train_set)}.")
        print(f"The size of penalty_set is {len(penalty_set)}.")
    else:
        penalty_loader_infinite = itertools.repeat(None)

    pdn_dropout = cfg.get('pdn_dropout', 0.0)
    if cfg.model_size == "small":
        teacher = get_pdn_small(out_channels, dropout_rate=pdn_dropout)
        student = get_pdn_small(2 * out_channels, dropout_rate=pdn_dropout)
    elif cfg.model_size == "medium":
        teacher = get_pdn_medium(out_channels, dropout_rate=pdn_dropout)
        student = get_pdn_medium(2 * out_channels, dropout_rate=pdn_dropout)

    weights_path = _resolve_teacher_weights_path(cfg)
    print(f'Teacher 重み: {weights_path}')
    state_dict = torch.load(weights_path, map_location='cpu', weights_only=True)
    # 旧 PDN (Dropout なし、最終 Conv が index 8) → 現行 PDN (index 9) のキー読み替え
    if '8.weight' in state_dict and '9.weight' not in state_dict:
        state_dict = {(('9' + k[1:]) if k.startswith('8.') else k): v for k, v in state_dict.items()}
    teacher.load_state_dict(state_dict)
    autoencoder = get_autoencoder(out_channels,
                                  image_size_height=image_size_height,
                                  image_size_width=image_size_width)

    teacher.eval()
    student.train()
    autoencoder.train()

    if on_gpu:
        teacher.to(device)
        student.to(device)
        autoencoder.to(device)

    best_val_loss = float('inf')
    val_patience_counter = 0

    train_dataset_size = len(full_train_set)
    iterations_per_epoch = train_dataset_size // cfg.batch_size
    cfg.train_step = iterations_per_epoch * cfg.epochs

    # 学習 step の上限キャップ (データ増加時の線形増加を抑制、過学習回避)
    max_train_step = cfg.get('max_train_step', None)
    if max_train_step is not None and cfg.train_step > max_train_step:
        print(f'[max_train_step] epochs={cfg.epochs} × iter/epoch={iterations_per_epoch} = {cfg.train_step} step を {max_train_step} step にキャップ')
        cfg.train_step = max_train_step

    # val_interval: cfg.val_interval があればそれを使い、無ければ len(train_loader) (1 epoch 毎)
    # 大きい値にすると validation 頻度が下がり、I/O 待ち (.pth save 等) を削減できる
    cfg_val_interval = cfg.get('val_interval', None)
    val_interval = int(cfg_val_interval) if cfg_val_interval else len(train_loader)
    print(f'[val_interval={val_interval}] {val_interval} step ごとに validation 実行')

    teacher_mean, teacher_std = teacher_normalization(teacher, train_loader)

    optimizer = torch.optim.AdamW(itertools.chain(student.parameters(),
                                                  autoencoder.parameters()),
                                  lr=cfg.model.lr, weight_decay=cfg.model.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=cfg.train_step)

    mlflow_log_interval = cfg.get('mlflow', {}).get('log', {}).get('train_step_interval', 500)

    tqdm_obj = tqdm(range(cfg.train_step))
    for iteration, (image_st, image_ae), image_penalty in zip(
            tqdm_obj, train_loader_infinite, penalty_loader_infinite):
        optimizer.zero_grad()
        with autocast("cuda"):
            if on_gpu:
                image_st = image_st.to(device)
                image_ae = image_ae.to(device)
                if image_penalty is not None:
                    image_penalty = image_penalty.to(device)

            with torch.no_grad():
                teacher_output_st = teacher(image_st)
                teacher_output_st = (teacher_output_st - teacher_mean) / teacher_std
            student_output_st = student(image_st)[:, :out_channels]

            distance_st = (teacher_output_st - student_output_st) ** 2
            # 両端 padding artifact を loss/quantile/threshold から除外。
            # color 側も Phase H 完成で対称適用済 (cfg.color.edge_mask_w で制御、現状デフォルト 2)。
            distance_st_masked = slice_edge_excluded(distance_st, edge_mask_w)

            loss_type = cfg.get('st_loss_type', 'hard')
            if loss_type == 'focal':
                focal_gamma = cfg.get('focal_gamma', 2.0)
                loss_hard = focal_feature_loss(distance_st_masked, gamma=focal_gamma)
            else:
                flat = distance_st_masked.flatten()
                max_elements = 100_000
                if flat.numel() > max_elements:
                    indices = torch.randperm(flat.numel(), device=flat.device)[:max_elements]
                    flat = flat[indices]
                d_hard = torch.quantile(flat, q=cfg.get('hard_mining_quantile', 0.999))
                loss_hard = torch.mean(distance_st_masked[distance_st_masked >= d_hard])

            del teacher_output_st, student_output_st, distance_st, distance_st_masked

            if image_penalty is not None:
                student_output_penalty = student(image_penalty)[:, :out_channels]
                loss_penalty = torch.mean(student_output_penalty ** 2)
                penalty_weight = cfg.get('penalty_weight', 1.0)
                loss_st = loss_hard + penalty_weight * loss_penalty
            else:
                loss_st = loss_hard

            with torch.no_grad():
                teacher_output_ae = teacher(image_ae)
                teacher_output_ae = (teacher_output_ae - teacher_mean) / teacher_std

            ae_output = autoencoder(image_ae)
            student_output_ae = student(image_ae)[:, out_channels:]

            distance_ae = (teacher_output_ae - ae_output) ** 2
            distance_stae = (ae_output - student_output_ae) ** 2
            loss_ae = torch.mean(slice_edge_excluded(distance_ae, edge_mask_w))
            loss_stae = torch.mean(slice_edge_excluded(distance_stae, edge_mask_w))
            loss_total = cfg.loss_st * loss_st + cfg.loss_ae * loss_ae + cfg.loss_stae * loss_stae

        scaler.scale(loss_total).backward()
        scaler.step(optimizer)
        scaler.update()
        scheduler.step()

        if iteration % 10 == 0:
            tqdm_obj.set_description("Current loss: {:.4f}  ".format(loss_total.item()))

        if mgr is not None and mlflow_log_interval > 0 and iteration % mlflow_log_interval == 0:
            step_metrics = {'train_loss_total': loss_total.item(),
                            'train_loss_st': loss_st.item(),
                            'train_loss_ae': loss_ae.item()}
            if image_penalty is not None:
                step_metrics['train_loss_penalty'] = loss_penalty.item()
            mgr.log_metrics(step_metrics, step=iteration)

        if iteration % val_interval == 0:
            val_loss = evaluate_validation_loss(validation_loader, teacher, student,
                                                autoencoder, teacher_mean, teacher_std,
                                                device, cfg)
            print(f"Validation Loss: {val_loss:.4f}")

            # val_loss を MLflow に step 単位で記録 (過学習検知の可視化)
            if mgr is not None:
                mgr.log_metrics({'val_loss': val_loss}, step=iteration)

            # NOTE: temp .pth (teacher/student/autoencoder_state_temp.pth) は学習時間短縮のため削除済み
            # best 更新時のみ *_state_best.pth を保存する (下記 if val_loss < best_val_loss ブロック参照)

            q_st_start, q_st_end, q_ae_start, q_ae_end = map_normalization(
                validation_loader=validation_loader, teacher=teacher,
                student=student, autoencoder=autoencoder,
                teacher_mean=teacher_mean, teacher_std=teacher_std,
                st_para=cfg.map_st, ae_para=cfg.map_ae,
                desc='Intermediate map normalization',
                edge_mask_w=edge_mask_w)

            # best モデル保存も patience リセットも「min_delta 以上の真の改善」で統一 (color 側と対称)
            min_delta = float(cfg.get('early_stop_min_delta', 0.0))
            meaningful_improved = val_loss < (best_val_loss - min_delta)

            if meaningful_improved:
                best_val_loss = val_loss
                val_patience_counter = 0
                torch.save(teacher.state_dict(), os.path.join(train_output_dir, 'teacher_state_best.pth'))
                torch.save(student.state_dict(), os.path.join(train_output_dir, 'student_state_best.pth'))
                torch.save(autoencoder.state_dict(), os.path.join(train_output_dir, 'autoencoder_state_best.pth'))

                q_st_start_l = [q_st_start.cpu().detach().numpy().copy()]
                q_st_end_l = [q_st_end.cpu().detach().numpy().copy()]
                q_ae_start_l = [q_ae_start.cpu().detach().numpy().copy()]
                q_ae_end_l = [q_ae_end.cpu().detach().numpy().copy()]
                teacher_mean_l = [teacher_mean.cpu().detach().numpy().copy()]
                teacher_std_l = [teacher_std.cpu().detach().numpy().copy()]

                para_json = {
                    'q_st_start': q_st_start_l, 'q_st_end': q_st_end_l,
                    'q_ae_start': q_ae_start_l, 'q_ae_end': q_ae_end_l,
                    'teacher_mean': teacher_mean_l, 'teacher_std': teacher_std_l,
                    'image_size_height': int(image_size_height),
                    'image_size_width': int(image_size_width),
                }
                with open(os.path.join(train_output_dir, 'para.json'), 'w', encoding='utf-8') as para_file:
                    json.dump(para_json, para_file, indent=4, default=numpy_encoder, ensure_ascii=False)

            else:
                val_patience_counter += 1
                if val_patience_counter >= cfg.early_stop_patience:
                    print(f"Early stopping triggered based on validation loss (min_delta={min_delta}).")
                    if mgr is not None:
                        mgr.log_metrics({'early_stop_step': iteration}, step=iteration)
                    break

            teacher.eval()
            student.train()
            autoencoder.train()

            del image_st, image_ae, image_penalty
            del teacher_output_ae, student_output_ae, ae_output
            del distance_ae, distance_stae, loss_ae, loss_stae, loss_total
            torch.cuda.empty_cache()

    teacher.eval()
    student.eval()
    autoencoder.eval()

    teacher.load_state_dict(torch.load(os.path.join(train_output_dir, 'teacher_state_best.pth'), weights_only=True))
    student.load_state_dict(torch.load(os.path.join(train_output_dir, 'student_state_best.pth'), weights_only=True))
    autoencoder.load_state_dict(torch.load(os.path.join(train_output_dir, 'autoencoder_state_best.pth'), weights_only=True))

    # raw_shift モード時: teacher_mean/std を推論時分布 (shift=0) で再計算して上書きする。
    # 学習中は augment 込みの統計だったが、channel_weights / 最終 map_normalization /
    # threshold / para.json 保存は「推論時と同じ分布 (C# 側で読まれる値)」で揃えるべき。
    # validation_loader は val_full (RawShiftImageFolder, shift_max=0) の subset なので
    # 推論時相当の固定 offset で teacher の特徴量統計を取り直せる。
    if use_raw_shift:
        print('[teacher_renormalization] 推論時分布 (shift=0) で teacher_mean/std を再計算 (channel_weights / threshold 用)')
        teacher_mean, teacher_std = teacher_normalization(teacher, validation_loader)

    # Channel Weights 計算
    channel_weights_tensor = None
    channel_weights_info = {}
    cw_cfg = cfg.get('channel_weights', None)
    if cw_cfg is not None and cw_cfg.get('enabled', False):
        # [データ依存関係 — monochro] channel_weights の入力ソース:
        #   raw_shift=True  : good は 1_download の shift=0 クロップ (val_full) から取得し、
        #                     defect は 3_pool→4_dataset split 済の 4_dataset/train/defect から。
        #                     (good を 1_download に一本化したため 4_dataset/train/good は不要)
        #   raw_shift=False : 従来どおり 4_dataset/train/{good,defect} から。
        # 不良は raw を上下2分割すると不良箇所の half が不明 → 2_staging 人手triage が必須で、
        # その成果 (3_pool/<color>/monochro/defect_pool→4_dataset/train/defect) だけが defect の供給源。
        cw_kwargs = dict(
            supervised_power=cw_cfg.get('supervised_power', 10),
            unsupervised_power=cw_cfg.get('unsupervised_power', 7),
            blend_n_mid=cw_cfg.get('blend_n_mid', 30),
            blend_scale=cw_cfg.get('blend_scale', 10.0),
            max_fpr=cw_cfg.get('max_fpr', 0.05))
        train_path = os.path.join(dataset_path, 'train')
        cw_defect_path = os.path.join(train_path, 'defect')
        if use_raw_shift:
            # good は 1_download 由来 (val_full: shift=0 のクロップ済テンソルを yield)。
            # defect が無い場合 compute_channel_weights は unsupervised に degrade する。
            weights_np, cw_method, ch_aucs, w_sup = compute_channel_weights(
                teacher, student, teacher_mean, teacher_std, None, device,
                good_dataset=val_full, defect_path=cw_defect_path, **cw_kwargs)
        else:
            _cw_good = os.path.join(train_path, 'good')
            if not (os.path.isdir(_cw_good)
                    and any(f.lower().endswith('.bmp') for f in os.listdir(_cw_good))):
                raise FileNotFoundError(
                    f"[monochro] channel_weights に必要な前処理済データがありません: {_cw_good}\n"
                    f"  → 先に split_pool_to_dataset('{color_num}', mode='monochro') を実行してください。")
            weights_np, cw_method, ch_aucs, w_sup = compute_channel_weights(
                teacher, student, teacher_mean, teacher_std, train_path, device, **cw_kwargs)
        channel_weights_tensor = torch.from_numpy(weights_np).float().to(device)
        channel_weights_tensor = channel_weights_tensor[None, :, None, None]
        channel_weights_info['channel_weights'] = weights_np.tolist()
        channel_weights_info['channel_weights_method'] = cw_method
        channel_weights_info['blend_w_sup'] = float(w_sup)
        if ch_aucs is not None:
            channel_weights_info['channel_aucs'] = ch_aucs.tolist()
        print(f'チャネル重み計算完了 (方式: {cw_method}, w_sup={w_sup:.4f})')

    q_st_start, q_st_end, q_ae_start, q_ae_end = map_normalization(
        validation_loader=validation_loader, teacher=teacher, student=student,
        autoencoder=autoencoder, teacher_mean=teacher_mean,
        st_para=cfg.map_st, ae_para=cfg.map_ae, teacher_std=teacher_std,
        desc='Final map normalization',
        channel_weights=channel_weights_tensor,
        edge_mask_w=edge_mask_w)

    q_st_start_l = [q_st_start.cpu().detach().numpy().copy()]
    q_st_end_l = [q_st_end.cpu().detach().numpy().copy()]
    q_ae_start_l = [q_ae_start.cpu().detach().numpy().copy()]
    q_ae_end_l = [q_ae_end.cpu().detach().numpy().copy()]
    teacher_mean_l = [teacher_mean.cpu().detach().numpy().copy()]
    teacher_std_l = [teacher_std.cpu().detach().numpy().copy()]

    best_st, best_ae = cfg.map_st, cfg.map_ae

    teacher_mean_4d = teacher_mean.squeeze().cpu().detach().numpy()
    teacher_std_4d = teacher_std.squeeze().cpu().detach().numpy()

    para_json = {
        'q_st_start': q_st_start_l, 'q_st_end': q_st_end_l,
        'q_ae_start': q_ae_start_l, 'q_ae_end': q_ae_end_l,
        'teacher_mean': teacher_mean_l, 'teacher_std': teacher_std_l,
        'teacher_mean_1d': teacher_mean_4d.tolist(),
        'teacher_std_1d': teacher_std_4d.tolist(),
        'st_para': best_st, 'ae_para': best_ae,
        'image_size_height': int(image_size_height),
        'image_size_width': int(image_size_width),
        'edge_mask_w': edge_mask_w,
        'normalize_mode': normalize_mode,
        # 後方互換のため per_image_minmax も保存 (normalize_mode='min_max' のとき True)
        'per_image_minmax': normalize_mode == 'min_max',
    }
    if normalize_mode == 'mean_std':
        para_json['normalize_target_mean'] = (
            list(target_mean) if target_mean is not None else None)
        para_json['normalize_target_std'] = (
            list(target_std) if target_std is not None else None)
    para_json.update(channel_weights_info)

    # F1 最大化閾値の計算 (validation set から)
    print('閾値計算中...')
    scores_val = []
    cand1_maps = []  # 候補1 (z-score) 較正用: per-image の scored_map (edge_mask 適用後, 2D)
    for image, _ in tqdm(validation_loader, desc='Computing threshold scores'):
        if on_gpu:
            image = image.to(device)
        teacher_output = teacher(image)
        teacher_output = (teacher_output - teacher_mean) / teacher_std
        student_output = student(image)
        diff_st = (teacher_output - student_output[:, :out_channels]) ** 2
        if channel_weights_tensor is not None:
            map_st = torch.sum(diff_st * channel_weights_tensor, dim=1, keepdim=True)
        else:
            map_st = torch.mean(diff_st, dim=1, keepdim=True)
        if q_st_start is not None:
            map_st = 0.1 * (map_st - q_st_start) / (q_st_end - q_st_start)
        scored_map = best_st * map_st
        scored_map = slice_edge_excluded(scored_map, edge_mask_w)
        score = scored_map.max().item()
        scores_val.append(score)
        # 候補1: per-image の 2D マップを保持 (batch_size>1 に対応)
        for b in range(scored_map.shape[0]):
            cand1_maps.append(scored_map[b, 0].detach().cpu().numpy())

    scores_np = np.array(scores_val)
    threshold_val = float(np.quantile(scores_np, 0.995))
    para_json['threshold'] = threshold_val
    print(f'閾値: {threshold_val:.6f} (validation 99.5パーセンタイル)')

    # 候補1 (raw + z-score OR, monochro 専用) 較正: μ,σ,A,Z を算出して para に保存。
    # raw/z は scored_map(=st_para·map_st, edge_mask 適用後の 56x120) で算出し model.py forward と一致させる。
    # cand1_enabled が無い旧 para / color では z-OR 無効=従来 raw 動作 (後方互換)。
    try:
        from utils.candidate1_calib import (
            compute_mu_sigma, raw_map_max, zscore_map_max, calib_AZ)
        cand1_fpr = 1.0
        c1cfg = cfg.get('candidate1', None) if hasattr(cfg, 'get') else None
        if c1cfg is not None:
            try:
                cand1_fpr = float(c1cfg.get('fpr', 1.0))
            except Exception:
                cand1_fpr = 1.0
        mu, sigma = compute_mu_sigma(cand1_maps)
        raws_c = [raw_map_max(m) for m in cand1_maps]
        zs_c = [zscore_map_max(m, mu, sigma) for m in cand1_maps]
        A_c, Z_c = calib_AZ(raws_c, zs_c, fpr_pct=cand1_fpr)
        para_json['cand1_enabled'] = True
        para_json['cand1_mu'] = mu.tolist()
        para_json['cand1_sigma'] = sigma.tolist()
        para_json['cand1_A'] = float(A_c)
        para_json['cand1_Z'] = float(Z_c)
        para_json['cand1_T'] = 1.0
        para_json['cand1_fpr'] = float(cand1_fpr)
        print(f'候補1較正(monochro): A={A_c:.4f} Z={Z_c:.3f} '
              f'(fpr={cand1_fpr}%, μσ shape={mu.shape})')
    except Exception as e:
        print(f'⚠️ 候補1較正に失敗 (raw のみで継続): {e}')

    with open(os.path.join(train_output_dir, 'para.json'), 'w', encoding='utf-8') as para_file:
        json.dump(para_json, para_file, indent=4, default=numpy_encoder, ensure_ascii=False)


@torch.no_grad()
def evaluate_validation_loss(validation_loader, teacher, student, autoencoder,
                             teacher_mean, teacher_std, device, cfg):
    """validation loss を集計する (monochro 専用)。

    edge_mask_w で両端をマスクして loss を取る (color 側にも Phase H 完成で
    対称適用済、cfg.color.edge_mask_w で制御)。
    """
    teacher.eval()
    student.eval()
    autoencoder.eval()

    edge_mask_w = int(cfg.get('edge_mask_w', 0))

    total_loss = 0
    count = 0
    for image, _ in validation_loader:
        image = image.to(device)
        teacher_output = teacher(image)
        teacher_output = (teacher_output - teacher_mean) / teacher_std
        student_output = student(image)
        ae_output = autoencoder(image)

        d_st = (teacher_output - student_output[:, :384]) ** 2
        d_ae = (teacher_output - ae_output) ** 2
        d_stae = (ae_output - student_output[:, 384:]) ** 2
        loss_st = torch.mean(slice_edge_excluded(d_st, edge_mask_w))
        loss_ae = torch.mean(slice_edge_excluded(d_ae, edge_mask_w))
        loss_stae = torch.mean(slice_edge_excluded(d_stae, edge_mask_w))

        loss_total = cfg.loss_st * loss_st + cfg.loss_ae * loss_ae + cfg.loss_stae * loss_stae
        total_loss += loss_total.item()
        count += 1

    student.train()
    autoencoder.train()
    return total_loss / count


@torch.no_grad()
def predict(image, teacher, student, autoencoder, teacher_mean, teacher_std, st_para, ae_para,
            q_st_start=None, q_st_end=None, q_ae_start=None, q_ae_end=None,
            channel_weights=None):
    teacher_output = teacher(image)
    teacher_output = (teacher_output - teacher_mean) / teacher_std
    student_output = student(image)
    autoencoder_output = autoencoder(image)

    diff_st = (teacher_output - student_output[:, :out_channels]) ** 2
    if channel_weights is not None:
        map_st = torch.sum(diff_st * channel_weights, dim=1, keepdim=True)
    else:
        map_st = torch.mean(diff_st, dim=1, keepdim=True)

    map_ae = torch.mean((autoencoder_output - student_output[:, out_channels:]) ** 2,
                        dim=1, keepdim=True)
    if q_st_start is not None:
        map_st = 0.1 * (map_st - q_st_start) / (q_st_end - q_st_start)
    if q_ae_start is not None:
        map_ae = 0.1 * (map_ae - q_ae_start) / (q_ae_end - q_ae_start)
    map_combined = st_para * map_st + ae_para * map_ae
    return map_combined, map_st, map_ae


@torch.no_grad()
def map_normalization(validation_loader, teacher, student, autoencoder,
                      teacher_mean, teacher_std, st_para, ae_para,
                      desc='Map normalization', channel_weights=None,
                      edge_mask_w=0):
    """validation set から anomaly map の quantile を集計する (monochro 専用)。

    edge_mask_w>0 のとき両端を除外して quantile を計算する (color 版も Phase H
    完成で対称適用済、cfg.color.edge_mask_w で制御)。
    """
    maps_st = []
    maps_ae = []
    # teacher が乗っている device を採用 (cuda:0 ハードコードを廃止)
    device = next(teacher.parameters()).device
    for image, _ in tqdm(validation_loader, desc=desc):
        if on_gpu:
            image = image.to(device)
        map_combined, map_st, map_ae = predict(
            image=image, teacher=teacher, student=student,
            autoencoder=autoencoder, teacher_mean=teacher_mean,
            teacher_std=teacher_std, st_para=st_para, ae_para=ae_para,
            channel_weights=channel_weights)
        maps_st.append(slice_edge_excluded(map_st, edge_mask_w))
        maps_ae.append(slice_edge_excluded(map_ae, edge_mask_w))
    maps_st = torch.cat(maps_st).cpu().numpy().flatten()
    maps_ae = torch.cat(maps_ae).cpu().numpy().flatten()
    q_st_start = torch.tensor(np.quantile(maps_st, 0.9))
    q_st_end = torch.tensor(np.quantile(maps_st, 0.995))
    q_ae_start = torch.tensor(np.quantile(maps_ae, 0.9))
    q_ae_end = torch.tensor(np.quantile(maps_ae, 0.995))
    return q_st_start, q_st_end, q_ae_start, q_ae_end


@torch.no_grad()
def teacher_normalization(teacher, train_loader):
    mean_outputs = []
    # teacher が乗っている device を採用 (cuda:0 ハードコードを廃止)
    device = next(teacher.parameters()).device

    for train_image, _ in tqdm(train_loader, desc='Computing mean of features'):
        if on_gpu:
            train_image = train_image.to(device)
        teacher_output = teacher(train_image)
        mean_output = torch.mean(teacher_output, dim=[0, 2, 3])
        mean_outputs.append(mean_output)
    channel_mean = torch.mean(torch.stack(mean_outputs), dim=0)
    channel_mean = channel_mean[None, :, None, None]

    mean_distances = []
    for train_image, _ in tqdm(train_loader, desc='Computing std of features'):
        if on_gpu:
            train_image = train_image.to(device)
        teacher_output = teacher(train_image)
        distance = (teacher_output - channel_mean) ** 2
        mean_distance = torch.mean(distance, dim=[0, 2, 3])
        mean_distances.append(mean_distance)
    channel_var = torch.mean(torch.stack(mean_distances), dim=0)
    channel_var = channel_var[None, :, None, None]
    channel_std = torch.sqrt(channel_var)
    return channel_mean, channel_std


if __name__ == '__main__':
    import sys
    from omegaconf import OmegaConf
    config_path = './conf/config_monochro.yaml'
    cli_args = sys.argv[1:]
    if '--config-name' in cli_args:
        idx = cli_args.index('--config-name')
        name = cli_args[idx + 1]
        config_path = f'./conf/{name}.yaml'
        cli_args = cli_args[:idx] + cli_args[idx + 2:]
    cfg = OmegaConf.load(config_path)
    cli_overrides = [arg for arg in cli_args if '=' in arg]
    if cli_overrides:
        cli_cfg = OmegaConf.from_dotlist(cli_overrides)
        cfg = OmegaConf.merge(cfg, cli_cfg)
    train_monochro(cfg)
