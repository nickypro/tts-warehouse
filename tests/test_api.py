"""Tests for API routes."""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock

# Set test database before imports
os.environ["DATABASE_PATH"] = ":memory:"

from fastapi.testclient import TestClient
from src.main import app
from src.database import init_db


@pytest.fixture
def client():
    """Create test client with fresh database."""
    init_db()
    return TestClient(app)


class TestSourceEndpoints:
    """Tests for source API endpoints."""

    def test_list_sources_empty(self, client):
        """Test listing sources when empty."""
        response = client.get("/api/sources")
        assert response.status_code == 200
        assert response.json() == []

    @patch("src.services.content_service.ArticleParser")
    def test_add_article(self, mock_parser_class, client):
        """Test adding an article returns immediately."""
        mock_parser = Mock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = Mock(
            title="Test Article",
            text="This is the article content.",
            url="http://test.com/article",
            author="Test Author",
            published_at=None,
            description="Test description",
            image_url=None,
            image_urls=[],
        )

        response = client.post(
            "/api/sources/article",
            json={"url": "http://test.com/article"},
        )

        assert response.status_code == 200
        data = response.json()
        # Source is the unified "Manually Added Articles" source
        assert data["name"] == "Manually Added Articles"
        assert data["type"] == "article"
        assert "feed_url" in data

    def test_add_article_invalid_url(self, client):
        """Test adding article with connection error."""
        response = client.post(
            "/api/sources/article",
            json={"url": "http://nonexistent.invalid/article"},
        )
        assert response.status_code == 400

    @patch("src.services.content_service.RSSFeedParser")
    def test_add_feed(self, mock_parser_class, client):
        """Test adding a feed returns immediately without blocking on content fetch."""
        mock_parser = Mock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = Mock(
            title="Test Feed",
            url="http://test.com/feed",
            description="A test feed",
            image_url=None,
            items=[
                Mock(
                    title="Entry 1",
                    url="http://test.com/1",
                    content="Short",
                    published_at=None,
                    author=None,
                    description=None,
                ),
                Mock(
                    title="Entry 2",
                    url="http://test.com/2",
                    content="Also short",
                    published_at=None,
                    author=None,
                    description=None,
                ),
            ],
        )

        response = client.post(
            "/api/sources/feed",
            json={"url": "http://test.com/feed"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Feed"
        assert data["type"] == "rss_feed"
        assert data["item_count"] == 2

        # Verify feed was parsed WITHOUT fetching full content
        mock_parser.parse.assert_called_once_with("http://test.com/feed", fetch_content=False)

    @patch("src.services.content_service.ContentService.enrich_items")
    @patch("src.services.content_service.RSSFeedParser")
    def test_add_feed_does_not_generate_summaries_inline(
        self, mock_parser_class, mock_enrich, client
    ):
        """Test that adding a feed does NOT call summary generation synchronously.

        enrich_items is mocked because TestClient runs background tasks inline.
        We verify that add_rss_feed itself doesn't call generate_summary.
        """
        mock_parser = Mock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = Mock(
            title="Test Feed",
            url="http://test.com/feed",
            description="A test feed",
            image_url=None,
            items=[
                Mock(
                    title="Entry 1",
                    url="http://test.com/1",
                    content="Some content here",
                    published_at=None,
                    author=None,
                    description=None,
                ),
            ],
        )

        with patch("src.services.summary_service.generate_summary") as mock_summary:
            response = client.post(
                "/api/sources/feed",
                json={"url": "http://test.com/feed"},
            )

            assert response.status_code == 200
            # Summary generation should NOT be called during add_rss_feed
            mock_summary.assert_not_called()
            # But enrich_items was scheduled as a background task
            mock_enrich.assert_called_once()


class TestPreviewEndpoints:
    """Tests for preview API endpoints."""

    @patch("src.services.content_service.ArticleParser")
    def test_preview_article(self, mock_parser_class, client):
        """Test previewing an article."""
        mock_parser = Mock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = Mock(
            title="Test Article",
            text="This is a test article with enough content.",
            url="http://test.com/article",
            author="Test Author",
            description="Test description",
        )

        response = client.post(
            "/api/preview/article",
            json={"url": "http://test.com/article"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test Article"
        assert "content_length" in data

    @patch("src.services.content_service.RSSFeedParser")
    def test_preview_feed(self, mock_parser_class, client):
        """Test previewing an RSS feed."""
        mock_parser = Mock()
        mock_parser_class.return_value = mock_parser
        mock_parser.preview.return_value = Mock(
            title="Test Feed",
            url="http://test.com/feed",
            description="A test feed",
            items=[
                Mock(title="Item 1", url="http://test.com/1", published_at=None),
                Mock(title="Item 2", url="http://test.com/2", published_at=None),
            ],
        )

        response = client.post(
            "/api/preview/feed",
            json={"url": "http://test.com/feed"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test Feed"
        assert data["item_count"] == 2


class TestJobEndpoints:
    """Tests for job queue API endpoints."""

    def test_get_job_status(self, client):
        """Test getting job queue status."""
        response = client.get("/api/jobs")
        assert response.status_code == 200
        data = response.json()
        assert "pending" in data
        assert "processing" in data
        assert "completed" in data


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check(self, client):
        """Test health check returns ok."""
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestEnrichItems:
    """Tests for background enrichment."""

    @patch("src.services.content_service.ArticleParser")
    @patch("src.services.summary_service.generate_summary")
    def test_enrich_items_fetches_content_and_summary(
        self, mock_summary, mock_parser_class, client
    ):
        """Test that enrich_items fetches full content and generates summaries."""
        from src.services.content_service import ContentService
        from src.database import db_session, SourceRepository, ItemRepository, SourceType

        mock_parser = Mock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = Mock(
            text="Full article content that is longer than the feed snippet.",
        )
        mock_summary.return_value = "A nice summary."

        # Create a source and item with short content
        with db_session() as session:
            source = SourceRepository.create(
                session,
                type=SourceType.RSS_FEED,
                name="Test",
                url="http://test.com/feed",
            )
            item = ItemRepository.create(
                session,
                source_id=source.id,
                title="Test Item",
                url="http://test.com/article",
                content_text="Short",
            )
            item_id = item.id

        service = ContentService()
        service.article_parser = mock_parser
        service.enrich_items([item_id])

        # Verify full content was fetched
        mock_parser.parse.assert_called_once_with("http://test.com/article")

        # Verify summary was generated
        mock_summary.assert_called_once()

        # Verify item was updated in DB
        with db_session() as session:
            item = ItemRepository.get_by_id(session, item_id)
            assert item.content_text == "Full article content that is longer than the feed snippet."
            assert item.content_meta.get("summary") == "A nice summary."

    @patch("src.services.content_service.ArticleParser")
    @patch("src.services.summary_service.generate_summary")
    def test_enrich_items_skips_already_enriched(
        self, mock_summary, mock_parser_class, client
    ):
        """Test that enrich_items skips items that already have summaries."""
        from src.services.content_service import ContentService
        from src.database import db_session, SourceRepository, ItemRepository, SourceType

        with db_session() as session:
            source = SourceRepository.create(
                session,
                type=SourceType.RSS_FEED,
                name="Test2",
                url="http://test.com/feed2",
            )
            item = ItemRepository.create(
                session,
                source_id=source.id,
                title="Already Enriched",
                url="http://test.com/enriched",
                content_text="Full content here.",
                content_meta={"summary": "Existing summary"},
            )
            item_id = item.id

        service = ContentService()
        service.enrich_items([item_id])

        # Should not call parser or summary since item already has a summary
        mock_summary.assert_not_called()
