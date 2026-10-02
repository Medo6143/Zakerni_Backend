import logging
import re

_PASSWORD_PATTERN = re.compile(r'("?password"?\s*[:=]\s*)("[^"]*"|\'[^\']*\'|\S+)', re.IGNORECASE)


class ScrubCredentialsFilter(logging.Filter):
    """Redacts password-like values before a log record is emitted.

    The LMS password must never be persisted anywhere past the login call
    (hard rule #2 in CLAUDE.md). This filter is a defence-in-depth net for
    any accidental logging of request bodies.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _PASSWORD_PATTERN.sub(r"\1***REDACTED***", record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                _PASSWORD_PATTERN.sub(r"\1***REDACTED***", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        # dict-style args (e.g. `logger.info(fmt, {...})`) are left untouched:
        # re-wrapping them would break %-style dict formatting.
        return True
