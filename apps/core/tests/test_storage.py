from django.core.files.storage import FileSystemStorage, storages

from apps.core.storage import CloudinaryMediaStorage


def test_tests_use_local_storage() -> None:
    assert isinstance(storages["default"], FileSystemStorage)


def test_cloudinary_public_id_and_url(monkeypatch) -> None:
    monkeypatch.setenv("CLOUDINARY_URL", "cloudinary://key:secret@demo")
    import cloudinary

    cloudinary.reset_config()
    storage = CloudinaryMediaStorage(folder="zakerni")

    name = "reports/2026/10/abc.png"
    assert storage._public_id(name) == "zakerni/reports/2026/10/abc"
    url = storage.url(name)
    assert url.startswith("https://res.cloudinary.com/demo/image/upload/")
    assert url.endswith("zakerni/reports/2026/10/abc.png")
    assert "secret" not in url
