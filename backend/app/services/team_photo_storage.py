"""Process team photographs and store the official JPEG in Cloudflare R2.

Unselected pictures stay in the browser. This module never writes a permanent
copy to local disk, and it does not fall back to disk when R2 is unavailable.
"""

from __future__ import annotations

import io
import os
import time

from PIL import Image, ImageOps

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_EDGE = 4096
JPEG_QUALITY = 98
THUMB_EDGE = 480


def register_heif_support() -> bool:
    """Allow Pillow to read iPhone HEIC/HEIF files when the decoder is installed."""
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
        return True
    except Exception:
        return False


register_heif_support()


class PhotoRejected(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class PhotoStorageUnavailable(Exception):
    def __init__(self, message: str = "Team photograph storage is unavailable"):
        super().__init__(message)


def process_image(raw: bytes) -> bytes:
    """Store the camera JPEG as-is when it already fits.

    A second JPEG encode is what makes an upload look grainy next to the
    original. Rotate or shrink only when the file needs it, and do that once.
    """
    if not raw:
        raise PhotoRejected("Photograph file is empty")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise PhotoRejected("Photograph is too large", status_code=413)
    try:
        image = Image.open(io.BytesIO(raw))
        image.seek(0)
        # Keep the camera JPEG itself. Rewriting it, including to honor a
        # rotation tag, is what made the preview look grainy.
        if image.format == "JPEG" and image.mode in {"RGB", "L"}:
            return raw
        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True, subsampling=0)
    except PhotoRejected:
        raise
    except Exception as exc:
        raise PhotoRejected(
            "Photograph could not be read. Use a JPEG, PNG, or HEIC photo from the camera or library."
        ) from exc
    data = out.getvalue()
    if not data:
        raise PhotoRejected("Photograph could not be saved")
    return data


def make_display_thumbnail(raw: bytes) -> bytes:
    """Small JPEG for Check-In Desk and Score Entry. The original bytes are not changed."""
    if not raw:
        raise PhotoRejected("Photograph file is empty")
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.thumbnail((THUMB_EDGE, THUMB_EDGE), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=75, optimize=True)
    except Exception as exc:
        raise PhotoRejected("Photograph thumbnail could not be created") from exc
    data = out.getvalue()
    if not data:
        raise PhotoRejected("Photograph thumbnail could not be created")
    return data


def display_thumb_key(storage_key: str) -> str | None:
    if not storage_key.endswith(".jpg") or storage_key.endswith("-thumb.jpg") or ".." in storage_key:
        return None
    return storage_key[:-4] + "-thumb.jpg"


def load_display_thumb(storage_key: str) -> bytes:
    """Return the small stored thumbnail. Never open the camera file here."""
    thumb_key = display_thumb_key(storage_key)
    if not thumb_key:
        raise FileNotFoundError(storage_key)
    return get_object_store().get_bytes(thumb_key)


_PRESIGN_SECONDS = 7 * 24 * 3600
_PRESIGN_REUSE_SECONDS = 24 * 3600
_presign_cache: dict[str, tuple[str, float]] = {}


_cors_next_try = 0.0
_cors_error: str | None = None


def reset_presign_cache() -> None:
    global _cors_next_try, _cors_error
    _presign_cache.clear()
    _cors_next_try = 0.0
    _cors_error = None


def _original_photo_key(storage_key: str) -> bool:
    if not storage_key or ".." in storage_key or "\\" in storage_key:
        return False
    return storage_key.startswith("team-photos/") and storage_key.endswith(".jpg") and not storage_key.endswith("-thumb.jpg")


def presigned_file_urls(storage_keys: list[str]) -> dict[str, str | None]:
    """Direct links for the camera files. Signing does not download them."""
    urls: dict[str, str | None] = {}
    store = None
    now = time.monotonic()
    for storage_key in storage_keys:
        if not _original_photo_key(storage_key):
            urls[storage_key] = None
            continue
        cached = _presign_cache.get(storage_key)
        if cached and cached[1] - now > _PRESIGN_REUSE_SECONDS:
            urls[storage_key] = cached[0]
            continue
        if store is None:
            store = get_object_store()
        presign = getattr(store, "presigned_get_url", None)
        if not callable(presign):
            urls[storage_key] = None
            continue
        try:
            url = presign(storage_key, _PRESIGN_SECONDS)
        except Exception:
            url = None
        if not url:
            urls[storage_key] = None
            continue
        _presign_cache[storage_key] = (url, now + _PRESIGN_SECONDS)
        urls[storage_key] = url
    return urls


