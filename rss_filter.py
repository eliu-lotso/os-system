#!/usr/bin/env python3
"""Fetch Apple Developer Releases RSS, filter by keywords, and generate a filtered RSS feed."""

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from xml.dom import minidom

import feedparser
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "feeds.yml"
OUTPUT_DIR = SCRIPT_DIR / "docs"
OUTPUT_PATH = OUTPUT_DIR / "feed.xml"
FEED_URL = "https://eliu-lotso.github.io/os-system/feed.xml"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


VERSION_RE = re.compile(r"^(\w+)\s+(\d+)")
TITLE_RE = re.compile(
    r"^(iOS|macOS|iPadOS|watchOS)\s+([\d.]+)\s*(?:(beta|RC)\s*(\d*)\s*)?\((\w+)\)$"
)

OS_EMOJI = {
    "iOS": "\U0001f4f1",
    "macOS": "\U0001f4bb",
    "iPadOS": "\U0001f4f2",
    "watchOS": "\u231a",
}


def matches_keywords(title: str, keywords: list[str]) -> bool:
    title_lower = title.lower()
    return any(title_lower.startswith(kw.lower()) for kw in keywords)


def meets_min_version(title: str, min_version: int) -> bool:
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


def parse_title(title: str) -> Optional[dict]:
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


def format_title_line(info: dict) -> str:
    """Concise title for the clickable header in Slack."""
    tag = info["pre_label"] if info["is_beta"] else ""
    release_type = "\U0001f7e1 测试版" if info["is_beta"] else "\U0001f7e2 正式版"
    return f"{info['emoji']} {info['os']} {info['version']}{tag} | {release_type}"


def format_description_line(info: dict, pub_date: str) -> str:
    """Supplementary details shown below the title in Slack."""
    parts = []
    if pub_date:
        parts.append(f"\U0001f4c5 {pub_date}")
    parts.append(f"Build: {info['build']}")
    return " | ".join(parts)


def format_pub_date_short(entry) -> str:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d")
        except Exception:
            pass
    return ""


def format_pub_date_gmt(entry) -> str:
    """Convert entry's published_parsed to RFC 822 GMT format."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
        except Exception:
            pass
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def build_rss_xml(entries: list, test_mode: bool = False) -> str:
    """Build RSS XML string using minidom (matching qweather's working format)."""
    impl = minidom.getDOMImplementation()
    doc = impl.createDocument(None, "rss", None)
    rss = doc.documentElement
    rss.setAttribute("version", "2.0")
    rss.setAttribute("xmlns:atom", "http://www.w3.org/2005/Atom")

    channel = doc.createElement("channel")
    rss.appendChild(channel)

    def el(tag, text):
        node = doc.createElement(tag)
        node.appendChild(doc.createTextNode(text))
        return node

    now = datetime.now(timezone.utc)

    channel.appendChild(el("title", "\U0001f34e Apple OS Releases"))
    channel.appendChild(el("link", FEED_URL))
    channel.appendChild(el("description", "iOS, macOS, iPadOS, watchOS — 正式版与测试版更新推送"))

    atom_link = doc.createElement("atom:link")
    atom_link.setAttribute("href", FEED_URL)
    atom_link.setAttribute("rel", "self")
    atom_link.setAttribute("type", "application/rss+xml")
    channel.appendChild(atom_link)

    for entry in entries:
        raw_title = entry.get("title", "")
        info = parse_title(raw_title)
        pub_date_short = format_pub_date_short(entry)

        if info:
            title_text = format_title_line(info)
            desc_text = format_description_line(info, pub_date_short)
        else:
            title_text = raw_title
            desc_text = pub_date_short or raw_title

        item = doc.createElement("item")

        item.appendChild(el("title", title_text))

        link_url = entry.get("link", "")
        if link_url:
            item.appendChild(el("link", link_url))

        if test_mode:
            pub_date_rfc = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
        else:
            pub_date_rfc = format_pub_date_gmt(entry)
        item.appendChild(el("pubDate", pub_date_rfc))

        guid_value = entry.get("id") or link_url
        if test_mode:
            test_ts = now.strftime("%Y%m%dT%H%M%S")
            guid_value = f"test-{test_ts}-{guid_value}"
        guid_node = doc.createElement("guid")
        guid_node.setAttribute("isPermaLink", "false")
        guid_node.appendChild(doc.createTextNode(guid_value))
        item.appendChild(guid_node)

        desc_node = doc.createElement("description")
        desc_node.appendChild(doc.createCDATASection(desc_text))
        item.appendChild(desc_node)

        channel.appendChild(item)

    return doc.toprettyxml(indent="  ")


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

    xml_str = build_rss_xml(all_entries, test_mode=args.test)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(xml_str)

    mode = " (TEST MODE)" if args.test else ""
    print(f"Generated {OUTPUT_PATH} with {len(all_entries)} item(s).{mode}")


if __name__ == "__main__":
    main()
