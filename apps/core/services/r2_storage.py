"""Cloudflare R2 storage — upload clips and return accessible URLs."""
import logging
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig
from django.conf import settings

logger = logging.getLogger(__name__)

# R2 supports presigned URLs up to 7 days. We use 24h to give the
# distributor task ample retry window (max 1h).
_PRESIGNED_EXPIRY = 86400  # 24 hours


def _get_r2_client():
    """Build a boto3 S3 client pointing at Cloudflare R2."""
    endpoint = getattr(settings, "R2_ENDPOINT", None)
    access_key = getattr(settings, "R2_ACCESS_KEY_ID", None)
    secret_key = getattr(settings, "R2_SECRET_ACCESS_KEY", None)

    if not all([endpoint, access_key, secret_key]):
        raise RuntimeError("R2 credentials not configured (R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY)")

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=BotoConfig(
            region_name="auto",
            s3={"addressing_style": "path"},
        ),
    )


def upload_clip(file_path: str, bucket: str | None = None, key_prefix: str = "clips") -> str:
    """
    Upload a clip file to R2 and return its public URL.

    Args:
        file_path: Local path to the MP4 file.
        bucket: R2 bucket name (defaults to settings.R2_BUCKET_NAME).
        key_prefix: Prefix (folder) inside the bucket.

    Returns:
        Publicly accessible URL for the uploaded file.
    """
    if bucket is None:
        bucket = getattr(settings, "R2_BUCKET_NAME", "tiktok-clips")

    r2 = _get_r2_client()
    filename = Path(file_path).name
    key = f"{key_prefix}/{filename}"

    logger.info("Uploading %s to R2 bucket %s/%s ...", filename, bucket, key)

    r2.upload_file(
        file_path,
        bucket,
        key,
        ExtraArgs={"ContentType": "video/mp4"},
    )

    # Prefer a custom public domain, else fall back to presigned URL
    public_domain = getattr(settings, "R2_PUBLIC_DOMAIN", None)
    if public_domain:
        url = f"{public_domain.rstrip('/')}/{key}"
    else:
        url = r2.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=_PRESIGNED_EXPIRY,
        )

    logger.info("Upload complete. URL: %s", url)
    return url


def cleanup_old_clips(bucket: str | None = None, key_prefix: str = "clips") -> int:
    """
    Delete all clip objects from R2 under the given prefix.

    Runs daily via Celery Beat to keep storage usage low.

    Args:
        bucket: R2 bucket name (defaults to settings.R2_BUCKET_NAME).
        key_prefix: Prefix (folder) to clean up.

    Returns:
        Number of objects deleted.
    """
    if bucket is None:
        bucket = getattr(settings, "R2_BUCKET_NAME", "tiktok-clips")

    r2 = _get_r2_client()
    deleted = 0

    paginator = r2.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket, Prefix=f"{key_prefix}/")

    for page in pages:
        objects = page.get("Contents", [])
        if not objects:
            continue

        keys = [{"Key": obj["Key"]} for obj in objects]
        r2.delete_objects(
            Bucket=bucket,
            Delete={"Objects": keys, "Quiet": True},
        )
        deleted += len(keys)
        logger.info("Deleted %d objects from R2 %s/%s/", len(keys), bucket, key_prefix)

    logger.info("R2 cleanup complete: %d total objects deleted from %s/%s/", deleted, bucket, key_prefix)
    return deleted
