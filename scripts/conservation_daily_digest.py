#!/usr/bin/env python3
"""Build a conservation news digest and deliver it through the Zalo reminder store."""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


VN_TZ = timezone(timedelta(hours=7))
BASE_DIR = Path(__file__).resolve().parents[1]
REMINDER_STORE = BASE_DIR / "data" / "zalo_reminders.json"
LOG_DIR = BASE_DIR / "runtime-logs"

ZALO_PERSONAL_ID = "9135812107335674691"
ZALO_PERSONAL_NAME = "Phạm Văn Vương Quốc"

KEYWORDS = (
    "bảo tồn",
    "rừng",
    "bảo vệ rừng",
    "động vật",
    "thực vật",
    "cứu hộ",
    "môi trường",
    "kiểm lâm",
    "lâm nghiệp",
    "đa dạng sinh học",
    "viễn thám",
    "wildlife",
    "forest",
    "biodiversity",
    "remote sensing",
)

QUERIES = (
    "bảo tồn rừng Việt Nam",
    "bảo vệ rừng kiểm lâm Việt Nam",
    "động vật hoang dã cứu hộ Việt Nam",
    "đa dạng sinh học Việt Nam",
    "lâm nghiệp viễn thám rừng",
    "môi trường rừng bảo tồn",
    "wildlife conservation Vietnam",
    "forest biodiversity remote sensing",
)

RSS_FEEDS = (
    "https://news.mongabay.com/feed/",
    "https://e.vnexpress.net/rss/environment.rss",
    "https://www.iucn.org/rss.xml",
)

ZALO_MESSAGE_LIMIT = 2400


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published: datetime | None
    summary: str
    score: int


def fetch_text(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "YokDonConservationDigest/1.0 (+https://yokdon.example)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(VN_TZ)
    except (TypeError, ValueError):
        return None


def node_text(node: ET.Element, tag: str) -> str:
    found = node.find(tag)
    return clean_text(found.text if found is not None and found.text else "")


def item_source(node: ET.Element, fallback: str) -> str:
    source = node.find("source")
    if source is not None and source.text:
        return clean_text(source.text)
    return fallback


def score_item(title: str, summary: str) -> int:
    text = f"{title} {summary}".lower()
    score = 0
    for keyword in KEYWORDS:
        if keyword.lower() in text:
            score += 3 if " " in keyword else 1
    if "việt nam" in text or "vietnam" in text:
        score += 4
    if any(term in text for term in ("illegal logging", "phá rừng", "cháy rừng", "kiểm lâm")):
        score += 3
    return score


def google_news_feed(query: str) -> str:
    encoded = urllib.parse.quote_plus(f"{query} when:7d")
    return f"https://news.google.com/rss/search?q={encoded}&hl=vi&gl=VN&ceid=VN:vi"


def parse_rss(xml_text: str, fallback_source: str) -> list[NewsItem]:
    root = ET.fromstring(xml_text)
    items: list[NewsItem] = []
    for node in root.findall(".//item"):
        title = node_text(node, "title")
        link = node_text(node, "link")
        summary = node_text(node, "description")
        published = parse_date(node_text(node, "pubDate"))
        source = item_source(node, fallback_source)
        if not title or not link:
            continue
        score = score_item(title, summary)
        items.append(NewsItem(title, link, source, published, summary, score))
    return items


def collect_items() -> tuple[list[NewsItem], list[str]]:
    urls = [google_news_feed(query) for query in QUERIES]
    urls.extend(RSS_FEEDS)
    items: list[NewsItem] = []
    errors: list[str] = []
    for url in urls:
        try:
            xml_text = fetch_text(url)
            fallback = urllib.parse.urlparse(url).netloc
            items.extend(parse_rss(xml_text, fallback))
        except (urllib.error.URLError, TimeoutError, ET.ParseError, UnicodeError) as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    return items, errors


def dedupe(items: Iterable[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    result: list[NewsItem] = []
    for item in items:
        key = re.sub(r"\W+", "", item.title.lower())[:120]
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def select_top(items: list[NewsItem], limit: int = 10) -> list[NewsItem]:
    now = datetime.now(VN_TZ)

    def sort_key(item: NewsItem) -> tuple[int, float]:
        published = item.published or datetime(1970, 1, 1, tzinfo=VN_TZ)
        age_days = max((now - published).total_seconds() / 86400, 0)
        freshness = max(30 - age_days, 0)
        return (item.score, freshness)

    relevant = [item for item in items if item.score > 0]
    return sorted(dedupe(relevant), key=sort_key, reverse=True)[:limit]


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(limit - 3, 1)].rsplit(" ", 1)[0].rstrip(" ,.;") + "..."


def compact_link(link: str) -> str:
    parsed = urllib.parse.urlparse(link)
    if parsed.netloc == "news.google.com" and "/rss/articles/" in parsed.path:
        return urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path.replace("/rss/articles/", "/articles/"), "", "", "")
        )
    return link


def short_summary(item: NewsItem, limit: int = 85) -> str:
    text = item.summary or item.title
    text = re.sub(r"\s*Read more.*$", "", text, flags=re.IGNORECASE)
    return truncate(text, limit)


