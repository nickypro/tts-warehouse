"""Tests for API routes."""

import os
import pytest
from unittest.mock import Mock, patch

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
        """Test adding an article."""
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
        )

        response = client.post(
            "/api/sources/article",
            json={"url": "http://test.com/article"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Article"
        assert data["type"] == "article"
        assert "feed_url" in data

    def test_add_article_invalid_url(self, client):
        """Test adding article with connection error."""
        response = client.post(
            "/api/sources/article",
            json={"url": "http://nonexistent.invalid/article"},
        )
        assert response.status_code == 400


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
