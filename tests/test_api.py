"""Tests for API routes."""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock

# Set test environment before imports
os.environ["DATABASE_PATH"] = ":memory:"
os.environ["ADMIN_PASSWORD"] = ""

# Clear cached settings so test env vars take effect
from src.config import get_settings
get_settings.cache_clear()

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


class TestAuthEndpoints:
    """Tests for auth-related endpoints."""

    def test_auth_status_no_password(self, client):
        """Test auth status when no admin password is set."""
        response = client.get("/api/auth/status")
        assert response.status_code == 200
        data = response.json()
        assert "authenticated" in data
        assert "auth_required" in data

    @patch("src.web.routes.get_settings")
    def test_auth_status_with_password(self, mock_settings, client):
        """Test auth status when admin password is configured."""
        mock_settings.return_value = Mock(admin_password="secret", base_url="http://localhost:8775")
        response = client.get("/api/auth/status")
        assert response.status_code == 200
        data = response.json()
        assert data["auth_required"] is True


class TestPublicSourcesEndpoint:
    """Tests for the public sources endpoint."""

    def test_public_sources_accessible(self, client):
        """Test public sources endpoint is accessible without auth."""
        response = client.get("/api/public/sources")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @patch("src.services.content_service.ArticleParser")
    def test_public_sources_returns_url(self, mock_parser_class, client):
        """Test public sources includes the source URL for linking."""
        mock_parser = Mock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = Mock(
            title="Test Article",
            text="Content.",
            url="http://test.com/article",
            author=None,
            published_at=None,
            description=None,
            image_url=None,
            image_urls=[],
        )

        client.post("/api/sources/article", json={"url": "http://test.com/article"})

        response = client.get("/api/public/sources")
        assert response.status_code == 200
        sources = response.json()
        assert len(sources) >= 1
        # Public endpoint should include url, name, type, item_count, feed_url, in_feed
        source = sources[0]
        assert "url" in source
        assert "name" in source
        assert "feed_url" in source
        assert "in_feed" in source

    @patch("src.services.content_service.ArticleParser")
    def test_public_sources_limited_fields(self, mock_parser_class, client):
        """Test public sources does NOT expose sensitive fields like settings."""
        mock_parser = Mock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = Mock(
            title="Test Article",
            text="Content.",
            url="http://test.com/article2",
            author=None,
            published_at=None,
            description=None,
            image_url=None,
            image_urls=[],
        )

        client.post("/api/sources/article", json={"url": "http://test.com/article2"})

        response = client.get("/api/public/sources")
        sources = response.json()
        source = sources[0]
        assert "settings" not in source
        assert "processing_mode" not in source


class TestInFeedToggle:
    """Tests for the in-feed toggle endpoint."""

    @patch("src.services.content_service.RSSFeedParser")
    def test_toggle_in_feed(self, mock_parser_class, client):
        """Test toggling a source in/out of the unified feed."""
        mock_parser = Mock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = Mock(
            title="Toggle Feed",
            url="http://test.com/togglefeed",
            description="A feed",
            image_url=None,
            items=[],
        )

        add_resp = client.post("/api/sources/feed", json={"url": "http://test.com/togglefeed"})
        source_id = add_resp.json()["id"]

        # Toggle off
        resp = client.patch(f"/api/sources/{source_id}/in-feed")
        assert resp.status_code == 200
        assert resp.json()["in_feed"] is False

        # Toggle back on
        resp = client.patch(f"/api/sources/{source_id}/in-feed")
        assert resp.status_code == 200
        assert resp.json()["in_feed"] is True

    def test_toggle_in_feed_not_found(self, client):
        """Test toggling in-feed for nonexistent source."""
        resp = client.patch("/api/sources/99999/in-feed")
        assert resp.status_code == 404


class TestSetMode:
    """Tests for the processing mode endpoint."""

    @patch("src.services.content_service.RSSFeedParser")
    def test_set_mode(self, mock_parser_class, client):
        """Test setting processing mode for a source."""
        mock_parser = Mock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = Mock(
            title="Mode Feed",
            url="http://test.com/modefeed",
            description="A feed",
            image_url=None,
            items=[],
        )

        add_resp = client.post("/api/sources/feed", json={"url": "http://test.com/modefeed"})
        source_id = add_resp.json()["id"]

        resp = client.patch(f"/api/sources/{source_id}/mode", json={"mode": "lazy"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "lazy"

        resp = client.patch(f"/api/sources/{source_id}/mode", json={"mode": "new_only"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "new_only"

    @patch("src.services.content_service.RSSFeedParser")
    def test_set_invalid_mode(self, mock_parser_class, client):
        """Test setting an invalid processing mode."""
        mock_parser = Mock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = Mock(
            title="Mode Feed 2",
            url="http://test.com/modefeed2",
            description="A feed",
            image_url=None,
            items=[],
        )

        add_resp = client.post("/api/sources/feed", json={"url": "http://test.com/modefeed2"})
        source_id = add_resp.json()["id"]

        resp = client.patch(f"/api/sources/{source_id}/mode", json={"mode": "turbo"})
        assert resp.status_code == 400

    def test_set_mode_not_found(self, client):
        """Test setting mode for nonexistent source."""
        resp = client.patch("/api/sources/99999/mode", json={"mode": "lazy"})
        assert resp.status_code == 404


class TestItemsEndpoint:
    """Tests for item listing with URL field."""

    @patch("src.services.content_service.ArticleParser")
    def test_items_include_url(self, mock_parser_class, client):
        """Test that items include the original article URL."""
        mock_parser = Mock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = Mock(
            title="URL Test Article",
            text="Content for URL test.",
            url="http://test.com/url-test",
            author=None,
            published_at=None,
            description=None,
            image_url=None,
            image_urls=[],
        )

        add_resp = client.post("/api/sources/article", json={"url": "http://test.com/url-test"})
        source_id = add_resp.json()["id"]

        resp = client.get(f"/api/items?source_id={source_id}")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 1
        assert items[0]["url"] == "http://test.com/url-test"


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