def _public_storage_error(exc: Exception) -> str:
    cause = exc.__cause__ or exc
    response = getattr(cause, "response", None)
    if isinstance(response, dict):
        error = response.get("Error") or {}
        code = str(error.get("Code") or "").strip()
        message = str(error.get("Message") or "").strip()
        text = ": ".join(part for part in (code, message) if part)
        if text:
            return text[:240]
    return str(cause)[:240]


def allow_browser_downloads() -> str | None:
    """Let the laptop read a signed photograph. The bytes stay in storage."""
    global _cors_next_try, _cors_error
    now = time.monotonic()
    if now < _cors_next_try:
        return _cors_error
    store = get_object_store()
    allow = getattr(store, "allow_browser_downloads", None)
    if not callable(allow):
        _cors_error = None
        _cors_next_try = float("inf")
        return None
    try:
        allow()
    except Exception as exc:
        _cors_error = _public_storage_error(exc)
        _cors_next_try = now + 60
        return _cors_error
    _cors_error = None
    _cors_next_try = float("inf")
    return None


def presigned_display_url(storage_key: str) -> str | None:
    """Direct storage link for the thumbnail. None when this store cannot sign one."""
    thumb_key = display_thumb_key(storage_key)
    if not thumb_key:
        return None
    now = time.monotonic()
    cached = _presign_cache.get(thumb_key)
    if cached and cached[1] - now > _PRESIGN_REUSE_SECONDS:
        return cached[0]
    store = get_object_store()
    presign = getattr(store, "presigned_get_url", None)
    if not callable(presign):
        return None
    try:
        url = presign(thumb_key, _PRESIGN_SECONDS)
    except Exception:
        return None
    if not url:
        return None
    _presign_cache[thumb_key] = (url, now + _PRESIGN_SECONDS)
    return url


