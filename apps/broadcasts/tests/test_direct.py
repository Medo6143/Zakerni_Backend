import pytest
from django.test import Client
from django.utils import translation

from apps.accounts.tests.factories import UserFactory
from apps.broadcasts.models import Broadcast
from apps.broadcasts.selectors import channel_availability, estimated_recipients
from apps.broadcasts.services.direct import EmptyDirectMessage, create_direct_broadcast
from apps.broadcasts.services.send import send_broadcast
from apps.notifications.models import Notification
from apps.notifications.tests.factories import DeviceFactory, TelegramLinkFactory

pytestmark = pytest.mark.django_db


def _direct(sender, recipient, **kw):  # type: ignore[no-untyped-def]
    queued: list = []
    data = {"title_ar": "عنوان", "body_ar": "نص", "title_en": "Title", "body_en": "Text"}
    data.update(kw)
    broadcast = create_direct_broadcast(
        sender=sender, recipient=recipient, enqueue=queued.append, **data
    )
    return broadcast, queued


def test_direct_reaches_only_recipient_in_their_language(channels, fake_clients) -> None:
    staff = UserFactory(is_staff=True)
    target = UserFactory(language="en")
    other = UserFactory(language="en")
    DeviceFactory(user=target, fcm_token="t-token")
    DeviceFactory(user=other, fcm_token="o-token")
    TelegramLinkFactory(user=target, chat_id=7)
    broadcast, _q = _direct(staff, target)

    assert send_broadcast(broadcast, channels=channels) == 1

    assert [t for t, _m in fake_clients.push.sent] == ["t-token"]
    assert fake_clients.bot.sent == [(7, "Title\nText")]
    assert Notification.objects.filter(broadcast=broadcast).count() == 1
    assert not Notification.objects.filter(user=other).exists()
    broadcast.refresh_from_db()
    assert broadcast.recipient == target and broadcast.created_by == staff


def test_direct_uses_arabic_for_arabic_user(channels, fake_clients) -> None:
    target = UserFactory(language="ar")
    DeviceFactory(user=target, fcm_token="t")
    broadcast, _q = _direct(UserFactory(is_staff=True), target)
    send_broadcast(broadcast, channels=channels)
    assert fake_clients.push.sent[0][1].title == "عنوان"


def test_single_language_is_used_for_both() -> None:
    staff = UserFactory(is_staff=True)
    broadcast, _q = _direct(
        staff, UserFactory(), title_ar="", body_ar="", title_en="T", body_en="B"
    )
    assert (broadcast.title_ar, broadcast.body_ar) == ("T", "B")
    broadcast, _q = _direct(
        staff, UserFactory(), title_en="", body_en="", title_ar="ع", body_ar="ن"
    )
    assert (broadcast.title_en, broadcast.body_en) == ("ع", "ن")


def test_empty_message_rejected() -> None:
    with pytest.raises(EmptyDirectMessage):
        _direct(
            UserFactory(is_staff=True),
            UserFactory(),
            title_ar="",
            body_ar="",
            title_en="",
            body_en="",
        )


def test_inactive_recipient_gets_nothing(channels, fake_clients) -> None:
    target = UserFactory(is_active=False)
    DeviceFactory(user=target)
    broadcast, _q = _direct(UserFactory(is_staff=True), target)
    assert send_broadcast(broadcast, channels=channels) == 0
    assert fake_clients.push.sent == []


def test_staff_recipient_allowed_and_no_device_keeps_history(channels, fake_clients) -> None:
    target = UserFactory(is_staff=True)
    broadcast, _q = _direct(UserFactory(is_staff=True), target)
    assert estimated_recipients(broadcast) == 0
    assert send_broadcast(broadcast, channels=channels) == 0
    assert Notification.objects.filter(user=target, broadcast=broadcast).count() == 1
    broadcast.refresh_from_db()
    assert broadcast.status == Broadcast.Status.SENT


def test_estimated_recipients_for_direct() -> None:
    target = UserFactory()
    DeviceFactory(user=target)
    DeviceFactory(user=UserFactory())
    broadcast, _q = _direct(UserFactory(is_staff=True), target)
    assert estimated_recipients(broadcast) == 1


def test_channel_availability() -> None:
    user = UserFactory()
    assert not channel_availability(user).any_available
    DeviceFactory(user=user)
    DeviceFactory(user=user, is_active=False)
    TelegramLinkFactory(user=user)
    info = channel_availability(user)
    assert info.active_devices == 1 and info.telegram_linked


