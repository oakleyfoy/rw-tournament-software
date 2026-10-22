"""Process team photographs and store the official JPEG in Cloudflare R2.

Unselected pictures stay in the browser. This module never writes a permanent
copy to local disk, and it does not fall back to disk when R2 is unavailable.
"""

from __future__ import annotations

import io
import os

from PIL import Image, ImageOps

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_EDGE = 4096
JPEG_QUALITY = 95
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
        orientation = 1
        exif = image.getexif()
        if exif:
            orientation = int(exif.get(274, 1) or 1)
        if (
            image.format == "JPEG"
            and orientation == 1
            and image.mode in {"RGB", "L"}
            and max(image.size) <= MAX_EDGE
        ):
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


def official_object_key(tournament_id: int, team_id: int, unique_id: str) -> str:
    safe = "".join(ch for ch in unique_id if ch.isalnum() or ch in {"-", "_"})[:80]
    if len(safe) < 8:
        raise PhotoRejected("client_upload_id is invalid")
    return f"team-photos/{int(tournament_id)}/{int(team_id)}/{safe}.jpg"


class MemoryObjectStore:
    """In-process store used by tests. It is not a disk fallback."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_next_put = False
        self.fail_next_delete = False

    def put_jpeg(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
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

    def delete(self, key: str | None) -> None:
        if self.fail_next_delete:
            self.fail_next_delete = False
            raise PhotoStorageUnavailable("Team photograph storage delete failed")
        if key:
            self.objects.pop(key, None)


_memory_store = MemoryObjectStore()


def reset_memory_store() -> None:
    _memory_store.objects.clear()
    _memory_store.fail_next_put = False
    _memory_store.fail_next_delete = False


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
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret,
            region_name=region,
        )
        return cls(client, bucket)

    def put_jpeg(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        self._call(
            "upload",
            lambda: self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
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