def display_thumb_response(storage_key: str):
    """Send the stored thumbnail. A direct link keeps the bytes out of this server."""
    from fastapi.responses import RedirectResponse, Response

    url = presigned_display_url(storage_key)
    if url:
        return RedirectResponse(
            url,
            status_code=302,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    data = load_display_thumb(storage_key)
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def official_object_key(tournament_id: int, team_id: int, unique_id: str) -> str:
    safe = "".join(ch for ch in unique_id if ch.isalnum() or ch in {"-", "_"})[:80]
    if len(safe) < 8:
        raise PhotoRejected("client_upload_id is invalid")
    return f"team-photos/{int(tournament_id)}/{int(team_id)}/{safe}.jpg"


def group_object_key(tournament_id: int, unique_id: str) -> str:
    """High-resolution group photograph. The path is not a team id."""
    safe = "".join(ch for ch in unique_id if ch.isalnum() or ch in {"-", "_"})[:80]
    if len(safe) < 8:
        raise PhotoRejected("client_upload_id is invalid")
    return f"team-photos/{int(tournament_id)}/groups/{safe}.jpg"


def owned_group_key(tournament_id: int, storage_key: str) -> bool:
    prefix = f"team-photos/{int(tournament_id)}/groups/"
    if not storage_key.startswith(prefix) or ".." in storage_key:
        return False
    remainder = storage_key[len(prefix):]
    return bool(remainder) and "/" not in remainder and remainder.endswith(".jpg")


class MemoryObjectStore:
    """In-process store used by tests. It is not a disk fallback."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_next_put = False
        self.fail_next_delete = False

    def put_jpeg(self, key: str, data: bytes, content_type: str = "image/jpeg", cache_control: str | None = None) -> None:
        del cache_control
        if self.fail_next_put:
            self.fail_next_put = False
            raise PhotoStorageUnavailable("Team photograph storage is unavailable")
        self.objects[key] = data

    def head_size(self, key: str) -> int:
        if key not in self.objects:
            raise FileNotFoundError(key)
        return len(self.objects[key])

    def get_bytes(self, key: str) -> bytes:
        if key not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[key]

    def get_prefix(self, key: str, limit: int = 262144) -> bytes:
        return self.get_bytes(key)[:limit]

    def delete(self, key: str | None) -> None:
        if self.fail_next_delete:
            self.fail_next_delete = False
            raise PhotoStorageUnavailable("Team photograph storage delete failed")
        if key:
            self.objects.pop(key, None)


_memory_store = MemoryObjectStore()


def reset_memory_store() -> None:
    global _cors_next_try, _cors_error
    _memory_store.objects.clear()
    _memory_store.fail_next_put = False
    _memory_store.fail_next_delete = False
    _presign_cache.clear()
    _cors_next_try = 0.0
    _cors_error = None


def arm_next_put_failure() -> None:
    _memory_store.fail_next_put = True


def arm_next_delete_failure() -> None:
    _memory_store.fail_next_delete = True


class R2ObjectStore:
    def __init__(self, client, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    @classmethod
    def from_env(cls) -> "R2ObjectStore":
        bucket = os.getenv("TEAM_PHOTO_R2_BUCKET", "").strip()
        access_key = os.getenv("R2_ACCESS_KEY_ID", "").strip()
        secret = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
        endpoint = os.getenv("R2_ENDPOINT", "").strip()
        region = os.getenv("R2_REGION", "auto").strip() or "auto"
        backup_bucket = os.getenv("R2_BUCKET", "").strip()
        if not bucket or not access_key or not secret or not endpoint:
            raise PhotoStorageUnavailable(
                "Team photo storage is not configured. Set TEAM_PHOTO_R2_BUCKET, "
                "R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, and R2_ENDPOINT."
            )
        if backup_bucket and bucket == backup_bucket:
            raise PhotoStorageUnavailable(
                "Team photographs cannot be stored in the database backup bucket"
            )
        try:
            import boto3
        except ImportError as exc:
            raise PhotoStorageUnavailable("Team photo storage client is not installed") from exc
        from botocore.config import Config

        base = {
            "connect_timeout": 3,
            "read_timeout": 8,
            "retries": {"max_attempts": 1},
            "signature_version": "s3v4",
        }
        try:
            config = Config(
                **base,
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            )
        except TypeError:
            config = Config(**base)
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret,
            region_name=region,
            config=config,
        )
        return cls(client, bucket)

    def put_jpeg(self, key: str, data: bytes, content_type: str = "image/jpeg", cache_control: str | None = None) -> None:
        extra = {"CacheControl": cache_control} if cache_control else {}
        self._call(
            "upload",
            lambda: self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                **extra,
            ),
        )

    def presigned_get_url(self, key: str, expires_in: int) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=int(expires_in),
        )

    def allow_browser_downloads(self) -> None:
        self._call(
            "prepare",
            lambda: self.client.put_bucket_cors(
                Bucket=self.bucket,
                CORSConfiguration={
                    "CORSRules": [
                        {
                            "AllowedOrigins": ["*"],
                            "AllowedMethods": ["GET", "HEAD"],
                            "AllowedHeaders": ["*"],
                            "ExposeHeaders": ["Content-Length", "Content-Type", "ETag"],
                            "MaxAgeSeconds": 86400,
                        }
                    ]
                },
            ),
        )

    def head_size(self, key: str) -> int:
        response = self._call("verify", lambda: self.client.head_object(Bucket=self.bucket, Key=key))
        size = response.get("ContentLength")
        if size is None:
            raise PhotoStorageUnavailable("Uploaded photograph could not be verified")
        return int(size)

    def get_bytes(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if _missing_object(exc):
                raise FileNotFoundError(key) from exc
            raise PhotoStorageUnavailable("Team photograph storage is unavailable") from exc
        body = response["Body"].read()
        return body

    def get_prefix(self, key: str, limit: int = 262144) -> bytes:
        try:
            response = self.client.get_object(
                Bucket=self.bucket,
                Key=key,
                Range=f"bytes=0-{max(0, limit - 1)}",
            )
        except Exception as exc:
            if _missing_object(exc):
                raise FileNotFoundError(key) from exc
            raise PhotoStorageUnavailable("Team photograph storage is unavailable") from exc
        return response["Body"].read()

    def delete(self, key: str | None) -> None:
        if not key:
            return
        self._call("delete", lambda: self.client.delete_object(Bucket=self.bucket, Key=key))

    def _call(self, action: str, operation):
        try:
            return operation()
        except PhotoStorageUnavailable:
            raise
        except Exception as exc:
            raise PhotoStorageUnavailable(f"Team photograph storage {action} failed") from exc


def _missing_object(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    code = (response.get("Error") or {}).get("Code")
    return code in {"404", "NoSuchKey", "NotFound"}


def get_object_store():
    mode = os.getenv("TEAM_PHOTO_OBJECT_STORE", "r2").strip().lower()
    if mode == "memory":
        return _memory_store
    if mode == "r2":
        return R2ObjectStore.from_env()
    raise PhotoStorageUnavailable("Team photo storage is not configured")