def format_digest(items: list[NewsItem], errors: list[str]) -> str:
    now = datetime.now(VN_TZ)
    lines = [
        f"Bản tin bảo tồn sáng - {now:%d/%m/%Y %H:%M} (giờ Việt Nam)",
        "",
        "10 thông tin liên quan đến bảo tồn, rừng, bảo vệ rừng, động vật, thực vật, cứu hộ, môi trường, kiểm lâm, lâm nghiệp, đa dạng sinh học và viễn thám.",
        "",
    ]
    for idx, item in enumerate(items, start=1):
        published = item.published.strftime("%d/%m/%Y") if item.published else "Chưa rõ ngày"
        lines.extend(
            [
                f"{idx}. {truncate(item.title, 105)}",
                f"Nguồn/ngày: {truncate(item.source, 42)} - {published}",
                f"Tóm tắt: {short_summary(item)}",
                f"Link: {compact_link(item.link)}",
                "",
            ]
        )
    if errors:
        lines.extend(
            [
                "Ghi chú: một số nguồn không truy cập được; bản tin dùng các nguồn còn truy cập được.",
            ]
        )
    digest = "\n".join(lines).strip()
    if len(digest) <= ZALO_MESSAGE_LIMIT:
        return digest

    shorter_lines = lines[:4]
    for idx, item in enumerate(items, start=1):
        published = item.published.strftime("%d/%m") if item.published else "?"
        shorter_lines.extend(
            [
                f"{idx}. {truncate(item.title, 86)}",
                f"Nguồn: {truncate(item.source, 28)} - {published}",
                f"Tóm tắt: {short_summary(item, 55)}",
                f"Link: {compact_link(item.link)}",
                "",
            ]
        )
    return "\n".join(shorter_lines).strip()


def split_for_zalo(text: str, limit: int = ZALO_MESSAGE_LIMIT) -> list[str]:
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= limit:
            current = paragraph
        else:
            lines = paragraph.splitlines()
            current = ""
            for line in lines:
                candidate_line = line if not current else f"{current}\n{line}"
                if len(candidate_line) <= limit:
                    current = candidate_line
                else:
                    if current:
                        chunks.append(current)
                    current = line[:limit]
    if current:
        chunks.append(current)
    if len(chunks) <= 1:
        return chunks
    total = len(chunks)
    return [f"{chunk}\n\n(Phần {idx}/{total})" for idx, chunk in enumerate(chunks, start=1)]


def read_reminders() -> list[dict]:
    REMINDER_STORE.parent.mkdir(parents=True, exist_ok=True)
    if REMINDER_STORE.exists():
        reminders = json.loads(REMINDER_STORE.read_text(encoding="utf-8"))
        if not isinstance(reminders, list):
            raise ValueError(f"Invalid reminder store: {REMINDER_STORE}")
    else:
        reminders = []
    return reminders


def write_reminders(reminders: list[dict]) -> None:
    tmp_path = REMINDER_STORE.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(reminders, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(REMINDER_STORE)


def append_zalo_reminders(text: str) -> list[str]:
    reminders = read_reminders()

    now = datetime.now(timezone.utc)
    chunks = split_for_zalo(text)
    ids: list[str] = []
    base = int(time.time() * 1000)
    for index, chunk in enumerate(chunks):
        reminder_id = f"zr_digest_{base:x}_{index + 1}"
        ids.append(reminder_id)
        reminders.append(
            {
                "id": reminder_id,
                "zaloId": ZALO_PERSONAL_ID,
                "threadType": 0,
                "chatName": ZALO_PERSONAL_NAME,
                "senderId": ZALO_PERSONAL_ID,
                "senderName": ZALO_PERSONAL_NAME,
                "text": chunk,
                "remindAtIso": (now - timedelta(seconds=2)).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "createdAtIso": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "status": "pending",
                "attempts": 0,
            }
        )
    write_reminders(reminders)
    return ids


def reminder_status(reminder_id: str) -> dict:
    reminders = read_reminders()
    for reminder in reminders:
        if reminder.get("id") == reminder_id:
            return reminder
    raise KeyError(reminder_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-send", action="store_true", help="Print digest only; do not write Zalo reminder")
    parser.add_argument("--wait-sent", type=int, default=0, help="Wait up to N seconds for reminder status=sent")
    args = parser.parse_args()

    items, errors = collect_items()
    selected = select_top(items, 10)
    if len(selected) < 10:
        print(f"Only found {len(selected)} relevant items", file=sys.stderr)
    digest = format_digest(selected, errors)
    print(digest)

    if args.no_send:
        return 0

    reminder_ids = append_zalo_reminders(digest)
    print(f"\n[Zalo] queued reminder ids={','.join(reminder_ids)}", file=sys.stderr)
    deadline = time.time() + args.wait_sent
    while args.wait_sent > 0 and time.time() < deadline:
        statuses = [reminder_status(reminder_id) for reminder_id in reminder_ids]
        if all(status.get("status") == "sent" for status in statuses):
            print(json.dumps({
                "reminderIds": reminder_ids,
                "status": "sent",
                "sentAtIso": max((status.get("sentAtIso") or "") for status in statuses),
            }, ensure_ascii=False))
            return 0
        failed = [status for status in statuses if status.get("status") == "failed"]
        if failed:
            print(json.dumps(failed, ensure_ascii=False), file=sys.stderr)
            return 2
        time.sleep(5)
    if args.wait_sent > 0:
        print(json.dumps([reminder_status(reminder_id) for reminder_id in reminder_ids], ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
