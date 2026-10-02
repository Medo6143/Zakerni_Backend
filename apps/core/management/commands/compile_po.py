"""Compile ``locale/*/LC_MESSAGES/django.po`` to ``.mo`` without GNU gettext.

``python manage.py compilemessages`` needs ``msgfmt``; this pure-Python
fallback produces the same binary catalog for our simple catalogs (msgctxt
supported, plural forms not used). Fuzzy and untranslated entries are skipped.
"""

from __future__ import annotations

import ast
import struct
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand


def _unquote(line: str) -> str:
    return ast.literal_eval(line)


def parse_po(text: str) -> dict[str, str]:
    """Return ``{key: msgstr}`` where key is ``msgid`` or ``ctxt\\x04msgid``."""
    entries: dict[str, str] = {}
    current: dict[str, Any] = {}
    field: str | None = None
    fuzzy = False

    def flush() -> None:
        nonlocal current, fuzzy
        if "msgid" in current and "msgstr" in current:
            msgid = current["msgid"]
            msgstr = current["msgstr"]
            if (msgstr and not fuzzy) or msgid == "":
                key = f"{current['msgctxt']}\x04{msgid}" if "msgctxt" in current else msgid
                entries[key] = msgstr
        current = {}
        fuzzy = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            field = None
            continue
        if line.startswith("#,") and "fuzzy" in line:
            fuzzy = True
            continue
        if line.startswith("#"):
            continue
        for keyword in ("msgctxt", "msgid", "msgstr"):
            if line.startswith(keyword + " "):
                if keyword in ("msgctxt",) or (keyword == "msgid" and "msgstr" in current):
                    flush()
                field = keyword
                current[keyword] = _unquote(line[len(keyword) + 1 :])
                break
        else:
            if line.startswith('"') and field is not None:
                current[field] += _unquote(line)
    flush()
    return entries


def build_mo(entries: dict[str, str]) -> bytes:
    keys = sorted(entries)
    ids = [k.encode("utf-8") for k in keys]
    strs = [entries[k].encode("utf-8") for k in keys]
    count = len(keys)
    header_size = 7 * 4
    originals_offset = header_size
    translations_offset = originals_offset + count * 8
    data_offset = translations_offset + count * 8

    original_table = b""
    translation_table = b""
    data = b""
    offset = data_offset
    for value in ids:
        original_table += struct.pack("<II", len(value), offset)
        data += value + b"\0"
        offset += len(value) + 1
    for value in strs:
        translation_table += struct.pack("<II", len(value), offset)
        data += value + b"\0"
        offset += len(value) + 1

    header = struct.pack(
        "<IIIIIII", 0x950412DE, 0, count, originals_offset, translations_offset, 0, 0
    )
    return header + original_table + translation_table + data


class Command(BaseCommand):
    help = "Compile .po catalogs in LOCALE_PATHS to .mo (pure Python, no msgfmt needed)."

    def handle(self, *args: Any, **options: Any) -> None:
        for locale_path in settings.LOCALE_PATHS:
            for po_file in sorted(Path(locale_path).glob("*/LC_MESSAGES/*.po")):
                entries = parse_po(po_file.read_text(encoding="utf-8"))
                po_file.with_suffix(".mo").write_bytes(build_mo(entries))
                self.stdout.write(f"compiled {po_file} ({len(entries) - 1} messages)")
