from __future__ import annotations

import re
import uuid
from typing import Any

from apps.schedule.models import Enrollment
from apps.sis.models import SisAccount
from apps.sis.services.mappers import normalize_code

# Accounts the periodic sync picks up: a transient error must not stop syncing.
SYNCABLE_STATUSES = (SisAccount.Status.ACTIVE, SisAccount.Status.ERROR)


def sis_account_for_user(user_id: Any) -> SisAccount | None:
    return SisAccount.objects.filter(user_id=user_id).first()


def sis_account_by_id(account_id: Any) -> SisAccount | None:
    return SisAccount.objects.select_related("user").filter(id=account_id).first()


def syncable_sis_account_ids() -> list[uuid.UUID]:
    return list(
        SisAccount.objects.filter(status__in=SYNCABLE_STATUSES, user__is_active=True)
        .exclude(password_encrypted="")  # device mode: no password, nothing the server can fetch
        .values_list("id", flat=True)
    )


_GROUP_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")


def _code_tokens(code: str) -> set[str]:
    upper = code.upper()
    tokens = {normalize_code(t) for t in upper.replace("_", " ").replace("-", " ").split()}
    return {t for t in tokens if t} | {normalize_code(upper)}


class CourseIndex:
    """SIS course code -> the student's active enrollment with that code."""

    def __init__(self, user_id: Any) -> None:
        self._enrollments = list(
            Enrollment.objects.filter(user_id=user_id, is_active=True).select_related("course")
        )

    def find(self, sis_code: str) -> Enrollment | None:
        # The SIS appends the student's group, e.g. "EL112 (28)"; match on the code alone.
        wanted = normalize_code(_GROUP_SUFFIX.sub("", sis_code))
        if not wanted:
            return None
        for enrollment in self._enrollments:
            if wanted in _code_tokens(enrollment.course.code):
                return enrollment
        return None
