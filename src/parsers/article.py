"""Article parser for extracting content from web pages."""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ParsedArticle:
    """Parsed article data."""

    title: str
    text: str
    url: str
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    description: Optional[str] = None
    image_url: Optional[str] = None


class ArticleParser:
    """Parser for extracting article content from URLs."""

    def __init__(self):
        self.settings = get_settings()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.settings.scraper_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def parse(self, url: str) -> ParsedArticle:
        """
        Parse an article from a URL.

        Args:
            url: The URL to parse

        Returns:
            ParsedArticle with extracted content
        """
        logger.info(f"Parsing article: {url}")

        # Fetch the page
        response = self.session.get(url, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "lxml")

        # Extract metadata
        title = self._extract_title(soup)
        author = self._extract_author(soup)
        published_at = self._extract_date(soup)
        description = self._extract_description(soup)
        image_url = self._extract_image(soup, url)

        # Extract main content
        text = self._extract_content(soup)

        if not text:
            # Fallback: try using newspaper3k
            text = self._fallback_extract(url)

        if not title:
            title = self._extract_title_from_url(url)

        return ParsedArticle(
            title=title,
            text=text,
            url=url,
            author=author,
            published_at=published_at,
            description=description,
            image_url=image_url,
        )

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract article title."""
        # Try Open Graph title first
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()

        # Try Twitter title
        twitter_title = soup.find("meta", {"name": "twitter:title"})
        if twitter_title and twitter_title.get("content"):
            return twitter_title["content"].strip()

        # Try h1
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)

        # Try title tag
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True)

        return "Untitled Article"

    def _extract_author(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article author."""
        # Try meta author
        author_meta = soup.find("meta", {"name": "author"})
        if author_meta and author_meta.get("content"):
            return author_meta["content"].strip()

        # Try article:author
        og_author = soup.find("meta", property="article:author")
        if og_author and og_author.get("content"):
            return og_author["content"].strip()

        # Try common author classes
        for selector in [".author", ".byline", "[rel='author']", ".post-author"]:
            author_elem = soup.select_one(selector)
            if author_elem:
                return author_elem.get_text(strip=True)

        return None

    def _extract_date(self, soup: BeautifulSoup) -> Optional[datetime]:
        """Extract publication date."""
        # Try article:published_time
        pub_time = soup.find("meta", property="article:published_time")
        if pub_time and pub_time.get("content"):
            try:
                return datetime.fromisoformat(pub_time["content"].replace("Z", "+00:00"))
            except ValueError:
                pass

        # Try time element
        time_elem = soup.find("time", {"datetime": True})
        if time_elem:
            try:
                return datetime.fromisoformat(time_elem["datetime"].replace("Z", "+00:00"))
            except ValueError:
                pass

        return None

    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article description."""
        # Try Open Graph description
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return og_desc["content"].strip()

        # Try meta description
        meta_desc = soup.find("meta", {"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return meta_desc["content"].strip()

        return None

    def _extract_image(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Extract article image."""
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            return og_image["content"]

        return None

    def _extract_content(self, soup: BeautifulSoup) -> str:
        """Extract main article content."""
        # Remove unwanted elements
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()

        # Try common article containers
        content_selectors = [
            "article",
            "[role='main']",
            ".post-content",
            ".article-content",
            ".entry-content",
            ".content",
            ".post-body",
            ".article-body",
            "main",
        ]

        for selector in content_selectors:
            content = soup.select_one(selector)
            if content:
                text = self._clean_text(content.get_text(separator="\n"))
                if len(text) > 200:  # Minimum content threshold
                    return text

        # Fallback: get body text
        body = soup.find("body")
        if body:
            return self._clean_text(body.get_text(separator="\n"))

        return ""

    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        # Remove excessive whitespace
        text = re.sub(r"\n\s*\n", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)

        # Remove lines that are likely navigation/UI elements
        lines = text.split("\n")
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            # Skip very short lines that are likely UI elements
            if len(line) < 20 and any(
                x in line.lower()
                for x in ["subscribe", "share", "comment", "login", "sign up", "follow"]
            ):
                continue
            cleaned_lines.append(line)

        return "\n".join(cleaned_lines).strip()

    def _fallback_extract(self, url: str) -> str:
        """Fallback extraction using newspaper3k."""
        try:
            from newspaper import Article

            article = Article(url)
            article.download()
            article.parse()
            return article.text
        except Exception as e:
            logger.warning(f"Fallback extraction failed: {e}")
            return ""

    def _extract_title_from_url(self, url: str) -> str:
        """Extract a title from the URL path."""
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if path:
            # Take last path segment and clean it up
            segment = path.split("/")[-1]
            segment = segment.replace("-", " ").replace("_", " ")
            segment = re.sub(r"\.\w+$", "", segment)  # Remove extension
            return segment.title()
        return parsed.netloc
