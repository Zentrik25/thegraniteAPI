"""
storage.py — Storage backend configuration.

Development:  files saved to MEDIA_ROOT (local disk)
Production:   files uploaded to S3 or Cloudflare R2 via django-storages

To switch to S3/R2 in production add these to your .env:

    USE_S3=true
    AWS_ACCESS_KEY_ID=your_key
    AWS_SECRET_ACCESS_KEY=your_secret
    AWS_STORAGE_BUCKET_NAME=your_bucket
    AWS_S3_REGION_NAME=auto              # use 'auto' for Cloudflare R2
    AWS_S3_ENDPOINT_URL=https://your-account.r2.cloudflarestorage.com
    AWS_S3_CUSTOM_DOMAIN=cdn.thegranite.co.zw

Then in config/settings.py add:

    import os
    if os.environ.get("USE_S3") == "true":
        from media_assets.storage import configure_s3
        configure_s3()
"""

import os


def configure_s3():
    """
    Configure django-storages to use S3 or Cloudflare R2.
    Call this from settings.py when USE_S3=true.
    """
    from django.conf import settings

    settings.DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

    settings.AWS_ACCESS_KEY_ID        = os.environ.get("AWS_ACCESS_KEY_ID", "")
    settings.AWS_SECRET_ACCESS_KEY    = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    settings.AWS_STORAGE_BUCKET_NAME  = os.environ.get("AWS_STORAGE_BUCKET_NAME", "")
    settings.AWS_S3_REGION_NAME       = os.environ.get("AWS_S3_REGION_NAME", "auto")
    settings.AWS_S3_ENDPOINT_URL      = os.environ.get("AWS_S3_ENDPOINT_URL", "")
    settings.AWS_S3_CUSTOM_DOMAIN     = os.environ.get("AWS_S3_CUSTOM_DOMAIN", "")
    settings.AWS_DEFAULT_ACL          = "public-read"
    settings.AWS_S3_FILE_OVERWRITE    = False
    settings.AWS_QUERYSTRING_AUTH     = False

    # Cache control — tell browsers and CDN to cache images for 1 year.
    settings.AWS_S3_OBJECT_PARAMETERS = {
        "CacheControl": "max-age=31536000",
    }
