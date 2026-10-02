from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.sis.models import SisAccount


class SisStatusSerializer(serializers.Serializer):
    """Status fields only: the password is never returned (CLAUDE.md rule 2)."""

    connected = serializers.BooleanField()
    username = serializers.CharField(allow_blank=True)
    status = serializers.ChoiceField(choices=SisAccount.Status.choices, allow_null=True)
    last_synced_at = serializers.DateTimeField(allow_null=True)
    last_sync_error = serializers.CharField(allow_blank=True)


def sis_status_data(account: SisAccount | None) -> dict[str, Any]:
    if account is None:
        values: dict[str, Any] = {
            "connected": False,
            "username": "",
            "status": None,
            "last_synced_at": None,
            "last_sync_error": "",
        }
    else:
        values = {
            "connected": True,
            "username": account.username,
            "status": account.status,
            "last_synced_at": account.last_synced_at,
            "last_sync_error": account.last_sync_error,
        }
    return dict(SisStatusSerializer(values).data)


class SisConnectSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=64)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