# --- admin ------------------------------------------------------------------------


@pytest.fixture
def staff_client() -> Client:
    client = Client()
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    return client


def _url(user) -> str:  # type: ignore[no-untyped-def]
    return f"/admin/accounts/user/{user.pk}/send-notification/"


def test_form_renders_channel_info(staff_client) -> None:
    target = UserFactory(language="en", full_name="Sara Ali")
    DeviceFactory(user=target)
    page = staff_client.get(_url(target))
    html = page.content.decode()
    assert page.status_code == 200
    assert "Sara Ali" in html and target.moodle_username in html
    assert 'id="channel-devices">1<' in html
    assert 'id="channel-telegram">No<' in html


def test_valid_post_creates_and_sends(
    staff_client, fake_clients, django_capture_on_commit_callbacks
) -> None:
    target = UserFactory(language="en")
    DeviceFactory(user=target, fcm_token="tok")
    with django_capture_on_commit_callbacks(execute=True):
        response = staff_client.post(
            _url(target),
            {"title_en": "Hi", "body_en": "There", "send_push": "on", "send_telegram": "on"},
            follow=True,
        )
    assert response.status_code == 200
    broadcast = Broadcast.objects.get(recipient=target)
    assert broadcast.status == Broadcast.Status.SENT and broadcast.recipients_count == 1
    assert fake_clients.push.sent[0][0] == "tok"
    assert any("push" in str(m) for m in response.context["messages"])


def test_post_without_device_warns(staff_client, django_capture_on_commit_callbacks) -> None:
    target = UserFactory()
    with django_capture_on_commit_callbacks(execute=True):
        response = staff_client.post(
            _url(target), {"title_en": "Hi", "body_en": "There", "send_push": "on"}, follow=True
        )
    assert any("history only" in str(m) for m in response.context["messages"])
    assert Notification.objects.filter(user=target).count() == 1


def test_post_with_both_languages_empty_is_invalid(staff_client) -> None:
    target = UserFactory()
    response = staff_client.post(_url(target), {"send_push": "on"})
    assert response.status_code == 200
    assert not Broadcast.objects.exists()
    assert "at least one language" in response.content.decode()


def test_post_without_channel_is_invalid(staff_client) -> None:
    response = staff_client.post(_url(UserFactory()), {"title_en": "a", "body_en": "b"})
    assert response.status_code == 200 and not Broadcast.objects.exists()


def test_non_staff_denied() -> None:
    client = Client()
    client.force_login(UserFactory())
    target = UserFactory()
    assert client.get(_url(target)).status_code == 302
    assert client.post(_url(target), {"title_en": "a", "body_en": "b"}).status_code == 302
    assert not Broadcast.objects.exists()


def test_staff_without_permission_denied() -> None:
    client = Client()
    client.force_login(UserFactory(is_staff=True))
    assert client.get(_url(UserFactory())).status_code in (302, 403)
    assert not Broadcast.objects.exists()


def test_list_action_requires_exactly_one_user(staff_client) -> None:
    a, b = UserFactory(), UserFactory()
    two = staff_client.post(
        "/admin/accounts/user/",
        {"action": "send_notification", "_selected_action": [str(a.pk), str(b.pk)]},
        follow=True,
    )
    assert any("exactly one" in str(m) for m in two.context["messages"])
    one = staff_client.post(
        "/admin/accounts/user/",
        {"action": "send_notification", "_selected_action": [str(a.pk)]},
    )
    assert one.status_code == 302 and one["Location"] == _url(a)


def test_detail_button_and_broadcast_list_show_recipient(staff_client) -> None:
    target = UserFactory(moodle_username="direct_target")
    _direct(UserFactory(is_staff=True), target)
    Broadcast.objects.create(title_ar="ع", body_ar="ن", title_en="T", body_en="B")
    change = staff_client.get(f"/admin/accounts/user/{target.pk}/change/")
    assert "send-notification" in change.content.decode()
    listing = staff_client.get("/admin/broadcasts/broadcast/").content.decode()
    assert "direct_target" in listing and "Everyone" in listing
    direct_only = staff_client.get("/admin/broadcasts/broadcast/?audience=direct")
    assert direct_only.status_code == 200
    assert "direct_target" in direct_only.content.decode()


def test_translations_present() -> None:
    with translation.override("ar"):
        assert translation.gettext("Send notification") == "إرسال إشعار"
        assert translation.gettext("Everyone") == "الجميع"
    with translation.override("en"):
        assert translation.gettext("Everyone") == "Everyone"
