"""Parse a WhatsApp chat export. Re-uploads skip messages already stored."""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import Path

LINE_A = re.compile(
    r"^\[(\d{1,2}/\d{1,2}/\d{2,4}),\s+(\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APMapm]{2})?)\]\s([^:]+):\s(.*)$"
)
LINE_B = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}),\s+(\d{1,2}:\d{2}(?::\d{2})?)\s+-\s([^:]+):\s(.*)$"
)


def _normalize_stamp(day: str, clock: str) -> str:
    return f"{day.strip()} {clock.strip()}"


def parse_export(text: str) -> list[dict]:
    messages = []
    current = None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip("\ufeff")
        match = LINE_A.match(line) or LINE_B.match(line)
        if match:
            if current:
                messages.append(current)
            current = {
                "sent_at": _normalize_stamp(match.group(1), match.group(2)),
                "sender": match.group(3).strip(),
                "body": match.group(4).strip(),
            }
            continue
        if current and line:
            current["body"] = (current["body"] + "\n" + line).strip()
    if current:
        messages.append(current)
    return [item for item in messages if item["body"] and "Messages and calls are end-to-end encrypted" not in item["body"]]


def read_export(path: Path | None = None, data: bytes | None = None, name: str = "") -> str:
    if data is not None and name.lower().endswith(".zip"):
        with zipfile.ZipFile(BytesIO(data)) as archive:
            texts = [archive.read(info).decode("utf-8", errors="replace") for info in archive.infolist() if info.filename.lower().endswith(".txt")]
        return "\n".join(texts)
    if data is not None:
        return data.decode("utf-8", errors="replace")
    if path is None:
        return ""
    if path.suffix.lower() == ".zip":
        return read_export(data=path.read_bytes(), name=path.name)
    return path.read_text(encoding="utf-8", errors="replace")
