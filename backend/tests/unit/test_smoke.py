"""プロジェクト雛形のスモークテスト。

pytest が収集・実行でき、マーカー（unit）が機能し、`src` パッケージが
import できること（＝雛形とツール設定が配置されていること）を確認する（F11）。
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_src_package_importable() -> None:
    """`src` パッケージが import できる（雛形が配置されている）。"""
    import src

    assert src.__name__ == "src"
