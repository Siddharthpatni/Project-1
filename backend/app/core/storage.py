"""
S3 / MinIO object-storage wrapper.

Small abstraction so the rest of the code does not depend on boto3
directly. Also makes testing easier — swap `ObjectStorage` with a local
filesystem implementation and nothing else changes.
"""
from __future__ import annotations

from dataclasses import dataclass

import boto3
from botocore.client import Config

from app.config import settings
from app.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class StoredObject:
    key: str
    size: int
    url: str


class ObjectStorage:
    def __init__(self):
        self._s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.minio_root_user,
            aws_secret_access_key=settings.minio_root_password,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4"),
        )
        self.bucket = settings.s3_bucket
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._s3.head_bucket(Bucket=self.bucket)
        except Exception:
            try:
                self._s3.create_bucket(Bucket=self.bucket)
                log.info("storage.bucket_created", bucket=self.bucket)
            except Exception as e:  # noqa: BLE001
                log.warning("storage.bucket_create_failed", error=str(e))

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return StoredObject(key=key, size=len(data), url=self.presign(key))

    def get(self, key: str) -> bytes:
        resp = self._s3.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()

    def presign(self, key: str, expires: int = 3600) -> str:
        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires,
        )

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=key)
