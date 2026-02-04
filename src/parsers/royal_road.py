"""Royal Road web novel scraper."""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class Chapter:
    """A chapter from a Royal Road book."""

    title: str
    url: str
    chapter_number: int
    content: str = ""
    published_at: Optional[datetime] = None


@dataclass
class RoyalRoadBook:
    """Parsed Royal Road book data."""

    title: str
    url: str
    author: Optional[str] = None
    description: Optional[str] = None
    cover_image: Optional[str] = None
    chapters: List[Chapter] = field(default_factory=list)


class RoyalRoadParser:
    """Scraper for Royal Road web novels."""

    BASE_URL = "https://www.royalroad.com"

    def __init__(self):
        self.settings = get_settings()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.settings.scraper_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def parse(self, book_url: str, fetch_chapters: bool = False) -> RoyalRoadBook:
        """
        Parse a Royal Road book page.

        Args:
            book_url: URL to the book's main page
            fetch_chapters: Whether to fetch full chapter content

        Returns:
            RoyalRoadBook with metadata and chapter list
        """
        logger.info(f"Parsing Royal Road book: {book_url}")

        # Fetch book page
        response = self.session.get(book_url, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "lxml")

        # Extract book metadata
        title = self._extract_title(soup)
        author = self._extract_author(soup)
        description = self._extract_description(soup)
        cover_image = self._extract_cover(soup)

        # Get chapter list from table of contents
        chapters = self._extract_chapters(soup, book_url)

        if fetch_chapters:
            for chapter in chapters:
                self._fetch_chapter_content(chapter)

        logger.info(f"Found {len(chapters)} chapters for '{title}'")

        return RoyalRoadBook(
            title=title,
            url=book_url,
            author=author,
            description=description,
            cover_image=cover_image,
            chapters=chapters,
        )

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract book title."""
        title_elem = soup.select_one("h1.font-white")
        if title_elem:
            return title_elem.get_text(strip=True)

        # Fallback
        title_elem = soup.find("h1")
        if title_elem:
            return title_elem.get_text(strip=True)

        return "Untitled Book"

    def _extract_author(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract book author."""
        author_elem = soup.select_one("h4.font-white a")
        if author_elem:
            return author_elem.get_text(strip=True)

        return None

    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract book description."""
        desc_elem = soup.select_one(".description .hidden-content")
        if desc_elem:
            return desc_elem.get_text(strip=True)

        desc_elem = soup.select_one(".description")
        if desc_elem:
            return desc_elem.get_text(strip=True)

        return None

    def _extract_cover(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract book cover image URL."""
        cover_elem = soup.select_one(".fic-header img.img-responsive")
        if cover_elem and cover_elem.get("src"):
            return cover_elem["src"]

        return None

    def _extract_chapters(self, soup: BeautifulSoup, book_url: str) -> List[Chapter]:
        """Extract chapter list from the page."""
        chapters = []

        # Find chapter table
        chapter_table = soup.select_one("#chapters tbody")
        if not chapter_table:
            # Try the table of contents page
            toc_url = book_url.rstrip("/") + "/table-of-contents"
            try:
                response = self.session.get(toc_url, timeout=30)
                if response.ok:
                    toc_soup = BeautifulSoup(response.content, "lxml")
                    chapter_table = toc_soup.select_one("#chapters tbody")
            except Exception as e:
                logger.warning(f"Failed to fetch TOC page: {e}")

        if not chapter_table:
            return chapters

        # Parse chapter rows
        rows = chapter_table.select("tr")
        for idx, row in enumerate(rows):
            link = row.select_one("a")
            if not link:
                continue

            title = link.get_text(strip=True)
            url = link.get("href", "")
            if url and not url.startswith("http"):
                url = urljoin(self.BASE_URL, url)

            # Try to extract publish date
            published_at = None
            time_elem = row.select_one("time")
            if time_elem and time_elem.get("datetime"):
                try:
                    published_at = datetime.fromisoformat(
                        time_elem["datetime"].replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            chapters.append(Chapter(
                title=title,
                url=url,
                chapter_number=idx + 1,
                published_at=published_at,
            ))

        return chapters

    def fetch_chapter(self, chapter: Chapter) -> Chapter:
        """
        Fetch full content for a chapter.

        Args:
            chapter: Chapter object with URL

        Returns:
            Updated chapter with content
        """
        self._fetch_chapter_content(chapter)
        return chapter

    def _fetch_chapter_content(self, chapter: Chapter) -> None:
        """Fetch and populate chapter content."""
        logger.info(f"Fetching chapter: {chapter.title}")

        try:
            response = self.session.get(chapter.url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, "lxml")

            # Find chapter content
            content_elem = soup.select_one(".chapter-content")
            if content_elem:
                # Remove author notes
                for note in content_elem.select(".author-note"):
                    note.decompose()

                # Get text
                chapter.content = self._clean_content(content_elem)

        except Exception as e:
            logger.error(f"Failed to fetch chapter {chapter.url}: {e}")

    def _clean_content(self, element: BeautifulSoup) -> str:
        """Clean chapter content to plain text."""
        # Remove script/style
        for tag in element.find_all(["script", "style"]):
            tag.decompose()

        # Get text with paragraph breaks
        text = element.get_text(separator="\n\n")

        # Clean up whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)

        return text.strip()

    def preview(self, book_url: str) -> RoyalRoadBook:
        """
        Get a preview of a book without fetching chapter content.

        Args:
            book_url: URL to the book's main page

        Returns:
            RoyalRoadBook with metadata and chapter list (no content)
        """
        return self.parse(book_url, fetch_chapters=False)
