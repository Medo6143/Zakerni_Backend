import pytest
from django.contrib.admin.sites import site
from django.test import Client, RequestFactory

from apps.accounts.models import User
from apps.accounts.services.device_auth import hash_device_secret
from apps.accounts.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_reset_device_binding_action_clears_the_hash() -> None:
    admin_user = UserFactory(is_staff=True, is_superuser=True)
    bound = UserFactory(device_secret_hash=hash_device_secret("s" * 40))
    other = UserFactory(device_secret_hash=hash_device_secret("t" * 40))
    client = Client()
    client.force_login(admin_user)

    response = client.post(
        "/admin/accounts/user/",
        {"action": "reset_device_binding", "_selected_action": [str(bound.pk)]},
        follow=True,
    )

    assert response.status_code == 200
    bound.refresh_from_db()
    other.refresh_from_db()
    assert bound.device_secret_hash == ""
    assert bound.device_bound_at is None
    assert other.device_secret_hash != ""


def test_action_is_registered_and_hash_is_not_shown() -> None:
    model_admin = site._registry[User]
    assert "reset_device_binding" in model_admin.actions
    request = RequestFactory().get("/admin/accounts/user/")
    request.user = UserFactory(is_staff=True, is_superuser=True)
    fields = {f for _, opts in model_admin.get_fieldsets(request) for f in opts["fields"]}
    assert "device_secret_hash" not in fields
