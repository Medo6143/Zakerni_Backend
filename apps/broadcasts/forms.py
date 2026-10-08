"""Form for the admin "Send notification" page (one user)."""

from __future__ import annotations

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _


class DirectNotificationForm(forms.Form):
    title_ar = forms.CharField(label=_("Title (Arabic)"), max_length=255, required=False)
    body_ar = forms.CharField(
        label=_("Message (Arabic)"), required=False, widget=forms.Textarea(attrs={"rows": 4})
    )
    title_en = forms.CharField(label=_("Title (English)"), max_length=255, required=False)
    body_en = forms.CharField(
        label=_("Message (English)"), required=False, widget=forms.Textarea(attrs={"rows": 4})
    )
    send_push = forms.BooleanField(label=_("Push"), required=False, initial=True)
    send_telegram = forms.BooleanField(label=_("Telegram"), required=False, initial=True)

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        complete = 0
        for lang in ("ar", "en"):
            title = (data.get(f"title_{lang}") or "").strip()
            body = (data.get(f"body_{lang}") or "").strip()
            if bool(title) != bool(body):
                missing = f"body_{lang}" if title else f"title_{lang}"
                self.add_error(
                    missing, _("Fill both the title and the message, or leave both empty.")
                )
            elif title:
                complete += 1
        if not self.errors and complete == 0:
            raise forms.ValidationError(_("Write a title and a message in at least one language."))
        if not data.get("send_push") and not data.get("send_telegram"):
            raise forms.ValidationError(_("Select at least one channel."))
        return data
