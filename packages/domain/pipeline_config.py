# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

# -----------------------------
# Constants / schema keys
# -----------------------------

KEY_PATH = "path"
KEY_SCHEMA_VERSION = "schema_version"
KEY_RUN_ID = "run_id"
KEY_GENERATOR_VERSION = "generator_version"
KEY_INPUT_ROOT = "input_root"
KEY_SHA1 = "sha1"
KEY_HASH8 = "hash8"
KEY_FILE_MTIME = "file_mtime"
KEY_EXIF_DATETIME = "exif_datetime"
KEY_GPS_LAT = "gps_lat"
KEY_GPS_LON = "gps_lon"
KEY_WIDTH = "width"
KEY_HEIGHT = "height"
KEY_MIME = "mime"
KEY_MEDIA_TYPE = "media_type"
KEY_DURATION_S = "duration_s"
KEY_SAMPLE_RATE = "sample_rate"
KEY_CHANNELS = "channels"
KEY_BITRATE_KBPS = "bitrate_kbps"
KEY_TRANSCRIPT = "transcript"
KEY_TRANSCRIPT_LANG = "transcript_lang"
KEY_TRANSCRIPT_CONF = "transcript_confidence"
KEY_TRANSCRIPT_SEGMENTS = "transcript_segments"
KEY_AI = "ai"
KEY_ERROR = "error"
KEY_ERROR_CODE = "error_code"
KEY_NEW_PATH = "new_path"
KEY_STATUS = "status"
KEY_STATUS_REASON = "status_reason"
KEY_APPLIED_AT = "applied_at"

AI_KIND = "kind"
AI_CATEGORY = "category"
AI_TITLE = "title"
AI_TAGS = "tags"
AI_CONFIDENCE = "confidence"
AI_NOTES = "notes"

# Product semantic values remain localized Chinese for manifest/output compatibility.
CATEGORY_OTHER = "其他"

MEDIA_IMAGE = "image"
MEDIA_AUDIO = "audio"
MEDIA_PDF = "pdf"
MEDIA_DOCX = "docx"
MEDIA_DOC = "doc"
MEDIA_PPTX = "pptx"
MEDIA_PPT = "ppt"

DEFAULT_CATEGORIES = [
    "工作",
    "旅行",
    "美食",
    "收据",
    "文档",
    "聊天",
    "错误",
    "产品",
    "风景",
    "人物",
    CATEGORY_OTHER,
]

DEFAULT_INLINE_MAX_MB = 15.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_S = 1.0
DEFAULT_RETRY_MAX_S = 10.0
DEFAULT_AI_TIMEOUT_S = 60.0
DEFAULT_SUBPROCESS_TIMEOUT_S = 120.0
DEFAULT_MANIFEST_FSYNC_INTERVAL = 50
DEFAULT_DURABILITY = "batch"
DEFAULT_AUDIO_SEGMENT_THRESHOLD_S = 600.0
DEFAULT_AUDIO_SEGMENT_SECONDS = 30.0
DEFAULT_AUDIO_SEGMENT_COUNT = 3
DEFAULT_AUDIO_TRANSCRIPT_MAX_CHARS = 4000
DEFAULT_DOC_TEXT_MAX_CHARS = 6000
MAX_FILENAME_LENGTH = 240
DEFAULT_MAX_FILE_MB = 1024.0
DEFAULT_MAX_FILES = 0
DEFAULT_MAX_TOTAL_MB = 0.0
DEFAULT_CHUNK_SIZE = 500
MAX_CHUNK_SIZE = 10000
DEFAULT_WORKERS = 1
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_JSON = False

DEFAULT_WORKSPACE_ROOT = Path(os.environ.get("FILEORGANIZE_WORKSPACE_ROOT", "~/.fileorganize/workspaces/default")).expanduser()
DEFAULT_INPUT_DIR = DEFAULT_WORKSPACE_ROOT / "data" / "raw"
DEFAULT_OUTPUT_PARENT = DEFAULT_WORKSPACE_ROOT / "data" / "organized"

APP_NAME = "fileorganize"
# Keep this aligned with pyproject.toml [project].version until version loading is centralized.
APP_VERSION = "4.0.5"
MANIFEST_SCHEMA_VERSION = 2

IMAGE_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
}

AUDIO_EXTS = {
    ".wav",
    ".mp3",
    ".aiff",
    ".aif",
    ".aac",
    ".ogg",
    ".flac",
    ".m4a",
    ".opus",
    ".amr",
}

PDF_EXTS = {".pdf"}
DOCX_EXTS = {".docx"}
DOC_EXTS = {".doc"}
PPTX_EXTS = {".pptx"}
PPT_EXTS = {".ppt"}

RAW_MIME_ALLOWLIST = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

AUDIO_MIME_ALLOWLIST = {
    ".wav": "audio/wav",
    ".mp3": "audio/mp3",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".opus": "audio/ogg",
    ".amr": "audio/amr",
}

DOC_MIME_ALLOWLIST = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
}


class ImageKind(str, Enum):
    SCREENSHOT = "截图"
    PHOTO = "照片"
    AUDIO = "音频"
    DOCUMENT = "文档"


CATEGORY_COMPATIBILITY_ALIASES = {
    CATEGORY_OTHER: CATEGORY_OTHER,
    "other": CATEGORY_OTHER,
    "misc": CATEGORY_OTHER,
    "miscellaneous": CATEGORY_OTHER,
    "work": "工作",
    "travel": "旅行",
    "food": "美食",
    "receipt": "收据",
    "receipts": "收据",
    "document": "文档",
    "documents": "文档",
    "chat": "聊天",
    "error": "错误",
    "errors": "错误",
    "product": "产品",
    "scenery": "风景",
    "landscape": "风景",
    "people": "人物",
    "person": "人物",
}

