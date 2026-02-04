"""Database repository for CRUD operations."""

import json
import logging
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional, List

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from src.config import get_settings
from .models import Base, Source, Item, OutputFeed, SourceType, ProcessingMode, ItemStatus

logger = logging.getLogger(__name__)

# Global engine and session factory
_engine = None
_SessionLocal = None


def get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        database_path = Path(settings.database_path)
        database_path.parent.mkdir(parents=True, exist_ok=True)

        database_url = f"sqlite:///{database_path}"

        _engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            echo=False,
        )

        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        logger.info(f"Database engine created: {database_url}")

    return _engine


def get_session() -> Session:
    """Get a database session."""
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    return _SessionLocal()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Context manager for database sessions with automatic commit/rollback."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db():
    """Initialize the database (create tables)."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text[:200]


class SourceRepository:
    """Repository for Source CRUD operations."""

    @staticmethod
    def create(
        session: Session,
        type: SourceType,
        name: str,
        url: str,
        slug: Optional[str] = None,
        settings: Optional[dict] = None,
        item_count: int = 0,
        processing_mode: Optional[ProcessingMode] = None,
    ) -> Source:
        """Create a new source."""
        app_settings = get_settings()
        
        if slug is None:
            slug = slugify(name)
        
        # Ensure unique slug
        base_slug = slug
        counter = 1
        while session.query(Source).filter(Source.slug == slug).first():
            slug = f"{base_slug}-{counter}"
            counter += 1

        # Auto-determine processing mode if not specified
        if processing_mode is None:
            threshold = app_settings.lazy_threshold
            processing_mode = ProcessingMode.LAZY if item_count >= threshold else ProcessingMode.EAGER

        source = Source(
            type=type,
            name=name,
            url=url,
            slug=slug,
            item_count=item_count,
            processing_mode=processing_mode,
            settings_json=json.dumps(settings) if settings else "{}",
        )
        session.add(source)
        session.flush()
        return source

    @staticmethod
    def get_by_id(session: Session, source_id: int) -> Optional[Source]:
        """Get source by ID."""
        return session.query(Source).filter(Source.id == source_id).first()

    @staticmethod
    def get_by_slug(session: Session, slug: str) -> Optional[Source]:
        """Get source by slug."""
        return session.query(Source).filter(Source.slug == slug).first()

    @staticmethod
    def get_all(session: Session) -> List[Source]:
        """Get all sources."""
        return session.query(Source).order_by(Source.created_at.desc()).all()

    @staticmethod
    def update_item_count(session: Session, source_id: int, count: int):
        """Update source item count and potentially processing mode."""
        source = session.query(Source).filter(Source.id == source_id).first()
        if source:
            source.item_count = count
            threshold = get_settings().lazy_threshold
            if count >= threshold:
                source.processing_mode = ProcessingMode.LAZY
            session.flush()

    @staticmethod
    def delete(session: Session, source_id: int) -> bool:
        """Delete a source and its items."""
        source = session.query(Source).filter(Source.id == source_id).first()
        if source:
            session.delete(source)
            return True
        return False


class ItemRepository:
    """Repository for Item CRUD operations."""

    @staticmethod
    def create(
        session: Session,
        source_id: int,
        title: str,
        url: str,
        content_text: Optional[str] = None,
        content_meta: Optional[dict] = None,
        published_at: Optional[datetime] = None,
    ) -> Item:
        """Create a new item."""
        item = Item(
            source_id=source_id,
            title=title,
            url=url,
            content_text=content_text,
            content_json=json.dumps(content_meta) if content_meta else "{}",
            published_at=published_at,
            status=ItemStatus.PENDING,
        )
        session.add(item)
        session.flush()
        return item

    @staticmethod
    def get_by_id(session: Session, item_id: int) -> Optional[Item]:
        """Get item by ID."""
        return session.query(Item).filter(Item.id == item_id).first()

    @staticmethod
    def get_by_source(
        session: Session,
        source_id: int,
        status: Optional[ItemStatus] = None,
    ) -> List[Item]:
        """Get items by source, optionally filtered by status."""
        query = session.query(Item).filter(Item.source_id == source_id)
        if status:
            query = query.filter(Item.status == status)
        return query.order_by(Item.published_at.desc()).all()

    @staticmethod
    def get_pending(session: Session, limit: int = 10) -> List[Item]:
        """Get pending items for processing."""
        return (
            session.query(Item)
            .filter(Item.status == ItemStatus.PENDING)
            .order_by(Item.created_at)
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_ready_items(session: Session, source_id: Optional[int] = None) -> List[Item]:
        """Get items that are ready (have audio)."""
        query = session.query(Item).filter(Item.status == ItemStatus.READY)
        if source_id:
            query = query.filter(Item.source_id == source_id)
        return query.order_by(Item.published_at.desc()).all()

    @staticmethod
    def update_status(
        session: Session,
        item_id: int,
        status: ItemStatus,
        audio_path: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        """Update item status."""
        item = session.query(Item).filter(Item.id == item_id).first()
        if item:
            item.status = status
            if audio_path:
                item.audio_path = audio_path
            if error_message:
                item.error_message = error_message
            if status == ItemStatus.READY:
                item.processed_at = datetime.utcnow()
            session.flush()

    @staticmethod
    def exists_by_url(session: Session, source_id: int, url: str) -> bool:
        """Check if an item with this URL already exists for the source."""
        return (
            session.query(Item)
            .filter(Item.source_id == source_id, Item.url == url)
            .first()
            is not None
        )


class OutputFeedRepository:
    """Repository for OutputFeed CRUD operations."""

    @staticmethod
    def create(
        session: Session,
        name: str,
        slug: Optional[str] = None,
        description: Optional[str] = None,
        source_filter: Optional[dict] = None,
    ) -> OutputFeed:
        """Create a new output feed."""
        if slug is None:
            slug = slugify(name)

        # Ensure unique slug
        base_slug = slug
        counter = 1
        while session.query(OutputFeed).filter(OutputFeed.slug == slug).first():
            slug = f"{base_slug}-{counter}"
            counter += 1

        feed = OutputFeed(
            name=name,
            slug=slug,
            description=description,
            source_filter_json=json.dumps(source_filter) if source_filter else "{}",
        )
        session.add(feed)
        session.flush()
        return feed

    @staticmethod
    def get_by_id(session: Session, feed_id: int) -> Optional[OutputFeed]:
        """Get feed by ID."""
        return session.query(OutputFeed).filter(OutputFeed.id == feed_id).first()

    @staticmethod
    def get_by_slug(session: Session, slug: str) -> Optional[OutputFeed]:
        """Get feed by slug."""
        return session.query(OutputFeed).filter(OutputFeed.slug == slug).first()

    @staticmethod
    def get_all(session: Session) -> List[OutputFeed]:
        """Get all output feeds."""
        return session.query(OutputFeed).order_by(OutputFeed.created_at.desc()).all()

    @staticmethod
    def delete(session: Session, feed_id: int) -> bool:
        """Delete an output feed."""
        feed = session.query(OutputFeed).filter(OutputFeed.id == feed_id).first()
        if feed:
            session.delete(feed)
            return True
        return False
