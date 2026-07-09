"""
S3 / MinIO object-storage wrapper.

Small abstraction so the rest of the code does not depend on boto3
directly. Also makes testing easier — swap `ObjectStorage` with a local
filesystem implementation and nothing else changes.

Resilient to MinIO being unavailable: connection errors are tolerated
at construction time so the API/worker can still start. When `put` /
`get` are called against a dead MinIO, the error surfaces there and
the pipeline marks the affected file with a warning rather than
aborting the whole job.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

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
            config=Config(
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=10,
                retries={"max_attempts": 1},
            ),
        )
        self.bucket = settings.s3_bucket
        self._available: bool | None = None
        self._local_fallback_dir = Path(settings.downloads_dir) / "_s3_fallback"
        # Best-effort bucket creation. Don't crash if MinIO is down —
        # we'll discover that on the first real put/get and fall back
        # to local disk.
        self._ensure_bucket()

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _ensure_bucket(self) -> None:
        try:
            self._s3.head_bucket(Bucket=self.bucket)
            self._available = True
        except (EndpointConnectionError, ClientError, BotoCoreError) as e:
            try:
                self._s3.create_bucket(Bucket=self.bucket)
                log.info("storage.bucket_created", bucket=self.bucket)
                self._available = True
            except Exception as e2:  # noqa: BLE001
                log.warning(
                    "storage.unavailable_using_local_fallback",
                    error=str(e2),
                    head_error=str(e),
                )
                self._available = False
                try:
                    self._local_fallback_dir.mkdir(parents=True, exist_ok=True)
                except Exception as e3:
                    log.warning("storage.local_fallback_mkdir_failed", error=str(e3))

    def _local_path(self, key: str) -> Path:
        # Sanitise: keep slashes as path separators, drop any traversal.
        safe = key.replace("..", "_")
        path = self._local_fallback_dir / safe
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def put(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredObject:
        if self._available:
            try:
                self._s3.put_object(
                    Bucket=self.bucket, Key=key, Body=data, ContentType=content_type,
                )
                return StoredObject(key=key, size=len(data), url=self.presign(key))
            except (EndpointConnectionError, ClientError, BotoCoreError) as e:
                log.warning("storage.put_failed_falling_back", key=key, error=str(e))
                self._available = False

        # local fallback
        path = self._local_path(key)
        path.write_bytes(data)
        return StoredObject(key=key, size=len(data), url=f"file://{path}")

    def get(self, key: str) -> bytes:
        if self._available:
            try:
                resp = self._s3.get_object(Bucket=self.bucket, Key=key)
                return resp["Body"].read()
            except (EndpointConnectionError, ClientError, BotoCoreError) as e:
                log.warning("storage.get_failed_trying_local", key=key, error=str(e))
        # fallback
        path = self._local_path(key)
        if path.exists():
            return path.read_bytes()
        raise FileNotFoundError(f"object not found in S3 or fallback: {key}")

    def presign(self, key: str, expires: int = 3600) -> str:
        if self._available:
            try:
                return self._s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=expires,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("storage.presign_failed", key=key, error=str(e))
        return f"file://{self._local_path(key)}"

    def delete(self, key: str) -> None:
        if self._available:
            try:
                self._s3.delete_object(Bucket=self.bucket, Key=key)
                return
            except Exception as e:  # noqa: BLE001
                log.warning("storage.delete_failed", key=key, error=str(e))
        path = self._local_path(key)
        if path.exists():
            try:
                os.remove(path)
            except OSError as e:
                log.debug("storage.local_delete_failed", key=key, error=str(e))
