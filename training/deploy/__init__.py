# training/deploy/__init__.py
"""deployステージの公開API。

deployパッケージ外からは `deploy.upload_model` のみを使用すること。
`deploy.ftp_upload.upload_model_to_host` 等の内部関数を外部から
直接importしてはならない（境界はtests/ci_gates/test_deploy_boundary.pyで検証）。
"""
from deploy.ftp_upload import upload_model

__all__ = ["upload_model"]
