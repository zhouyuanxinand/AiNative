"""Controlled cover fields for taskbook generation."""

from __future__ import annotations

import re


ALLOWED_COVER_PHASES = ("F", "C", "S", "D")


def normalize_cover_phase(value: str | None) -> str:
    """Return a validated F/C/S/D cover phase.

    The cover phase is independent from the development-process class
    (全新/改型I/改型II/改型III), so it must never be inferred from it.
    """

    phase = str(value or "").strip().upper()
    if phase and phase not in ALLOWED_COVER_PHASES:
        raise ValueError("研制阶段只能是 F、C、S、D 之一")
    return phase


def apply_cover_phase(document, value: str | None) -> bool:
    """Replace the template cover placeholder without changing its styling."""

    phase = normalize_cover_phase(value)
    if not phase:
        return False

    for paragraph in document.paragraphs:
        compact = re.sub(r"\s+", "", paragraph.text or "")
        if not compact.startswith("研制阶段"):
            continue

        replacement = f"研制阶段：{phase}"
        runs = paragraph.runs
        if runs:
            runs[0].text = replacement
            for run in runs[1:]:
                run.text = ""
        else:
            paragraph.add_run(replacement)
        return True
    return False
