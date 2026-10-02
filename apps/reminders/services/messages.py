"""Localised reminder text, rendered in the user's language and timezone.

Examples (docs/01 section 4.4):

- ar: ``كويز M110 — Quiz 2 بيقفل بكرة الساعة 10:00 م``
- en: ``M110 — Quiz 2 closes tomorrow at 10:00 PM``

The push body is the sentence plus the location on a second line; Telegram
gets ``Message.long_body`` with extra lines (location, tutor from the enrollment, Teams join
link). ``REMINDER_PHRASES`` is the only type-dependent mapping for message text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import dateformat, translation
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from apps.core.i18n import normalise_language
from apps.moodle.services.mappers import find_teams_link
from apps.notifications.protocols import Message
from apps.schedule.models import ItemType
from apps.schedule.selectors import tutor_name_for

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.schedule.models import Item


@dataclass(frozen=True)
class ReminderPhrase:
    title: Any
    body: Any  # %(subject)s and %(when)s placeholders


REMINDER_PHRASES: dict[str, ReminderPhrase] = {
    ItemType.QUIZ.value: ReminderPhrase(
        title=_("Quiz reminder"),
        body=pgettext_lazy("quiz reminder", "%(subject)s closes %(when)s"),
    ),
    ItemType.TMA.value: ReminderPhrase(
        title=_("TMA reminder"),
        body=pgettext_lazy("tma reminder", "%(subject)s is due %(when)s"),
    ),
    ItemType.EXAM.value: ReminderPhrase(
        title=_("Exam reminder"),
        body=pgettext_lazy("exam reminder", "%(subject)s starts %(when)s"),
    ),
    ItemType.LECTURE.value: ReminderPhrase(
        title=_("Lecture reminder"),
        body=pgettext_lazy("lecture reminder", "%(subject)s starts %(when)s"),
    ),
}

_TODAY = _("today at %(time)s")
_TOMORROW = _("tomorrow at %(time)s")
_ON_DATE = _("on %(date)s at %(time)s")
_ONLINE_TEAMS = _("Online (Teams)")
_LOCATION_LINE = _("Location: %(location)s")
_TUTOR_LINE = _("Tutor: %(tutor)s")
_JOIN_LINE = _("Join: %(url)s")
_AM = pgettext_lazy("time of day", "AM")
_PM = pgettext_lazy("time of day", "PM")


def user_zone(user: User) -> ZoneInfo:
    try:
        return ZoneInfo(user.timezone or settings.DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(settings.DEFAULT_TIMEZONE)


def format_time(local: datetime) -> str:
    hour = local.hour % 12 or 12
    marker = _AM if local.hour < 12 else _PM
    return f"{hour}:{local.minute:02d} {marker}"


def format_when(moment: datetime, now: datetime, zone: ZoneInfo) -> str:
    local = moment.astimezone(zone)
    today = now.astimezone(zone).date()
    time_text = format_time(local)
    delta_days = (local.date() - today).days
    if delta_days == 0:
        return str(_TODAY) % {"time": time_text}
    if delta_days == 1:
        return str(_TOMORROW) % {"time": time_text}
    return str(_ON_DATE) % {"date": dateformat.format(local, "D j M"), "time": time_text}


def item_subject(item: Item) -> str:
    course = item.course
    if course is not None and course.code:
        return f"{course.code} — {item.title}"
    return item.title


def item_location(item: Item) -> str:
    """The stored location, else "Online (Teams)" when the item has a Teams link."""
    if item.location:
        return item.location
    if find_teams_link(item.url):
        return str(_ONLINE_TEAMS)
    return ""


def render_reminder_message(item: Item, *, user: User, now: datetime) -> Message:
    phrase = REMINDER_PHRASES[item.type]
    assert item.scheduled_at is not None
    with translation.override(normalise_language(user.language)):
        sentence = str(phrase.body) % {
            "subject": item_subject(item),
            "when": format_when(item.scheduled_at, now, user_zone(user)),
        }
        title = str(phrase.title)
        location = item_location(item)
        tutor = tutor_name_for(user, item.course_id)
        teams_link = find_teams_link(item.url)
        lines = [
            sentence,
            str(_LOCATION_LINE) % {"location": location} if location else "",
            str(_TUTOR_LINE) % {"tutor": tutor} if tutor else "",
            str(_JOIN_LINE) % {"url": teams_link} if teams_link else "",
        ]
    body = f"{sentence}\n{location}" if location else sentence
    return Message(
        title=title,
        body=body,
        long_body="\n".join(line for line in lines if line),
        data={
            "kind": "reminder",
            "item_id": str(item.pk),
            "route": f"/calendar?item={item.pk}",
        },
    )
