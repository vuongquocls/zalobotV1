"""
time_utils.py - Thoi gian dia phuong cho bot.

VPS co the chay UTC, nhung lich nhac viec cua bot phai theo gio Viet Nam.
Dung module nay de tranh phu thuoc timezone cua he dieu hanh.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python cu hon 3.9
    ZoneInfo = None


LOCAL_TIMEZONE_NAME = os.getenv("BOT_TIMEZONE", "Asia/Ho_Chi_Minh").strip() or "Asia/Ho_Chi_Minh"


def _load_timezone():
    if ZoneInfo is not None:
        try:
            return ZoneInfo(LOCAL_TIMEZONE_NAME)
        except Exception:
            pass

    # Viet Nam khong dung DST, UTC+7 la fallback an toan neu thieu tzdata.
    return timezone(timedelta(hours=7), name="ICT")


LOCAL_TZ = _load_timezone()


def local_now() -> datetime:
    """Tra ve thoi gian hien tai theo timezone cau hinh cua bot."""
    return datetime.now(LOCAL_TZ)


def local_today() -> date:
    """Tra ve ngay hien tai theo timezone cau hinh cua bot."""
    return local_now().date()


def local_today_key() -> str:
    """Key luu trang thai nhac viec moi ngay theo ngay Viet Nam."""
    return local_today().isoformat()

