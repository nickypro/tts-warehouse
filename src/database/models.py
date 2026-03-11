"""SQLAlchemy database models."""

import json
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Enum as SQLEnum,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class SourceType(str, Enum):
    """Type of content source."""

    ARTICLE = "article"
    RSS_FEED = "rss_feed"
    ROYAL_ROAD = "royal_road"


class ProcessingMode(str, Enum):
    """Processing mode for TTS generation."""

    EAGER = "eager"  # Process immediately
    LAZY = "lazy"  # Process on demand
    NEW_ONLY = "new_only"  # Only process newly added items


class ItemStatus(str, Enum):
    """Status of an item's TTS processing."""

    PENDING = "pending"  # Awaiting TTS
    PROCESSING = "processing"  # TTS currently running
    READY = "ready"  # Audio available
    FAILED = "failed"  # TTS failed


class Source(Base):
    """A content source (article, RSS feed, or Royal Road book)."""

    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(SQLEnum(SourceType), nullable=False)
    name = Column(String(500), nullable=False)
    slug = Column(String(200), unique=True, nullable=False)
    url = Column(String(2000), nullable=False)
    item_count = Column(Integer, default=0)
    processing_mode = Column(SQLEnum(ProcessingMode), default=ProcessingMode.EAGER)
    in_feed = Column(Boolean, default=True)  # Include in unified podcast feed
    settings_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    last_refreshed_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    items = relationship("Item", back_populates="source", cascade="all, delete-orphan")

    @property
    def settings(self) -> dict:
        """Parse settings JSON."""
        if not self.settings_json or self.settings_json.strip() == "":
            return {}
        try:
            return json.loads(self.settings_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    @settings.setter
    def settings(self, value: dict):
        """Serialize settings to JSON."""
        self.settings_json = json.dumps(value) if value else "{}"

    def __repr__(self):
        return f"<Source(id={self.id}, type={self.type}, name='{self.name}')>"


class Item(Base):
    """An individual item (article or chapter) from a source."""

    __tablename__ = "items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    title = Column(String(500), nullable=False)
    url = Column(String(2000), nullable=False)
    content_text = Column(Text)  # Plain text for TTS
    content_json = Column(Text)  # Structured content/metadata
    audio_path = Column(String(500))  # Path to generated audio file
    status = Column(SQLEnum(ItemStatus), default=ItemStatus.PENDING)
    error_message = Column(Text)  # Error details if failed
    published_at = Column(DateTime)
    processed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    source = relationship("Source", back_populates="items")

    @property
    def content_meta(self) -> dict:
        """Parse content JSON."""
        if not self.content_json or self.content_json.strip() == "":
            return {}
        try:
            return json.loads(self.content_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    @content_meta.setter
    def content_meta(self, value: dict):
        """Serialize content metadata to JSON."""
        self.content_json = json.dumps(value) if value else "{}"

    def __repr__(self):
        return f"<Item(id={self.id}, title='{self.title[:50]}...', status={self.status})>"


class OutputFeed(Base):
    """A generated podcast RSS feed."""

    __tablename__ = "output_feeds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(500), nullable=False)
    slug = Column(String(200), unique=True, nullable=False)
    description = Column(Text)
    source_filter_json = Column(Text, default="{}")  # Filter criteria for items
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def source_filter(self) -> dict:
        """Parse source filter JSON."""
        if not self.source_filter_json or self.source_filter_json.strip() == "":
            return {}
        try:
            return json.loads(self.source_filter_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    @source_filter.setter
    def source_filter(self, value: dict):
        """Serialize source filter to JSON."""
        self.source_filter_json = json.dumps(value) if value else "{}"

    def __repr__(self):
        return f"<OutputFeed(id={self.id}, name='{self.name}', slug='{self.slug}')>"
