"""Tests for content parsers."""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from src.parsers.article import ArticleParser, ParsedArticle
from src.parsers.rss_feed import RSSFeedParser, ParsedFeed, FeedItem
from src.parsers.royal_road import RoyalRoadParser, RoyalRoadBook, Chapter


class TestArticleParser:
    """Tests for ArticleParser."""

    def test_clean_text(self):
        """Test text cleaning."""
        parser = ArticleParser()
        text = "Hello   world\n\n\n\nTest\n  \n  More"
        cleaned = parser._clean_text(text)
        assert "\n\n\n" not in cleaned

    def test_extract_title_from_url(self):
        """Test extracting title from URL."""
        parser = ArticleParser()
        title = parser._extract_title_from_url("https://example.com/my-great-article")
        assert title == "My Great Article"

    @patch("src.parsers.article.requests.Session")
    def test_parse_article(self, mock_session_class):
        """Test parsing an article."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        
        mock_response = Mock()
        mock_response.content = b"""
        <html>
        <head>
            <title>Test Article</title>
            <meta property="og:title" content="Test Article Title">
            <meta name="author" content="Test Author">
        </head>
        <body>
            <article>
                <p>This is the article content. It has multiple sentences.</p>
                <p>Another paragraph with more content to meet the threshold.</p>
            </article>
        </body>
        </html>
        """
        mock_response.raise_for_status = Mock()
        mock_session.get.return_value = mock_response

        parser = ArticleParser()
        parser.session = mock_session
        
        result = parser.parse("http://example.com/article")
        
        assert result.title == "Test Article Title"
        assert result.author == "Test Author"
        assert "article content" in result.text


class TestRSSFeedParser:
    """Tests for RSSFeedParser."""

    def test_html_to_text(self):
        """Test HTML to text conversion."""
        parser = RSSFeedParser()
        html = "<p>Hello <b>world</b></p><script>alert('x')</script>"
        text = parser._html_to_text(html)
        assert "Hello" in text
        assert "world" in text
        assert "alert" not in text

    @patch("src.parsers.rss_feed.feedparser.parse")
    def test_parse_feed(self, mock_feedparser):
        """Test parsing an RSS feed."""
        mock_feedparser.return_value = Mock(
            bozo=False,
            feed={
                "title": "Test Feed",
                "description": "A test feed",
            },
            entries=[
                {
                    "title": "Entry 1",
                    "link": "http://example.com/1",
                    "summary": "Summary 1",
                    "published_parsed": None,
                },
                {
                    "title": "Entry 2",
                    "link": "http://example.com/2",
                    "summary": "Summary 2",
                    "published_parsed": None,
                },
            ],
        )

        parser = RSSFeedParser()
        result = parser.parse("http://example.com/feed", fetch_content=False)

        assert result.title == "Test Feed"
        assert len(result.items) == 2
        assert result.items[0].title == "Entry 1"


class TestRoyalRoadParser:
    """Tests for RoyalRoadParser."""

    @patch("src.parsers.royal_road.requests.Session")
    def test_extract_title(self, mock_session_class):
        """Test extracting book title."""
        parser = RoyalRoadParser()
        
        from bs4 import BeautifulSoup
        html = '<html><body><h1 class="font-white">Test Book Title</h1></body></html>'
        soup = BeautifulSoup(html, "lxml")
        
        title = parser._extract_title(soup)
        assert title == "Test Book Title"

    @patch("src.parsers.royal_road.requests.Session")
    def test_extract_author(self, mock_session_class):
        """Test extracting book author."""
        parser = RoyalRoadParser()
        
        from bs4 import BeautifulSoup
        html = '<html><body><h4 class="font-white"><a>Test Author</a></h4></body></html>'
        soup = BeautifulSoup(html, "lxml")
        
        author = parser._extract_author(soup)
        assert author == "Test Author"

    def test_clean_content(self):
        """Test cleaning chapter content."""
        parser = RoyalRoadParser()
        
        from bs4 import BeautifulSoup
        html = """
        <div>
            <p>First paragraph.</p>
            <script>bad script</script>
            <p>Second paragraph.</p>
        </div>
        """
        soup = BeautifulSoup(html, "lxml")
        
        content = parser._clean_content(soup.find("div"))
        assert "First paragraph" in content
        assert "Second paragraph" in content
        assert "bad script" not in content
