"""datasetステージの境界を守るCI gate。

dataset.manager（dataset処理の低レベルモジュール）を直接importできるのは
datasetパッケージ内のみであることを保証する。他のモジュールは
dataset.DatasetManager の公開APIのみを使用すること。

`dataset.ftp_download`（入力側FTP）は dataset-export-root-migration.md v1.4
決定10により削除済み。

走査対象は training/ 配下のみに限定する（app_ver2はEfficientADと異なり、
同一リポジトリに backend/ 等の無関係なPythonコードを含むため。設計書ADR-app4）。
"""
import ast
from pathlib import Path

TRAINING_ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIR_NAMES = {"tests", "dataset", "__pycache__"}
INTERNAL_MODULES = {"dataset.manager"}


def _imported_module_names(file_path):
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
    return names


def test_pipline_does_not_import_dataset_internals_directly():
    """pipline.py は dataset.manager を直接importしてはいけない。
    dataset処理は dataset の公開APIを経由すること。"""
    pipline_path = TRAINING_ROOT / "pipline.py"
    assert _imported_module_names(pipline_path).isdisjoint(INTERNAL_MODULES)


def test_only_dataset_module_imports_dataset_internals():
    """dataset.manager を直接importしているのは
    dataset パッケージ内のみであること（境界の逆行を防ぐラチェット）。"""
    offenders = []
    for py_file in TRAINING_ROOT.rglob("*.py"):
        rel_parts = py_file.relative_to(TRAINING_ROOT).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if _imported_module_names(py_file) & INTERNAL_MODULES:
            offenders.append(str(py_file.relative_to(TRAINING_ROOT)))
    assert offenders == [], f"dataset外からのdataset内部モジュール直接importを検出: {offenders}"
