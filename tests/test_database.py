"""Tests for database models and repository."""

import json
import os
import tempfile
import pytest
from datetime import datetime

# Set test database before imports
os.environ["DATABASE_PATH"] = ":memory:"

from src.database import (
    init_db,
    db_session,
    Source,
    Item,
    SourceRepository,
    ItemRepository,
    SourceType,
    ProcessingMode,
    ItemStatus,
)
from src.database.repository import _engine, _SessionLocal, Base
import src.database.repository as repo_module


@pytest.fixture(autouse=True)
def setup_db():
    """Initialize fresh database for each test."""
    # Reset global state
    repo_module._engine = None
    repo_module._SessionLocal = None
    init_db()
    yield
    # Clean up after test
    if repo_module._engine:
        Base.metadata.drop_all(bind=repo_module._engine)
        repo_module._engine.dispose()
        repo_module._engine = None
        repo_module._SessionLocal = None


class TestSourceModel:
    """Tests for Source model."""

    def test_settings_property_empty(self):
        """Test settings property with empty JSON."""
        source = Source(
            type=SourceType.ARTICLE,
            name="Test",
            slug="test",
            url="http://test.com",
            settings_json="{}",
        )
        assert source.settings == {}

    def test_settings_property_with_data(self):
        """Test settings property with data."""
        source = Source(
            type=SourceType.ARTICLE,
            name="Test",
            slug="test",
            url="http://test.com",
            settings_json='{"key": "value"}',
        )
        assert source.settings == {"key": "value"}

    def test_settings_property_invalid_json(self):
        """Test settings property with invalid JSON returns empty dict."""
        source = Source(
            type=SourceType.ARTICLE,
            name="Test",
            slug="test",
            url="http://test.com",
            settings_json="not valid json",
        )
        assert source.settings == {}

    def test_settings_property_empty_string(self):
        """Test settings property with empty string returns empty dict."""
        source = Source(
            type=SourceType.ARTICLE,
            name="Test",
            slug="test",
            url="http://test.com",
            settings_json="",
        )
        assert source.settings == {}


class TestSourceRepository:
    """Tests for SourceRepository."""

    def test_create_source(self):
        """Test creating a source."""
        with db_session() as session:
            source = SourceRepository.create(
                session,
                type=SourceType.ARTICLE,
                name="Test Article",
                url="http://test.com/article",
            )
            assert source.id is not None
            assert source.name == "Test Article"
            assert source.slug == "test-article"
            assert source.type == SourceType.ARTICLE

    def test_create_source_with_settings(self):
        """Test creating a source with settings."""
        with db_session() as session:
            source = SourceRepository.create(
                session,
                type=SourceType.RSS_FEED,
                name="Test Feed",
                url="http://test.com/feed",
                settings={"author": "Test Author", "description": "Test desc"},
            )
            assert source.settings["author"] == "Test Author"

    def test_create_source_auto_lazy_mode(self):
        """Test that sources with 10+ items get lazy mode."""
        with db_session() as session:
            source = SourceRepository.create(
                session,
                type=SourceType.RSS_FEED,
                name="Large Feed",
                url="http://test.com/feed",
                item_count=15,
            )
            assert source.processing_mode == ProcessingMode.LAZY

    def test_create_source_auto_eager_mode(self):
        """Test that sources with <10 items get eager mode."""
        with db_session() as session:
            source = SourceRepository.create(
                session,
                type=SourceType.RSS_FEED,
                name="Small Feed",
                url="http://test.com/feed",
                item_count=5,
            )
            assert source.processing_mode == ProcessingMode.EAGER

    def test_get_by_id(self):
        """Test getting source by ID."""
        with db_session() as session:
            source = SourceRepository.create(
                session,
                type=SourceType.ARTICLE,
                name="Test",
                url="http://test.com",
            )
            source_id = source.id

        with db_session() as session:
            found = SourceRepository.get_by_id(session, source_id)
            assert found is not None
            assert found.name == "Test"

    def test_get_by_slug(self):
        """Test getting source by slug."""
        with db_session() as session:
            SourceRepository.create(
                session,
                type=SourceType.ARTICLE,
                name="My Test Article",
                url="http://test.com",
            )

        with db_session() as session:
            found = SourceRepository.get_by_slug(session, "my-test-article")
            assert found is not None
            assert found.name == "My Test Article"

    def test_unique_slug_generation(self):
        """Test that duplicate names get unique slugs."""
        with db_session() as session:
            source1 = SourceRepository.create(
                session,
                type=SourceType.ARTICLE,
                name="Test",
                url="http://test1.com",
            )
            source2 = SourceRepository.create(
                session,
                type=SourceType.ARTICLE,
                name="Test",
                url="http://test2.com",
            )
            assert source1.slug == "test"
            assert source2.slug == "test-1"

    def test_delete_source(self):
        """Test deleting a source."""
        with db_session() as session:
            source = SourceRepository.create(
                session,
                type=SourceType.ARTICLE,
                name="To Delete",
                url="http://test.com",
            )
            source_id = source.id

        with db_session() as session:
            result = SourceRepository.delete(session, source_id)
            assert result is True

        with db_session() as session:
            found = SourceRepository.get_by_id(session, source_id)
            assert found is None


class TestItemRepository:
    """Tests for ItemRepository."""

    def test_create_item(self):
        """Test creating an item."""
        with db_session() as session:
            source = SourceRepository.create(
                session,
                type=SourceType.ARTICLE,
                name="Test",
                url="http://test.com",
            )
            item = ItemRepository.create(
                session,
                source_id=source.id,
                title="Test Item",
                url="http://test.com/item",
                content_text="This is the content.",
            )
            assert item.id is not None
            assert item.title == "Test Item"
            assert item.status == ItemStatus.PENDING

    def test_update_status(self):
        """Test updating item status."""
        with db_session() as session:
            source = SourceRepository.create(
                session,
                type=SourceType.ARTICLE,
                name="Test",
                url="http://test.com",
            )
            item = ItemRepository.create(
                session,
                source_id=source.id,
                title="Test Item",
                url="http://test.com/item",
            )
            item_id = item.id

        with db_session() as session:
            ItemRepository.update_status(
                session,
                item_id,
                ItemStatus.READY,
                audio_path="/path/to/audio.mp3",
            )

        with db_session() as session:
            item = ItemRepository.get_by_id(session, item_id)
            assert item.status == ItemStatus.READY
            assert item.audio_path == "/path/to/audio.mp3"
            assert item.processed_at is not None

    def test_get_pending_items(self):
        """Test getting pending items."""
        with db_session() as session:
            source = SourceRepository.create(
                session,
                type=SourceType.ARTICLE,
                name="Test",
                url="http://test.com",
            )
            for i in range(5):
                ItemRepository.create(
                    session,
                    source_id=source.id,
                    title=f"Item {i}",
                    url=f"http://test.com/item{i}",
                )

        with db_session() as session:
            pending = ItemRepository.get_pending(session, limit=3)
            assert len(pending) == 3

    def test_exists_by_url(self):
        """Test checking if item exists by URL."""
        with db_session() as session:
            source = SourceRepository.create(
                session,
                type=SourceType.ARTICLE,
                name="Test",
                url="http://test.com",
            )
            ItemRepository.create(
                session,
                source_id=source.id,
                title="Test Item",
                url="http://test.com/unique-item",
            )
            source_id = source.id

        with db_session() as session:
            assert ItemRepository.exists_by_url(session, source_id, "http://test.com/unique-item")
            assert not ItemRepository.exists_by_url(session, source_id, "http://test.com/other")
