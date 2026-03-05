#!/usr/bin/env python3
"""Fetch Apple Developer Releases RSS, filter by keywords, and post new items to Slack."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import feedparser
import requests
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "feeds.yml"
SENT_ITEMS_PATH = SCRIPT_DIR / "sent_items.json"
MAX_SENT_ITEMS = 500


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sent_items():
    if not SENT_ITEMS_PATH.exists():
        return []
    with open(SENT_ITEMS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("sent", [])


def save_sent_items(sent: list):
    sent = sent[-MAX_SENT_ITEMS:]
    with open(SENT_ITEMS_PATH, "w", encoding="utf-8") as f:
        json.dump({"sent": sent}, f, indent=2, ensure_ascii=False)


def matches_keywords(title: str, keywords: list[str]) -> bool:
    """Return True if the title starts with any of the keywords (case-insensitive)."""
    title_lower = title.lower()
    return any(title_lower.startswith(kw.lower()) for kw in keywords)


def format_slack_message(items: list[dict]) -> dict:
    """Build a Slack Block Kit message from a list of RSS items."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🍎 Apple Developer Release", "emoji": True},
        },
        {"type": "divider"},
    ]

    for item in items:
        title = item["title"]
        link = item["link"]
        pub_date = item.get("pub_date", "")

        text_parts = [f"*{title}*"]
        if pub_date:
            text_parts.append(f"📅 {pub_date}")
        text_parts.append(f"🔗 <{link}|View release>")

        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(text_parts)},
            }
        )

    return {"blocks": blocks}


def post_to_slack(webhook_url: str, payload: dict) -> bool:
    resp = requests.post(webhook_url, json=payload, timeout=30)
    if resp.status_code != 200:
        print(f"Slack responded with {resp.status_code}: {resp.text}", file=sys.stderr)
        return False
    return True


def format_pub_date(entry) -> str:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    return entry.get("published", "")


def fetch_and_filter(feed_cfg: dict, sent_guids: set) -> list[dict]:
    """Fetch one RSS feed, filter by keywords, and return new items."""
    url = feed_cfg["url"]
    keywords = feed_cfg.get("filters", {}).get("keywords", [])

    print(f"Fetching {url} ...")
    parsed = feedparser.parse(url)

    if parsed.bozo and not parsed.entries:
        print(f"Failed to parse feed: {parsed.bozo_exception}", file=sys.stderr)
        return []

    new_items = []
    for entry in parsed.entries:
        guid = entry.get("id") or entry.get("link", "")
        title = entry.get("title", "")

        if guid in sent_guids:
            continue
        if keywords and not matches_keywords(title, keywords):
            continue

        new_items.append(
            {
                "guid": guid,
                "title": title,
                "link": entry.get("link", ""),
                "pub_date": format_pub_date(entry),
            }
        )

    return new_items


def main():
    parser = argparse.ArgumentParser(description="RSS to Slack notifier")
    parser.add_argument("--force", action="store_true", help="Ignore sent history and push latest items")
    parser.add_argument("--dry-run", action="store_true", help="Print messages without posting to Slack")
    args = parser.parse_args()

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url and not args.dry_run:
        print("Error: SLACK_WEBHOOK_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    config = load_config()
    sent_guids = set() if args.force else set(load_sent_items())
    all_new_items = []

    for feed_cfg in config.get("feeds", []):
        items = fetch_and_filter(feed_cfg, sent_guids)
        all_new_items.extend(items)

    if not all_new_items:
        print("No new items to push.")
        return

    all_new_items.reverse()
    print(f"Found {len(all_new_items)} new item(s).")

    payload = format_slack_message(all_new_items)

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        if post_to_slack(webhook_url, payload):
            print("Posted to Slack successfully.")
        else:
            print("Failed to post to Slack.", file=sys.stderr)
            sys.exit(1)

    sent_list = load_sent_items()
    for item in all_new_items:
        if item["guid"] not in sent_list:
            sent_list.append(item["guid"])
    save_sent_items(sent_list)
    print(f"Updated sent_items.json ({len(sent_list)} entries).")


if __name__ == "__main__":
    main()
