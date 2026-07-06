import cv2
import numpy as np
import time

def process_image(image_data, image_size_width, image_size_height, mode, crop_offset_x=0):
    """画像データを処理し、上半分と下半分をリサイズする関数。

    C# 推論プログラム (onnx_framework_class_OpenCV/Class1.cs) と整合:
      - monochro crop: x_start=485
      - 上下分割は overlap=60 で重なり付き分割 (defect が境界に来た場合の検出漏れ抑制)
      - リサイズは INTER_AREA (縮小時のアンチエイリアシング、C# Area と同等)

    Args:
        image_data (byte): 画像データのバイト配列
        mode (str): "monochro" または "color" のいずれかを指定
        crop_offset_x (int): crop 開始 x 座標のオフセット (学習時のシフト不変性
            獲得のため raw 段階で揺らす用途。推論時は 0)。**monochro 専用**で、
            color mode では無視される (color は撮像位置ずれの問題が観測されていないため)。

    Returns:
        resized_top_half (numpy.ndarray): 上半分のリサイズ画像
        resized_bottom_half (numpy.ndarray): 下半分のリサイズ画像
        elapsed_time (float): 処理にかかった時間
    """
    read_img = cv2.imdecode(np.frombuffer(image_data, np.uint8), cv2.IMREAD_COLOR)

    if mode == "monochro":
        # crop_offset_x は monochro のみ適用 (撮像系の水平シフト不変性獲得用)
        crop_rectangle = (485 + crop_offset_x, 0, 1250, read_img.shape[0])  # TEMP crop1250 (要revert→1200 / C#整合は1200)
    elif mode == "color":
        # color は crop_offset_x を無視 (C# 推論側との完全整合を保ち、撮像分布も安定)
        read_img = cv2.rotate(read_img, cv2.ROTATE_90_CLOCKWISE)
        crop_rectangle = (215, 0, 1675, read_img.shape[0])
    else:
        print("color or monochroの指定がありません。")
        return None, None, 0

    x, y, w, h = crop_rectangle
    img = read_img[y:y+h, x:x+w]

    # 上下分割: overlap=60 (C# Class1.cs と整合)。defect が境界付近に来た場合の検出漏れを抑制する。
    # bottom flip は C# 側でコメントアウトされており廃止。color/monochro どちらも flip しない。
    overlap = 60
    half_height = img.shape[0] // 2
    top_half = img[0:half_height + overlap, :]
    bottom_half = img[half_height - overlap:, :]

    new_size = (image_size_width, image_size_height)
    start_time = time.time()
    resized_top_half = cv2.resize(top_half, new_size, interpolation=cv2.INTER_AREA)  # C# Area と整合
    elapsed_time = time.time() - start_time
    resized_bottom_half = cv2.resize(bottom_half, new_size, interpolation=cv2.INTER_AREA)

    return resized_top_half, resized_bottom_half, elapsed_time

def load_image_as_byte_array(file_path):
    """ 画像ファイルを読み込み、PNG形式でエンコードしてバイト配列に変換する関数

    cv2.imread は Windows + 非ASCII (日本語/UNC) パスを開けないため、
    np.fromfile + cv2.imdecode 経由で読み込む。

    Args:
        file_path (str): 画像ファイルのパス

    Returns:
        encoded_image.tobytes() (byte): 画像をPNG形式でエンコードしたバイト配列
    """

    raw = np.fromfile(file_path, dtype=np.uint8)
    if raw.size == 0:
        raise FileNotFoundError(f"指定されたファイルが見つかりません: {file_path}")
    image = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)

    if image is None:
        raise FileNotFoundError(f"画像のデコードに失敗しました: {file_path}")

    # PNG形式にエンコードしてバイト配列に変換
    success, encoded_image = cv2.imencode('.png', image)

    if not success:
        raise Exception("画像のエンコードに失敗しました。")

    return encoded_image.tobytes()

if __name__ == '__main__':
    image_data = load_image_as_byte_array("D:/0032011/shisui_project/AI/EfficientAD/ImageData/color/train/841/OK_image_093646_924.bmp")
    resized_top_half, resized_bottom_half, elapsed_time = process_image(image_data, "color")

    cv2.imwrite("resized_top_half.bmp", resized_top_half)
    cv2.imwrite("resized_bottom_half.bmp", resized_bottom_half)
    print(f"画像を .bmp 形式で保存しました。処理時間: {elapsed_time:.4f}秒")

    img_cs = cv2.imread("D:/0032011/shisui_project/AI/EfficientAD/dataset/841/color/train/good/OK_image_093646_924_0.bmp")
    img_py = cv2.imread("resized_top_half.bmp")

    print("完全一致:", np.array_equal(img_py, img_cs))
    print("近似一致:", np.allclose(img_py, img_cs))
