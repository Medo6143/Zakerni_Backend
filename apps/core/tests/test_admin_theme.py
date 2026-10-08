"""Admin theme (Unfold restyle): login, dashboard, custom CSS, fonts, sidebar settings."""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import Client, override_settings

from apps.accounts.tests.factories import UserFactory

CSS_PATH = "admin/zakerni.css"
FONT_FILES = [
    "IBMPlexSansArabic_400Regular.ttf",
    "IBMPlexSansArabic_500Medium.ttf",
    "IBMPlexSansArabic_600SemiBold.ttf",
    "IBMPlexSansArabic_700Bold.ttf",
]


@pytest.fixture
def admin_client(db) -> Client:
    client = Client()
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("lang", ["en", "ar"])
def test_login_page_renders_branded(lang: str) -> None:
    response = Client().get("/admin/login/", HTTP_ACCEPT_LANGUAGE=lang)

    assert response.status_code == 200
    content = response.content.decode()
    assert "zakerni.css" in content
    assert "zk-login__hero" in content
    assert "logo-mark-white.svg" in content
    assert "csrfmiddlewaretoken" in content
    assert 'name="username"' in content and 'name="password"' in content
    assert ('dir="rtl"' in content) is (lang == "ar")


@pytest.mark.django_db
@pytest.mark.parametrize("lang", ["en", "ar"])
def test_dashboard_renders_cards_and_quick_actions(admin_client: Client, lang: str) -> None:
    response = admin_client.get("/admin/", HTTP_ACCEPT_LANGUAGE=lang)

    assert response.status_code == 200
    content = response.content.decode()
    assert "zakerni.css" in content
    assert content.count("zk-kpi__value") == 6
    assert "/admin/support/report/" in content and "/admin/broadcasts/broadcast/" in content
    assert "/admin/accounts/user/" in content
    assert 'data-type="bar"' in content


@pytest.mark.django_db
def test_sidebar_lists_apps_with_working_links(admin_client: Client) -> None:
    content = admin_client.get("/admin/").content.decode()

    for link in ("/admin/accounts/user/", "/admin/schedule/course/", "/admin/sis/sisaccount/"):
        assert link in content


def test_unfold_settings_are_complete() -> None:
    unfold = settings.UNFOLD
    scale = unfold["COLORS"]["primary"]

    assert list(scale) == [
        "50",
        "100",
        "200",
        "300",
        "400",
        "500",
        "600",
        "700",
        "800",
        "900",
        "950",
    ]
    assert scale["600"] == "79 70 229"  # #4F46E5, the brand indigo
    assert all(re.fullmatch(r"\d{1,3} \d{1,3} \d{1,3}", v) for v in scale.values())
    assert len(unfold["SIDEBAR"]["navigation"]) >= 6
    assert len(unfold["STYLES"]) == 1


def test_theme_files_exist() -> None:
    static = Path(settings.BASE_DIR) / "static"
    assert (static / CSS_PATH).is_file()
    assert (static / "fonts" / "OFL.txt").is_file()
    for font in FONT_FILES:
        assert (static / "fonts" / font).is_file()
    assert (static / "brand" / "logo-mark-white.svg").is_file()


def test_collectstatic_includes_css_and_fonts(tmp_path: Path) -> None:
    with override_settings(STATIC_ROOT=str(tmp_path)):
        call_command("collectstatic", interactive=False, verbosity=0)

    assert (tmp_path / CSS_PATH).is_file()
    for font in FONT_FILES:
        assert (tmp_path / "fonts" / font).is_file()
    assert (tmp_path / "brand" / "logo-icon.svg").is_file()
