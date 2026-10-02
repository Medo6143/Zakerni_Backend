"""Media storage backed by Cloudinary (production, when ``CLOUDINARY_URL`` is set).

A small ``Storage`` over the official ``cloudinary`` SDK (maintained by Cloudinary,
no Django version pin). The SDK reads ``CLOUDINARY_URL`` from the environment itself,
so no credential ever passes through settings or logs. Files are uploaded as private
images whose public id is the Django file name without extension, under ``folder``.
Validation (type, size, count) stays in the serializers and is unchanged.
"""

from __future__ import annotations

import posixpath
from typing import Any

from django.core.files.base import File
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class CloudinaryMediaStorage(Storage):
    def __init__(self, folder: str = "zakerni") -> None:
        self._folder = folder.strip("/")

    def _public_id(self, name: str) -> str:
        stem = posixpath.splitext(name.replace("\\", "/"))[0]
        return f"{self._folder}/{stem}" if self._folder else stem

    def _save(self, name: str, content: File) -> str:
        import cloudinary.uploader

        content.seek(0)
        cloudinary.uploader.upload(
            content,
            public_id=self._public_id(name),
            resource_type="image",
            overwrite=False,
        )
        return name

    def _open(self, name: str, mode: str = "rb") -> File:
        import io

        import httpx

        response = httpx.get(self.url(name), timeout=10.0)
        response.raise_for_status()
        return File(io.BytesIO(response.content), name=name)

    def delete(self, name: str) -> None:
        import cloudinary.uploader

        cloudinary.uploader.destroy(self._public_id(name), resource_type="image")

    def exists(self, name: str) -> bool:
        import cloudinary.api
        from cloudinary.exceptions import NotFound

        try:
            cloudinary.api.resource(self._public_id(name), resource_type="image")
        except NotFound:
            return False
        return True

    def url(self, name: str | None) -> str:
        import cloudinary

        ext = posixpath.splitext(name or "")[1].lstrip(".") or None
        options: dict[str, Any] = {"secure": True, "resource_type": "image"}
        if ext:
            options["format"] = ext
        return str(cloudinary.CloudinaryImage(self._public_id(name or "")).build_url(**options))

    def size(self, name: str) -> int:
        import cloudinary.api

        return int(cloudinary.api.resource(self._public_id(name), resource_type="image")["bytes"])