KIND_COMPATIBILITY_ALIASES = {
    ImageKind.SCREENSHOT.value: ImageKind.SCREENSHOT.value,
    "截屏": ImageKind.SCREENSHOT.value,
    "screenshot": ImageKind.SCREENSHOT.value,
    "screen-shot": ImageKind.SCREENSHOT.value,
    "screen": ImageKind.SCREENSHOT.value,
    ImageKind.PHOTO.value: ImageKind.PHOTO.value,
    "photo": ImageKind.PHOTO.value,
    "image": ImageKind.PHOTO.value,
    "picture": ImageKind.PHOTO.value,
    "pic": ImageKind.PHOTO.value,
    ImageKind.AUDIO.value: ImageKind.AUDIO.value,
    "audio": ImageKind.AUDIO.value,
    "voice": ImageKind.AUDIO.value,
    "voicemail": ImageKind.AUDIO.value,
    "recording": ImageKind.AUDIO.value,
    "speech": ImageKind.AUDIO.value,
    ImageKind.DOCUMENT.value: ImageKind.DOCUMENT.value,
    "document": ImageKind.DOCUMENT.value,
    "doc": ImageKind.DOCUMENT.value,
    "docx": ImageKind.DOCUMENT.value,
    "pdf": ImageKind.DOCUMENT.value,
    "ppt": ImageKind.DOCUMENT.value,
    "pptx": ImageKind.DOCUMENT.value,
    "presentation": ImageKind.DOCUMENT.value,
    "slides": ImageKind.DOCUMENT.value,
    "file": ImageKind.DOCUMENT.value,
}


class Durability(str, Enum):
    NONE = "none"
    BATCH = "batch"
    SYNC = "sync"


class RowStatus(str, Enum):
    PENDING = "pending"
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"
    ERROR = "error"


class ErrorCode(str, Enum):
    INPUT_DIR_MISSING = "INPUT_DIR_MISSING"
    PROVIDER_CREDENTIAL_MISSING = "PROVIDER_CREDENTIAL_MISSING"
    MODEL_MISSING = "MODEL_MISSING"
    MANIFEST_READ_FAIL = "MANIFEST_READ_FAIL"
    MANIFEST_WRITE_FAIL = "MANIFEST_WRITE_FAIL"
    MANIFEST_UPDATE_FAIL = "MANIFEST_UPDATE_FAIL"
    MANIFEST_ROW_INVALID = "MANIFEST_ROW_INVALID"
    REPORT_WRITE_FAIL = "REPORT_WRITE_FAIL"
    OUTPUT_CREATE_FAIL = "OUTPUT_CREATE_FAIL"
    SOURCE_MISSING = "SOURCE_MISSING"
    SOURCE_MOVED = "SOURCE_MOVED"
    FILE_STAT_FAIL = "FILE_STAT_FAIL"
    INPUT_ROOT_INVALID = "INPUT_ROOT_INVALID"
    INPUT_ROOT_MISMATCH = "INPUT_ROOT_MISMATCH"
    HASH_MISSING = "HASH_MISSING"
    HASH_FAIL = "HASH_FAIL"
    HASH_MISMATCH = "HASH_MISMATCH"
    BUILD_DEST_FAIL = "BUILD_DEST_FAIL"
    MOVE_FAIL = "MOVE_FAIL"
    DEDUPE_PATH_FAIL = "DEDUPE_PATH_FAIL"
    DEDUPE_MOVE_FAIL = "DEDUPE_MOVE_FAIL"
    AUDIO_PREP_FAIL = "AUDIO_PREP_FAIL"
    AUDIO_TRANSCRIBE_FAIL = "AUDIO_TRANSCRIBE_FAIL"
    IMAGE_PREP_FAIL = "IMAGE_PREP_FAIL"
    DOC_PREP_FAIL = "DOC_PREP_FAIL"
    DOC_CONVERT_FAIL = "DOC_CONVERT_FAIL"
    AI_FAIL = "AI_FAIL"
    AI_TIMEOUT = "AI_TIMEOUT"
    DOC_CONVERT_TIMEOUT = "DOC_CONVERT_TIMEOUT"
    AUDIO_PREP_TIMEOUT = "AUDIO_PREP_TIMEOUT"
    EXIF_FAIL = "EXIF_FAIL"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    CSV_WRITE_FAIL = "CSV_WRITE_FAIL"
    CONFIG_INVALID = "CONFIG_INVALID"
    CONFIG_TYPE_INVALID = "CONFIG_TYPE_INVALID"
    CONFIG_UNKNOWN_KEY = "CONFIG_UNKNOWN_KEY"
    CONFIG_DEPRECATED = "CONFIG_DEPRECATED"
    OUTPUT_PATH_CONFLICT = "OUTPUT_PATH_CONFLICT"
    PREFLIGHT_LIMIT = "PREFLIGHT_LIMIT"
    ROLLBACK_FAIL = "ROLLBACK_FAIL"


def normalize_durability(value: str) -> Durability:
    if not value:
        return Durability.BATCH
    val = value.strip().lower()
    for item in Durability:
        if item.value == val:
            return item
    return Durability.BATCH


def resolve_fsync_interval(durability: str, fsync_interval: int) -> int:
    if fsync_interval is not None and int(fsync_interval) > 0:
        return int(fsync_interval)
    mode = normalize_durability(durability)
    if mode == Durability.NONE:
        return 0
    if mode == Durability.SYNC:
        return 1
    return DEFAULT_MANIFEST_FSYNC_INTERVAL
