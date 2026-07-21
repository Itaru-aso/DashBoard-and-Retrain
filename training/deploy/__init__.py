"""deployステージの公開API。

deployパッケージ外からは `deploy.upload_model` / `deploy.export_model` のみを
使用すること。`deploy.ftp_upload` / `deploy.model_export` 内の関数を外部から
直接importしてはならない（境界はtests/ci_gates/test_deploy_boundary.pyで検証）。
"""
from deploy.ftp_upload import upload_model
from deploy.model_export import export_model

__all__ = ["upload_model", "export_model"]
