#!/usr/bin/env python3
"""Fetch Apple Developer Releases RSS, filter by keywords, and generate a filtered RSS feed."""

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent

import feedparser
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "feeds.yml"
OUTPUT_DIR = SCRIPT_DIR / "docs"
OUTPUT_PATH = OUTPUT_DIR / "feed.xml"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


VERSION_RE = re.compile(r"^(\w+)\s+(\d+)")
TITLE_RE = re.compile(
    r"^(iOS|macOS|iPadOS|watchOS)\s+([\d.]+)\s*(?:(beta|RC)\s*(\d*)\s*)?\((\w+)\)$"
)

OS_EMOJI = {
    "iOS": "\U0001f4f1",      # 📱
    "macOS": "\U0001f4bb",    # 💻
    "iPadOS": "\U0001f4f2",   # 📲
    "watchOS": "\u231a",      # ⌚
}


def matches_keywords(title: str, keywords: list[str]) -> bool:
    title_lower = title.lower()
    return any(title_lower.startswith(kw.lower()) for kw in keywords)


def meets_min_version(title: str, min_version: int) -> bool:
    """Check if the major version number in the title is >= min_version.

    Parses titles like 'iOS 26.3.1 (23D8133)' or 'macOS 26.4 beta 3'.
    """
    m = VERSION_RE.match(title)
    if not m:
        return False
    return int(m.group(2)) >= min_version


def is_within_age(entry, max_age_days: int) -> bool:
    if not hasattr(entry, "published_parsed") or not entry.published_parsed:
        return True
    try:
        pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        return pub_dt >= cutoff
    except Exception:
        return True


def fetch_and_filter(feed_cfg: dict) -> tuple[dict, list]:
    url = feed_cfg["url"]
    filters = feed_cfg.get("filters", {})
    keywords = filters.get("keywords", [])
    min_version = filters.get("min_version")
    max_age_days = filters.get("max_age_days")

    print(f"Fetching {url} ...")
    parsed = feedparser.parse(url)

    if parsed.bozo and not parsed.entries:
        print(f"Failed to parse feed: {parsed.bozo_exception}", file=sys.stderr)
        return parsed.feed, []

    filtered = []
    for entry in parsed.entries:
        title = entry.get("title", "")
        if keywords and not matches_keywords(title, keywords):
            continue
        if min_version and not meets_min_version(title, min_version):
            continue
        if max_age_days and not is_within_age(entry, max_age_days):
            continue
        filtered.append(entry)

    return parsed.feed, filtered


def parse_title(title: str) -> dict | None:
    m = TITLE_RE.match(title)
    if not m:
        return None
    os_name, version, pre_tag, pre_num, build = m.groups()
    is_beta = pre_tag is not None
    pre_label = ""
    if pre_tag:
        pre_label = f" {pre_tag.capitalize()}"
        if pre_num:
            pre_label += f" {pre_num}"
    return {
        "os": os_name,
        "version": version,
        "build": build,
        "is_beta": is_beta,
        "pre_label": pre_label,
        "emoji": OS_EMOJI.get(os_name, "\U0001f34e"),
    }


def format_title(info: dict, pub_date: str) -> str:
    tag = info["pre_label"] if info["is_beta"] else ""
    release_type = "\U0001f7e1 测试版" if info["is_beta"] else "\U0001f7e2 正式版"
    parts = [
        f"{info['emoji']} {info['os']} {info['version']}{tag}",
    ]
    if pub_date:
        parts.append(f"\U0001f4c5 {pub_date}")
    parts.append(release_type)
    parts.append(f"Build: {info['build']}")
    return " | ".join(parts)


def format_pub_date_short(entry) -> str:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d")
        except Exception:
            pass
    return ""


def build_rss_xml(feed_meta, entries: list, test_mode: bool = False) -> ElementTree:
    rss = Element("rss", version="2.0")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")

    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = "\U0001f34e Apple OS Releases"
    SubElement(channel, "link").text = "https://developer.apple.com/news/releases/"
    SubElement(channel, "description").text = (
        "iOS, macOS, iPadOS, watchOS — 正式版与测试版更新推送"
    )
    SubElement(channel, "language").text = "en-US"
    SubElement(channel, "lastBuildDate").text = datetime.now(timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )

    for entry in entries:
        raw_title = entry.get("title", "")
        info = parse_title(raw_title)

        item = SubElement(channel, "item")
        SubElement(item, "link").text = entry.get("link", "")
        guid = entry.get("id") or entry.get("link", "")
        if test_mode:
            test_ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            guid = f"{guid}#test-{test_ts}"
        SubElement(item, "guid").text = guid
        SubElement(item, "pubDate").text = entry.get("published", "")

        if info:
            pub_date = format_pub_date_short(entry)
            SubElement(item, "title").text = format_title(info, pub_date)
        else:
            SubElement(item, "title").text = raw_title

    indent(rss, space="  ")
    return ElementTree(rss)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Apple RSS filter")
    parser.add_argument(
        "--test", action="store_true",
        help="Generate unique guids so Slack treats all items as new (for testing)",
    )
    args = parser.parse_args()

    config = load_config()
    all_entries = []

    for feed_cfg in config.get("feeds", []):
        feed_meta, entries = fetch_and_filter(feed_cfg)
        all_entries.extend(entries)
        print(f"  Kept {len(entries)} item(s) after filtering.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tree = build_rss_xml({}, all_entries, test_mode=args.test)
    tree.write(OUTPUT_PATH, encoding="unicode", xml_declaration=True)

    mode = " (TEST MODE - unique guids)" if args.test else ""
    print(f"Generated {OUTPUT_PATH} with {len(all_entries)} item(s).{mode}")


if __name__ == "__main__":
    main()
