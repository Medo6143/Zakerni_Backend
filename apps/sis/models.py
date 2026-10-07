"""Link to the university Student Information System (SIS).

Product decision (CLAUDE.md rule 2): unlike the Moodle password, the SIS password
is stored, Fernet-encrypted, because the SIS has no long-lived token. It is never
returned by any API, never shown in admin, never logged, and is deleted with the
account (disconnect or account deletion).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.crypto import decrypt, encrypt
from apps.core.models import TimeStampedModel, UUIDModel


class SisAccount(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        INVALID_CREDENTIALS = "invalid_credentials", _("Invalid credentials")
        ERROR = "error", _("Error")
        DISABLED = "disabled", _("Disabled")

    user = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="sis_account"
    )
    username = models.CharField(_("username"), max_length=64)
    # Empty in device mode: the SIS password stays on the student's phone.
    password_encrypted = models.TextField(blank=True, default="")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.ACTIVE)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(blank=True)

    class Meta:
        db_table = "sis_account"
        verbose_name = _("SIS account")
        verbose_name_plural = _("SIS accounts")

    def set_password(self, raw_password: str) -> None:
        self.password_encrypted = encrypt(raw_password)

    def get_password(self) -> str:
        return decrypt(self.password_encrypted) if self.password_encrypted else ""

    def __str__(self) -> str:
        return f"SisAccount<{self.user_id}>"


class SisSyncLog(UUIDModel):
    class Status(models.TextChoices):
        SUCCESS = "success", _("Success")
        FAILED = "failed", _("Failed")

    sis_account = models.ForeignKey(SisAccount, on_delete=models.CASCADE, related_name="sync_logs")
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SUCCESS)
    items_created = models.PositiveIntegerField(default=0)
    items_updated = models.PositiveIntegerField(default=0)
    items_removed = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        db_table = "sis_sync_log"
        ordering = ("-started_at",)
        verbose_name = _("SIS sync log")
        verbose_name_plural = _("SIS sync logs")
