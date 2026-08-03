"""Zen Kaku Gothic New の woff2 サブセットを再生成するスクリプト。

design.md §2.4「フォント: Zen Kaku Gothic New 自前ホスト」で使う和文サブセットフォントの
再現用ビルドスクリプト。frontend/public/fonts/zen-kaku-gothic-new-{400,500,700}.woff2 を
上書き生成する。

文字集合の方針:
- 常用漢字 2136字相当（+ 𠮟/叱 の異体字ペア）を必須とする（JIS 常用漢字表準拠の一般的な
  和文業務アプリの想定カバレッジ）。取得元は下記 JOYO_KANJI_URL（frost.kiwi の
  pyftsubset 向け配布ファイル）。
- ひらがな・カタカナ・半角カタカナの全域、半角ASCII可視域。
- 本リポジトリ frontend/src の現行コード中に実在する文字（漢字以外も含む記号等）。
  常用漢字に含まれない語（例: 閾値の「閾」）を取り落とさないためのセーフティネット。

再実行のタイミング: ui-redesign の各ページ再構成タスク（tasks.md 5〜10）でページ本文の
文言が確定した後、本スクリプトを再実行し、frontend/src の新規文言を確実にカバーする
（tasks.md タスク11メモ参照）。

前提: fonttools（`pip install fonttools`）・インターネット接続（google/fonts・
frost.kiwi から一次データを取得）。
"""

from __future__ import annotations

import glob
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
FONTS_OUT_DIR = REPO_ROOT / "frontend" / "public" / "fonts"
WORK_DIR = Path(__file__).resolve().parent / ".font-build-cache"

# google/fonts リポジトリのソース（OFL・v18。ZenKakuGothicNew-{Regular,Medium,Bold}.ttf）
GOOGLE_FONTS_BASE = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/zenkakugothicnew"
)
WEIGHTS = {"Regular": 400, "Medium": 500, "Bold": 700}

# 常用漢字 2136字 + 異体字ペア（𠮟/叱）の Unicode コードポイント一覧（pyftsubset形式）。
# 出典: https://blog.frost.kiwi/joyo-kanji-unicode/
JOYO_KANJI_URL = "https://blog.frost.kiwi/joyo-kanji-unicode/joyo-kanji-unicode-pyftsubset.txt"

KANA_RANGES = [range(0x3040, 0x3100), range(0xFF61, 0xFFA0)]
ASCII_RANGE = range(0x20, 0x7F)


def _download(url: str, dest: Path) -> None:
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)


def _corpus_codepoints() -> set[int]:
    """frontend/src の現行コードで実際に使われているCJK/かな/記号のコードポイント集合。"""
    chars: set[str] = set()
    for pattern in ("**/*.tsx", "**/*.ts"):
        for path in glob.glob(str(FRONTEND_SRC / pattern), recursive=True):
            chars.update(Path(path).read_text(encoding="utf-8"))
    return {
        ord(c)
        for c in chars
        if (0x3040 <= ord(c) <= 0x30FF)
        or (0x4E00 <= ord(c) <= 0x9FFF)
        or (0xFF00 <= ord(c) <= 0xFFEF)
        or (0x2000 <= ord(c) <= 0x206F)
    }


def _joyo_codepoints(path: Path) -> set[int]:
    text = path.read_text(encoding="utf-8")
    return {
        int(tok.strip()[2:], 16)
        for tok in text.replace("\n", ",").split(",")
        if tok.strip().startswith("U+")
    }


def build_unicode_set() -> set[int]:
    joyo_path = WORK_DIR / "joyo-kanji-unicode-pyftsubset.txt"
    _download(JOYO_KANJI_URL, joyo_path)

    codepoints = _joyo_codepoints(joyo_path)
    for r in KANA_RANGES:
        codepoints.update(r)
    codepoints.update(ASCII_RANGE)
    codepoints.update(_corpus_codepoints())
    return codepoints


def subset_weight(weight_name: str, weight_value: int, unicodes_file: Path) -> None:
    src = WORK_DIR / f"ZenKakuGothicNew-{weight_name}.ttf"
    _download(f"{GOOGLE_FONTS_BASE}/ZenKakuGothicNew-{weight_name}.ttf", src)

    out = FONTS_OUT_DIR / f"zen-kaku-gothic-new-{weight_value}.woff2"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fontTools.subset",
            str(src),
            f"--unicodes-file={unicodes_file}",
            "--flavor=woff2",
            f"--output-file={out}",
            "--layout-features=*",
            "--glyph-names",
            "--symbol-cmap",
            "--legacy-cmap",
            "--notdef-glyph",
            "--notdef-outline",
            "--recommended-glyphs",
            "--name-legacy",
        ],
        check=True,
    )
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")


def main() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    FONTS_OUT_DIR.mkdir(parents=True, exist_ok=True)

    codepoints = build_unicode_set()
    unicodes_file = WORK_DIR / "subset-unicodes.txt"
    unicodes_file.write_text(
        ",".join(f"U+{cp:04x}" for cp in sorted(codepoints)), encoding="utf-8"
    )
    print(f"target glyph count: {len(codepoints)}")

    for weight_name, weight_value in WEIGHTS.items():
        subset_weight(weight_name, weight_value, unicodes_file)

    _download(f"{GOOGLE_FONTS_BASE}/OFL.txt", FONTS_OUT_DIR / "OFL-ZenKakuGothicNew.txt")


if __name__ == "__main__":
    main()
