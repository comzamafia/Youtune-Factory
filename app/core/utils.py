"""Shared utility helpers used across multiple modules."""

from __future__ import annotations

import re
import unicodedata


# Characters forbidden in file names on Windows / Linux
_FORBIDDEN = re.compile(r'[\\/:*?"<>|]')
# Collapse multiple underscores / spaces
_MULTI_UNDERSCORE = re.compile(r"_+")


def safe_filename(text: str, max_length: int = 80) -> str:
    """Convert *text* (e.g. a Thai novel title) into a safe filesystem name.

    - Preserves Unicode letters and digits (including Thai).
    - Replaces spaces and Windows-forbidden characters with ``_``.
    - Strips leading/trailing underscores.
    - Truncates to *max_length* characters.

    Example::

        safe_filename("โลกใหม่: ความจริงอันโหดร้าย!")
        # → "โลกใหม่_ความจริงอันโหดร้าย"
    """
    # Normalize unicode (NFC keeps Thai combining chars correct)
    text = unicodedata.normalize("NFC", text)
    # Replace forbidden chars with underscore
    text = _FORBIDDEN.sub("_", text)
    # Replace whitespace sequences with underscore
    text = re.sub(r"\s+", "_", text)
    # Remove any remaining chars that are neither word chars nor Unicode letters/digits
    # Keep: Unicode letters (Thai etc.), digits, underscore, hyphen, dot
    text = re.sub(r"[^\w\-.]", "", text, flags=re.UNICODE)
    # Collapse multiple underscores
    text = _MULTI_UNDERSCORE.sub("_", text)
    # Strip leading/trailing separators
    text = text.strip("_-.")
    # Enforce max length (do NOT cut mid-codepoint — Python slicing on str is safe)
    return text[:max_length] or "untitled"
