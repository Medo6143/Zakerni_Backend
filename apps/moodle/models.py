from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.crypto import decrypt, encrypt
from apps.core.models import TimeStampedModel, UUIDModel


class MoodleAccount(UUIDModel, TimeStampedModel):
    """Links a Zakerni user to their university Moodle account.

    The LMS token is stored Fernet-encrypted and is never exposed through
    any API serializer or the Django admin (hard rule #2).
    """

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        EXPIRED = "expired", _("Expired")
        DISABLED = "disabled", _("Disabled")

    user = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="moodle_account"
    )
    site_url = models.URLField()
    moodle_user_id = models.PositiveIntegerField()
    token_encrypted = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(blank=True)

    class Meta:
        db_table = "moodle_account"
        verbose_name = _("Moodle account")
        verbose_name_plural = _("Moodle accounts")

    def set_token(self, raw_token: str) -> None:
        self.token_encrypted = encrypt(raw_token)

    def get_token(self) -> str:
        return decrypt(self.token_encrypted)

    def __str__(self) -> str:
        return f"MoodleAccount<{self.user_id}>"


class SyncLog(UUIDModel):
    moodle_account = models.ForeignKey(
        MoodleAccount, on_delete=models.CASCADE, related_name="sync_logs"
    )
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    class Status(models.TextChoices):
        SUCCESS = "success", _("Success")
        FAILED = "failed", _("Failed")

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SUCCESS)
    items_created = models.PositiveIntegerField(default=0)
    items_updated = models.PositiveIntegerField(default=0)
    items_removed = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        db_table = "moodle_sync_log"
        ordering = ("-started_at",)
        verbose_name = _("sync log")
        verbose_name_plural = _("sync logs")
