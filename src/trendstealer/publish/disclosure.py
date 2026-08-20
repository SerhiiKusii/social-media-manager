"""AI-content disclosure.

Meta has no documented, stable Graph API parameter for the AI-content
label on IG media creation. Reliability, descending: (1) embedded
provenance metadata (exiftool -XMP-iptcExt:DigitalSourceType, read back
to confirm) -- best-effort here since exiftool isn't part of the bundled
toolchain and its absence shouldn't block a publish the caption-line
disclosure already covers; (2) the mandatory caption line, which is what
preflight() actually enforces; (3) the account-level composer toggle, a
documented operator step outside this codebase.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from pathlib import Path

DIGITAL_SOURCE_TYPE = "trainedAlgorithmicMedia"
DISCLOSURE_MARKER = "#AIGenerated"


class DisclosureError(RuntimeError):
    pass


def ensure_caption_has_disclosure(caption: str) -> str:
    if DISCLOSURE_MARKER.lower() in caption.lower():
        return caption
    return f"{caption}\n\n{DISCLOSURE_MARKER}"


def validate_disclosure(caption: str) -> None:
    if DISCLOSURE_MARKER.lower() not in caption.lower():
        raise DisclosureError("caption is missing the mandatory AI disclosure marker")


def try_embed_metadata(video_path: Path) -> bool:
    """Best-effort: embeds and reads back XMP-iptcExt:DigitalSourceType.
    Returns False (does not raise) if exiftool isn't installed -- the
    caption-line disclosure is the gate that actually blocks publish."""
    exiftool = shutil.which("exiftool")
    if exiftool is None:
        return False

    subprocess.run(
        [
            exiftool,
            "-overwrite_original",
            f"-XMP-iptcExt:DigitalSourceType={DIGITAL_SOURCE_TYPE}",
            str(video_path),
        ],
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        [exiftool, "-XMP-iptcExt:DigitalSourceType", "-s3", str(video_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return DIGITAL_SOURCE_TYPE in result.stdout


def preflight(
    *,
    video_path: Path,
    caption: str,
    conn: sqlite3.Connection | None = None,
    revision_id: int | None = None,
) -> None:
    """Raises DisclosureError if this item is not safe to publish.

    The asset-licence check is the backstop, not the first line of defence
    -- the worker only ever selects cleared assets (see _select_broll). It
    matters most for a forced publish, where the operator has deliberately
    skipped the rate limiter and this is the last gate left standing.
    """
    validate_disclosure(caption)

    if conn is not None and revision_id is not None:
        from trendstealer import repo

        uncleared = repo.list_uncleared_assets_for_revision(conn, revision_id)
        if uncleared:
            paths = ", ".join(str(row["path"]) for row in uncleared)
            raise DisclosureError(
                f"revision {revision_id} contains asset(s) not cleared for commercial use: {paths}"
            )

    try_embed_metadata(video_path)
