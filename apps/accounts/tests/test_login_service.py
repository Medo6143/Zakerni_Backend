import pytest

from apps.accounts.models import User
from apps.accounts.services.auth import LoginWithLms
from apps.core.exceptions import InvalidLmsCredentials, LmsUnavailable
from apps.moodle.integrations.fake_client import FakeMoodleClient
from apps.moodle.models import MoodleAccount
from apps.moodle.protocols import SiteInfo


def _client_with_user(username="student1", password="secret", moodle_user_id=42):
    client = FakeMoodleClient()
    client.add_user(
        username,
        password,
        site_info=SiteInfo(
            moodle_user_id=moodle_user_id,
            full_name="Mohamed Wael",
            email="student1@example.com",
            site_url="https://egylms.arabou.edu.kw",
        ),
        token="tok-1",
    )
    return client


@pytest.mark.django_db
def test_login_success_creates_user_and_moodle_account() -> None:
    client = _client_with_user()
    service = LoginWithLms(auth_client=client, data_client=client)

    result = service("student1", "secret")

    assert result.is_new is True
    assert result.user.moodle_username == "student1"
    assert result.user.full_name == "Mohamed Wael"

    account = MoodleAccount.objects.get(user=result.user)
    assert account.moodle_user_id == 42
    assert account.get_token() == "tok-1"
    assert account.status == MoodleAccount.Status.ACTIVE


@pytest.mark.django_db
def test_login_wrong_credentials_raises() -> None:
    client = _client_with_user()
    service = LoginWithLms(auth_client=client, data_client=client)

    with pytest.raises(InvalidLmsCredentials):
        service("student1", "wrong-password")

    assert not User.objects.filter(moodle_username="student1").exists()


@pytest.mark.django_db
def test_login_lms_unreachable_raises() -> None:
    client = _client_with_user()
    client.unavailable = True
    service = LoginWithLms(auth_client=client, data_client=client)

    with pytest.raises(LmsUnavailable):
        service("student1", "secret")


@pytest.mark.django_db
def test_login_existing_user_relogin_updates_token_not_duplicated() -> None:
    client = _client_with_user()
    service = LoginWithLms(auth_client=client, data_client=client)

    first = service("student1", "secret")
    second = service("student1", "secret")

    assert first.user.id == second.user.id
    assert second.is_new is False
    assert User.objects.filter(moodle_username="student1").count() == 1
    assert MoodleAccount.objects.filter(user=first.user).count() == 1
