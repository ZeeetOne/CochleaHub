"""Mesh storage on S3 (D8). The same code targets Amazon S3 or a local S3-compatible
store; only `S3_ENDPOINT_URL` differs."""

from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from cochleahub.config import settings


class ObjectStore:
    def __init__(self, bucket: str | None = None):
        self.bucket = bucket or settings.s3_mesh_bucket
        self.client = boto3.client(
            "s3",
            region_name=settings.aws_region,
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            kwargs = {}
            if not settings.s3_endpoint_url and settings.aws_region != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": settings.aws_region}
            self.client.create_bucket(Bucket=self.bucket, **kwargs)

    def upload(self, path: Path, key: str, content_type: str = "model/gltf-binary") -> str:
        self.client.upload_file(str(path), self.bucket, key, ExtraArgs={"ContentType": content_type})
        return key

    def presigned_url(self, key: str, expires_s: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_s
        )
