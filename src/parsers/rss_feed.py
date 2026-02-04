"""RSS feed parser for subscribing to feeds."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from time import mktime

import feedparser
import requests
from bs4 import BeautifulSoup

from src.config import get_settings
from .article import ArticleParser

logger = logging.getLogger(__name__)


@dataclass
class FeedItem:
    """An item from an RSS feed."""

    title: str
    url: str
    content: str = ""
    published_at: Optional[datetime] = None
    author: Optional[str] = None
    description: Optional[str] = None


@dataclass
class ParsedFeed:
    """Parsed RSS feed data."""

    title: str
    url: str
    description: Optional[str] = None
    items: List[FeedItem] = field(default_factory=list)
    image_url: Optional[str] = None


class RSSFeedParser:
    """Parser for RSS/Atom feeds."""

    def __init__(self):
        self.settings = get_settings()
        self.article_parser = ArticleParser()

    def parse(self, feed_url: str, fetch_content: bool = True) -> ParsedFeed:
        """
        Parse an RSS feed.

        Args:
            feed_url: URL of the RSS feed
            fetch_content: Whether to fetch full content for each item

        Returns:
            ParsedFeed with feed metadata and items
        """
        logger.info(f"Parsing RSS feed: {feed_url}")

        # Parse the feed
        feed = feedparser.parse(feed_url)

        if feed.bozo and not feed.entries:
            raise ValueError(f"Failed to parse feed: {feed.bozo_exception}")

        # Extract feed metadata
        title = feed.feed.get("title", "Untitled Feed")
        description = feed.feed.get("description") or feed.feed.get("subtitle")
        image_url = None
        if feed.feed.get("image"):
            image_url = feed.feed.image.get("href") or feed.feed.image.get("url")

        # Parse items
        items = []
        for entry in feed.entries:
            item = self._parse_entry(entry, fetch_content)
            if item:
                items.append(item)

        logger.info(f"Parsed {len(items)} items from feed")

        return ParsedFeed(
            title=title,
            url=feed_url,
            description=description,
            items=items,
            image_url=image_url,
        )

    def _parse_entry(self, entry: dict, fetch_content: bool) -> Optional[FeedItem]:
        """Parse a single feed entry."""
        title = entry.get("title", "Untitled")
        url = entry.get("link", "")

        if not url:
            return None

        # Get publication date
        published_at = None
        if entry.get("published_parsed"):
            try:
                published_at = datetime.fromtimestamp(mktime(entry.published_parsed))
            except Exception:
                pass
        elif entry.get("updated_parsed"):
            try:
                published_at = datetime.fromtimestamp(mktime(entry.updated_parsed))
            except Exception:
                pass

        # Get author
        author = entry.get("author")

        # Get content/description
        content = ""
        description = entry.get("summary", "")

        # Try to get full content from feed
        if entry.get("content"):
            for content_item in entry.content:
                if content_item.get("type", "").startswith("text"):
                    content = content_item.get("value", "")
                    break

        # If content is HTML, clean it
        if content:
            content = self._html_to_text(content)
        elif description:
            content = self._html_to_text(description)

        # Optionally fetch full article content
        if fetch_content and url and len(content) < 500:
            try:
                article = self.article_parser.parse(url)
                if article.text and len(article.text) > len(content):
                    content = article.text
            except Exception as e:
                logger.warning(f"Failed to fetch full content for {url}: {e}")

        return FeedItem(
            title=title,
            url=url,
            content=content,
            published_at=published_at,
            author=author,
            description=description[:500] if description else None,
        )

    def _html_to_text(self, html: str) -> str:
        """Convert HTML content to plain text."""
        if not html:
            return ""

        soup = BeautifulSoup(html, "lxml")

        # Remove unwanted elements
        for tag in soup.find_all(["script", "style"]):
            tag.decompose()

        # Get text with newlines for block elements
        text = soup.get_text(separator="\n")

        # Clean up whitespace
        lines = [line.strip() for line in text.split("\n")]
        text = "\n".join(line for line in lines if line)

        return text

    def preview(self, feed_url: str) -> ParsedFeed:
        """
        Get a preview of a feed without fetching full content.

        Args:
            feed_url: URL of the RSS feed

        Returns:
            ParsedFeed with basic metadata and item list
        """
        return self.parse(feed_url, fetch_content=False)
