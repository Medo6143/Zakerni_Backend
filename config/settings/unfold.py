"""Unfold admin configuration (theme, sidebar navigation), imported by ``base.py``."""

from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _


# --- django-unfold admin -----------------------------------------------------------
# Visual theme: docs/07-design-system.md ("Admin panel"). The primary scale below is the app
# indigo (#4F46E5 = 600); change the primary colour there and in static/admin/zakerni.css.
def _static_url(path: str):  # type: ignore[no-untyped-def]
    """Resolve a static file lazily (Unfold calls it per request)."""

    def resolve(request):  # type: ignore[no-untyped-def]
        from django.templatetags.static import static

        return static(path)

    return resolve


def _can_view(permission: str):  # type: ignore[no-untyped-def]
    def check(request):  # type: ignore[no-untyped-def]
        return request.user.has_perm(permission)

    return check


def _nav_item(title, icon: str, url_name: str, permission: str) -> dict:  # type: ignore[no-untyped-def,type-arg]
    return {
        "title": title,
        "icon": icon,
        "link": reverse_lazy(url_name),
        "permission": _can_view(permission),
    }


UNFOLD = {
    "SITE_TITLE": _("Zakerni Admin"),
    "SITE_HEADER": _("Zakerni"),
    "SITE_SYMBOL": "notifications_active",
    "SITE_LOGO": {
        "light": _static_url("brand/logo-mark-white.svg"),
        "dark": _static_url("brand/logo-mark-white.svg"),
    },
    "SITE_ICON": {
        "light": _static_url("brand/logo-icon.svg"),
        "dark": _static_url("brand/logo-icon.svg"),
    },
    "SITE_FAVICONS": [
        {
            "rel": "icon",
            "sizes": "any",
            "type": "image/svg+xml",
            "href": _static_url("brand/logo-icon.svg"),
        },
    ],
    "SHOW_LANGUAGES": True,
    "SHOW_HISTORY": True,
    "DASHBOARD_CALLBACK": "apps.core.dashboard.dashboard_callback",
    "STYLES": [_static_url("admin/zakerni.css")],
    "COLORS": {
        # Indigo scale generated around the app primary #4F46E5 (600), rgb triplets.
        "primary": {
            "50": "238 242 255",
            "100": "224 231 255",
            "200": "199 210 254",
            "300": "165 180 252",
            "400": "129 140 248",
            "500": "99 102 241",
            "600": "79 70 229",
            "700": "67 56 202",
            "800": "55 48 163",
            "900": "49 46 129",
            "950": "30 27 75",
        },
    },
    "LOGIN": {"redirect_after": None},
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": _("Overview"),
                "items": [
                    {
                        "title": _("Dashboard"),
                        "icon": "dashboard",
                        "link": reverse_lazy("admin:index"),
                    },
                ],
            },
            {
                "title": _("Users"),
                "items": [
                    _nav_item(
                        _("Users"), "group", "admin:accounts_user_changelist", "accounts.view_user"
                    ),
                    _nav_item(
                        _("Devices"),
                        "smartphone",
                        "admin:notifications_device_changelist",
                        "notifications.view_device",
                    ),
                    _nav_item(
                        _("Telegram links"),
                        "send",
                        "admin:notifications_telegramlink_changelist",
                        "notifications.view_telegramlink",
                    ),
                ],
            },
            {
                "title": _("Courses and schedule"),
                "items": [
                    _nav_item(
                        _("Courses"),
                        "school",
                        "admin:schedule_course_changelist",
                        "schedule.view_course",
                    ),
                    _nav_item(
                        _("Enrollments"),
                        "how_to_reg",
                        "admin:schedule_enrollment_changelist",
                        "schedule.view_enrollment",
                    ),
                    _nav_item(
                        _("Items"),
                        "event_note",
                        "admin:schedule_item_changelist",
                        "schedule.view_item",
                    ),
                    _nav_item(
                        _("Lecture schedules"),
                        "calendar_month",
                        "admin:schedule_lectureschedule_changelist",
                        "schedule.view_lectureschedule",
                    ),
                ],
            },
            {
                "title": _("Reminders"),
                "items": [
                    _nav_item(
                        _("Reminder rules"),
                        "tune",
                        "admin:reminders_reminderrule_changelist",
                        "reminders.view_reminderrule",
                    ),
                    _nav_item(
                        _("Scheduled reminders"),
                        "alarm",
                        "admin:reminders_scheduledreminder_changelist",
                        "reminders.view_scheduledreminder",
                    ),
                ],
            },
            {
                "title": _("Notifications"),
                "items": [
                    _nav_item(
                        _("Notifications"),
                        "notifications",
                        "admin:notifications_notification_changelist",
                        "notifications.view_notification",
                    ),
                    _nav_item(
                        _("Broadcasts"),
                        "campaign",
                        "admin:broadcasts_broadcast_changelist",
                        "broadcasts.view_broadcast",
                    ),
                ],
            },
            {
                "title": _("Support"),
                "items": [
                    _nav_item(
                        _("Reports"),
                        "support_agent",
                        "admin:support_report_changelist",
                        "support.view_report",
                    ),
                ],
            },
            {
                "title": _("Integrations"),
                "items": [
                    _nav_item(
                        _("Moodle accounts"),
                        "link",
                        "admin:moodle_moodleaccount_changelist",
                        "moodle.view_moodleaccount",
                    ),
                    _nav_item(
                        _("Moodle sync logs"),
                        "sync",
                        "admin:moodle_synclog_changelist",
                        "moodle.view_synclog",
                    ),
                    _nav_item(
                        _("SIS accounts"),
                        "badge",
                        "admin:sis_sisaccount_changelist",
                        "sis.view_sisaccount",
                    ),
                    _nav_item(
                        _("SIS sync logs"),
                        "history",
                        "admin:sis_sissynclog_changelist",
                        "sis.view_sissynclog",
                    ),
                ],
            },
        ],
    },
}
