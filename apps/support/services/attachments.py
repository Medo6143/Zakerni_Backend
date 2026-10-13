"""Validation of report attachments (images only)."""

from __future__ import annotations

from collections.abc import Sequence

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.utils.translation import gettext_lazy as _
from PIL import Image, UnidentifiedImageError

from apps.core.exceptions import ValidationAppError

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


def validate_report_attachments(files: Sequence[UploadedFile]) -> None:
    """Images only (JPEG/PNG/WEBP), at most 3 files, 5 MB each."""
    max_files = settings.REPORT_MAX_ATTACHMENTS
    max_bytes = settings.REPORT_MAX_ATTACHMENT_BYTES
    if len(files) > max_files:
        raise ValidationAppError(
            details={"attachments": [str(_("You can attach up to 3 images."))]}
        )
    for upload in files:
        if upload.size is None or upload.size > max_bytes:
            raise ValidationAppError(
                details={"attachments": [str(_("Each image must be 5 MB or smaller."))]}
            )
        try:
            upload.seek(0)
            with Image.open(upload) as image:
                image_format = image.format
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
            raise ValidationAppError(
                details={"attachments": [str(_("Only image files can be attached."))]}
            ) from exc
        finally:
            upload.seek(0)
        if image_format not in ALLOWED_IMAGE_FORMATS:
            raise ValidationAppError(
                details={"attachments": [str(_("Only image files can be attached."))]}
            )
