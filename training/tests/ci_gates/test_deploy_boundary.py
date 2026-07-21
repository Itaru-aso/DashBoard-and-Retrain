"""deployステージの境界を守るCI gate。

utils.ftp_common.upload_file_to_ftp（ONNXモデルアップロードの低レベル関数）と
deploy.model_export（ONNXエクスポートの低レベルモジュール）を直接importできるのは
deployパッケージ内のみであることを保証する。他のモジュールは
deploy.upload_model / deploy.export_model の公開APIのみを使用すること。

走査対象は training/ 配下のみに限定する（app_ver2はEfficientADと異なり、
同一リポジトリに backend/ 等の無関係なPythonコードを含むため。設計書ADR-app4）。
"""
import ast
from pathlib import Path

TRAINING_ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_DIR_NAMES = {"tests", "deploy", "__pycache__"}
INTERNAL_MODULES = {"deploy.model_export"}


def _imported_names(file_path):
    tree = ast.parse(file_path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.name)
    return names


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


def test_pipline_does_not_import_ftp_upload_helper_directly():
    """pipline.py は utils.ftp_common.upload_file_to_ftp を直接importしてはいけない。
    ONNXモデルのFTPアップロードは deploy モジュールの公開APIを経由すること。"""
    pipline_path = TRAINING_ROOT / "pipline.py"
    assert "upload_file_to_ftp" not in _imported_names(pipline_path)


def test_only_deploy_module_imports_ftp_upload_helper():
    """utils.ftp_common.upload_file_to_ftp を直接importしているのは
    deploy パッケージ内のみであること（境界の逆行を防ぐラチェット）。"""
    offenders = []
    for py_file in TRAINING_ROOT.rglob("*.py"):
        rel_parts = py_file.relative_to(TRAINING_ROOT).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if "upload_file_to_ftp" in _imported_names(py_file):
            offenders.append(str(py_file.relative_to(TRAINING_ROOT)))
    assert offenders == [], f"deploy外からのupload_file_to_ftp直接importを検出: {offenders}"


def test_pipline_does_not_import_model_export_internals_directly():
    """pipline.py は deploy.model_export を直接importしてはいけない。
    ONNXエクスポートは deploy モジュールの公開APIを経由すること。"""
    pipline_path = TRAINING_ROOT / "pipline.py"
    assert _imported_module_names(pipline_path).isdisjoint(INTERNAL_MODULES)


def test_only_deploy_module_imports_model_export_internals():
    """deploy.model_export を直接importしているのは
    deploy パッケージ内のみであること（境界の逆行を防ぐラチェット）。"""
    offenders = []
    for py_file in TRAINING_ROOT.rglob("*.py"):
        rel_parts = py_file.relative_to(TRAINING_ROOT).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if _imported_module_names(py_file) & INTERNAL_MODULES:
            offenders.append(str(py_file.relative_to(TRAINING_ROOT)))
    assert offenders == [], f"deploy外からのdeploy.model_export直接importを検出: {offenders}"
