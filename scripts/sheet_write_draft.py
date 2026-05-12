#!/usr/bin/env python3
"""Write an approved Vietnamese draft into a Google Sheet row.

The script is intentionally narrow: it only writes to the draft column and,
optionally, the post status column after the Telegram approval flow has
approved the text.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SHEET_ID_DEFAULT = "1tdgynCsD8b3JjptyAvXNbZtnF5Ng6ChaFxQO4uHDYK8"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HEADER_ALIASES = {
    "group": [
        "nhom noi dung",
        "nhóm nội dung",
    ],
    "date": [
        "ngay du kien dang",
        "ngày dự kiến đăng",
        "ngay dang du kien",
        "ngày đăng dự kiến",
        "ngay dang",
        "ngày đăng",
        "ngay",
        "ngày",
        "date",
    ],
    "topic": [
        "chu de nut obsidian",
        "chu de/tieu de bai viet",
        "chủ đề/tiêu đề bài viết",
        "chu de",
        "chủ đề",
        "topic",
        "nhom noi dung",
        "nhóm nội dung",
    ],
    "draft": [
        "ban nhap tieng viet",
        "bản nháp tiếng việt",
        "bai nhap",
        "bài nháp",
        "ban nhap",
        "draft",
    ],
    "post_status": [
        "trang thai dang",
        "trạng thái đăng",
        "post status",
        "trang thai",
        "trạng thái",
    ],
}

FIELD_ALIASES = {
    "group": ["nhom noi dung", "nhóm nội dung"],
    "topic": ["chu de", "chủ đề", "chu de tieu de bai viet", "chủ đề tiêu đề bài viết"],
    "channel": ["kenh dang tai", "kênh đăng tải"],
    "format": ["dinh dang bai viet", "định dạng bài viết"],
    "owner": ["don vi ca nhan thuc hien", "đơn vị cá nhân thực hiện", "nguoi thuc hien", "người thực hiện"],
    "note": ["luu y", "lưu ý"],
    "media": ["link anh video nguon", "link ảnh video nguồn", "link anh", "link ảnh"],
    "draft": ["ban nhap tieng viet", "bản nháp tiếng việt", "ban nhap", "bản nháp"],
}

FIELD_TO_HEADER = {
    "group": "group",
    "topic": "topic",
    "channel": "channel",
    "format": "format",
    "owner": "owner",
    "note": "note",
    "media": "media",
    "draft": "draft",
}

EXTRA_HEADER_ALIASES = {
    "channel": ["kenh dang tai", "kênh đăng tải"],
    "format": ["dinh dang bai viet", "định dạng bài viết"],
    "owner": ["don vi ca nhan thuc hien", "đơn vị/cá nhân thực hiện", "đơn vị cá nhân thực hiện"],
    "note": ["luu y", "lưu ý"],
    "media": ["link anh/video nguon", "link ảnh/video nguồn", "link anh video nguon", "link ảnh video nguồn"],
}


def _json(data: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def _norm(value: str) -> str:
    value = (value or "").strip().lower()
    value = value.translate(str.maketrans({
        "à": "a", "á": "a", "ạ": "a", "ả": "a", "ã": "a", "â": "a", "ầ": "a", "ấ": "a", "ậ": "a", "ẩ": "a", "ẫ": "a", "ă": "a", "ằ": "a", "ắ": "a", "ặ": "a", "ẳ": "a", "ẵ": "a",
        "è": "e", "é": "e", "ẹ": "e", "ẻ": "e", "ẽ": "e", "ê": "e", "ề": "e", "ế": "e", "ệ": "e", "ể": "e", "ễ": "e",
        "ì": "i", "í": "i", "ị": "i", "ỉ": "i", "ĩ": "i",
        "ò": "o", "ó": "o", "ọ": "o", "ỏ": "o", "õ": "o", "ô": "o", "ồ": "o", "ố": "o", "ộ": "o", "ổ": "o", "ỗ": "o", "ơ": "o", "ờ": "o", "ớ": "o", "ợ": "o", "ở": "o", "ỡ": "o",
        "ù": "u", "ú": "u", "ụ": "u", "ủ": "u", "ũ": "u", "ư": "u", "ừ": "u", "ứ": "u", "ự": "u", "ử": "u", "ữ": "u",
        "ỳ": "y", "ý": "y", "ỵ": "y", "ỷ": "y", "ỹ": "y", "đ": "d",
    }))
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _date_key(value: str) -> str:
    raw = (value or "").strip()
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", raw)
    if not match:
        return _norm(raw)
    day = match.group(1).zfill(2)
    month = match.group(2).zfill(2)
    year = match.group(3) or ""
    if len(year) == 2:
        year = "20" + year
    return f"{day}/{month}/{year}" if year else f"{day}/{month}"


def _key_path() -> Path:
    explicit = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    if explicit:
        return Path(explicit)
    home = os.environ.get("HERMES_HOME", "/srv/yokdon-telegram/hermes/quoc01")
    return Path(home) / "google_key.json"


def _open_worksheet(sheet_id: str, worksheet_gid: str | None):
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except Exception as exc:
        _json({"ok": False, "error": "missing_google_libs", "detail": str(exc)}, 3)

    key = _key_path()
    if not key.exists():
        _json({"ok": False, "error": "missing_service_account_key", "path": str(key)}, 2)
    creds = Credentials.from_service_account_file(str(key), scopes=SCOPES)
    sh = gspread.authorize(creds).open_by_key(sheet_id)
    if worksheet_gid:
        for ws in sh.worksheets():
            if str(ws.id) == str(worksheet_gid):
                return sh, ws
        _json({"ok": False, "error": "worksheet_gid_not_found", "gid": worksheet_gid}, 2)
    ws = sh.get_worksheet(0)
    if ws is None:
        _json({"ok": False, "error": "missing_first_worksheet"}, 2)
    return sh, ws


def _col(headers: list[str], logical: str, required: bool = True) -> int | None:
    normalized = [_norm(h) for h in headers]
    aliases = HEADER_ALIASES.get(logical, []) + EXTRA_HEADER_ALIASES.get(logical, [])
    for alias in aliases:
        wanted = _norm(alias)
        if wanted in normalized:
            return normalized.index(wanted) + 1
    if required:
        _json({"ok": False, "error": "missing_column", "logical": logical, "headers": headers}, 2)
    return None


def _cell(row: list[str], col_1based: int | None) -> str:
    if not col_1based:
        return ""
    idx = col_1based - 1
    return row[idx] if idx < len(row) else ""


def _field_key(label: str) -> str | None:
    normalized = _norm(re.sub(r"\(?\s*cot\s+[a-z]\s*\)?", "", label, flags=re.IGNORECASE))
    for key, aliases in FIELD_ALIASES.items():
        if normalized in [_norm(alias) for alias in aliases]:
            return key
    return None


def _parse_approved_fields(text: str) -> dict[str, str]:
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = re.match(r"^\s*(.+?)(?:\s*\((?:cột|cot)\s+[A-Z]\))?\s*:\s*(.*)$", line, flags=re.IGNORECASE)
        if match:
            key = _field_key(match.group(1))
            if key:
                current = key
                fields[current] = [match.group(2).strip()] if match.group(2).strip() else []
                continue
        if current and line.strip():
            fields[current].append(line.strip())
    return {key: "\n".join(parts).strip() for key, parts in fields.items() if "\n".join(parts).strip()}


def _find_row(
    rows: list[list[str]],
    *,
    row_number: int | None,
    date_col: int | None,
    target_date: str | None,
    topic_col: int | None,
    topic: str | None,
) -> tuple[int, list[str]]:
    if row_number:
        idx = row_number - 2
        if idx < 0 or idx >= len(rows):
            _json({"ok": False, "error": "row_out_of_range", "row": row_number}, 2)
        return row_number, rows[idx]

    if target_date and date_col:
        wanted = _date_key(target_date)
        for offset, row in enumerate(rows, start=2):
            candidate = _date_key(_cell(row, date_col))
            if candidate == wanted or (len(wanted) == 5 and candidate.startswith(wanted)):
                return offset, row
        _json({"ok": False, "error": "date_not_found", "date": target_date}, 2)

    if topic and topic_col:
        wanted = _norm(topic)
        for offset, row in enumerate(rows, start=2):
            candidate = _norm(_cell(row, topic_col))
            if wanted and (wanted in candidate or candidate in wanted):
                return offset, row
        _json({"ok": False, "error": "topic_not_found", "topic": topic}, 2)

    _json({"ok": False, "error": "row_date_or_topic_required"}, 2)


def _backup(row_number: int, headers: list[str], row: list[str]) -> str:
    home = Path(os.environ.get("HERMES_HOME", "/srv/yokdon-telegram/hermes/quoc01"))
    backup_dir = home / "sheet_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = backup_dir / f"zalo_sheet_write_row_{row_number}_{stamp}.json"
    path.write_text(json.dumps({"row": row_number, "headers": headers, "values": row}, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def cmd_write_draft(args: argparse.Namespace) -> None:
    approved_text = (args.approved_text or args.draft_text or sys.stdin.read()).strip()
    if len(approved_text) < 10:
        _json({"ok": False, "error": "approved_text_too_short", "length": len(approved_text)}, 2)

    sheet_id = args.sheet_id or os.environ.get("QUOC01_CONTENT_SHEET_ID") or SHEET_ID_DEFAULT
    _, ws = _open_worksheet(sheet_id, args.worksheet_gid)
    values = ws.get_all_values()
    if not values:
        _json({"ok": False, "error": "empty_sheet"}, 2)
    headers = values[0]
    rows = values[1:]
    draft_col = _col(headers, "draft")
    status_col = _col(headers, "post_status", required=False)
    date_col = _col(headers, "date", required=False)
    topic_col = _col(headers, "topic", required=False)
    field_values = _parse_approved_fields(approved_text)
    if not field_values:
        field_values = {"draft": approved_text}
    field_cols: dict[str, int] = {}
    for field_key in field_values:
        logical = FIELD_TO_HEADER.get(field_key)
        if logical:
            col = _col(headers, logical, required=False)
            if col:
                field_cols[field_key] = col
    if "draft" not in field_cols:
        field_cols["draft"] = draft_col
    row_number, row = _find_row(
        rows,
        row_number=args.row,
        date_col=date_col,
        target_date=args.date,
        topic_col=topic_col,
        topic=args.topic,
    )

    if args.dry_run:
        _json({
            "ok": True,
            "dry_run": True,
            "row": row_number,
            "worksheet": ws.title,
            "target_date": _cell(row, date_col),
            "topic": _cell(row, topic_col),
            "draft_len": len(field_values.get("draft", "")),
            "post_status": _cell(row, status_col),
            "updated_fields": list(field_cols.keys()),
        })

    backup_path = _backup(row_number, headers, row)
    for field_key, col in field_cols.items():
        ws.update_cell(row_number, col, field_values[field_key])
    if args.post_status and status_col:
        ws.update_cell(row_number, status_col, args.post_status)
    verify = ws.row_values(row_number)
    _json({
        "ok": True,
        "action": "write_draft",
        "row": row_number,
        "worksheet": ws.title,
        "target_date": _cell(verify, date_col),
        "topic": _cell(verify, topic_col),
        "draft_len": len(_cell(verify, draft_col)),
        "post_status": _cell(verify, status_col),
        "updated_fields": list(field_cols.keys()),
        "backup": backup_path,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description="Write approved Zalo draft content to Google Sheet")
    sub = parser.add_subparsers(dest="cmd", required=True)

    write = sub.add_parser("write-draft")
    write.add_argument("--sheet-id")
    write.add_argument("--worksheet-gid")
    write.add_argument("--row", type=int)
    write.add_argument("--date")
    write.add_argument("--topic")
    write.add_argument("--draft-text")
    write.add_argument("--approved-text")
    write.add_argument("--post-status", default="Chờ đăng")
    write.add_argument("--dry-run", action="store_true")
    write.set_defaults(func=cmd_write_draft)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
