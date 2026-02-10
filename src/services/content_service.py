"""Content service for managing sources and items."""

import logging
from datetime import datetime
from typing import Optional, List

from src.config import get_settings
from src.database import (
    db_session,
    Source,
    Item,
    SourceRepository,
    ItemRepository,
    SourceType,
    ProcessingMode,
    ItemStatus,
)
from src.parsers import ArticleParser, RSSFeedParser, RoyalRoadParser
from .job_queue import get_job_queue

logger = logging.getLogger(__name__)


def source_to_dict(source: Source, base_url: str) -> dict:
    """Convert a Source ORM object to a dictionary."""
    return {
        "id": source.id,
        "type": source.type.value,
        "name": source.name,
        "slug": source.slug,
        "url": source.url,
        "item_count": source.item_count,
        "processing_mode": source.processing_mode.value,
        "settings": source.settings,
        "feed_url": f"{base_url}/feeds/{source.slug}.xml",
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "last_refreshed_at": source.last_refreshed_at.isoformat() if source.last_refreshed_at else None,
    }


def item_to_dict(item: Item, base_url: str) -> dict:
    """Convert an Item ORM object to a dictionary."""
    return {
        "id": item.id,
        "source_id": item.source_id,
        "title": item.title,
        "url": item.url,
        "status": item.status.value,
        "audio_url": f"{base_url}/audio/{item.id}.mp3" if item.audio_path else None,
        "audio_path": item.audio_path,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "processed_at": item.processed_at.isoformat() if item.processed_at else None,
        "error_message": item.error_message,
    }


class ContentService:
    """Service for managing content sources and items."""

    def __init__(self):
        self.settings = get_settings()
        self.article_parser = ArticleParser()
        self.rss_parser = RSSFeedParser()
        self.royal_road_parser = RoyalRoadParser()
        self.base_url = self.settings.base_url.rstrip("/")

    MANUAL_ARTICLES_SLUG = "manually-added-articles"
    MANUAL_ARTICLES_NAME = "Manually Added Articles"

    def _get_or_create_manual_articles_source(self, session) -> Source:
        """Get or create the unified source for manually added articles."""
        source = SourceRepository.get_by_slug(session, self.MANUAL_ARTICLES_SLUG)
        if source:
            return source

        # Create the unified source
        return SourceRepository.create(
            session,
            type=SourceType.ARTICLE,
            name=self.MANUAL_ARTICLES_NAME,
            url="manual://articles",
            item_count=0,
            processing_mode=ProcessingMode.EAGER,
        )

    def add_article(self, url: str, name: Optional[str] = None) -> dict:
        """
        Add a single article to the unified "Manually Added Articles" feed.

        Args:
            url: URL of the article
            name: Optional custom title for the article (ignored, uses parsed title)

        Returns:
            Created source as dict
        """
        logger.info(f"Adding article: {url}")

        # Parse the article
        article = self.article_parser.parse(url)

        # Generate summary for the article
        from src.services.summary_service import generate_summary
        summary = generate_summary(article.text)

        with db_session() as session:
            # Get or create the unified articles source
            source = self._get_or_create_manual_articles_source(session)

            # Check if article already exists
            if ItemRepository.exists_by_url(session, source.id, url):
                logger.info(f"Article already exists: {url}")
                return source_to_dict(source, self.base_url)

            # Create item with summary
            content_meta = {
                "author": article.author,
                "description": article.description,
                "image_url": article.image_url,
                "image_urls": article.image_urls or [],
            }
            if summary:
                content_meta["summary"] = summary

            item = ItemRepository.create(
                session,
                source_id=source.id,
                title=name or article.title,
                url=url,
                content_text=article.text,
                content_meta=content_meta,
                published_at=article.published_at or datetime.utcnow(),
            )

            # Update item count
            source.item_count = len(ItemRepository.get_by_source(session, source.id))

            item_id = item.id
            result = source_to_dict(source, self.base_url)

        # Queue for TTS processing (eager mode)
        job_queue = get_job_queue()
        job_queue.enqueue(item_id)

        return result

    def add_rss_feed(
        self,
        feed_url: str,
        name: Optional[str] = None,
        fetch_content: bool = True,
    ) -> dict:
        """
        Add an RSS feed as a source.

        Args:
            feed_url: URL of the RSS feed
            name: Optional name for the source
            fetch_content: Whether to fetch full content for items

        Returns:
            Created source as dict
        """
        logger.info(f"Adding RSS feed: {feed_url}")

        # Parse the feed
        feed = self.rss_parser.parse(feed_url, fetch_content=fetch_content)

        # Determine processing mode based on item count
        item_count = len(feed.items)
        processing_mode = (
            ProcessingMode.LAZY
            if item_count >= self.settings.lazy_threshold
            else ProcessingMode.EAGER
        )

        # Generate summaries for all items
        from src.services.summary_service import generate_summary
        item_summaries = {}
        for feed_item in feed.items:
            if feed_item.content:
                summary = generate_summary(feed_item.content)
                if summary:
                    item_summaries[feed_item.url] = summary

        with db_session() as session:
            # Create source
            source = SourceRepository.create(
                session,
                type=SourceType.RSS_FEED,
                name=name or feed.title,
                url=feed_url,
                item_count=item_count,
                processing_mode=processing_mode,
                settings={"image_url": feed.image_url, "description": feed.description},
            )

            # Create items
            item_ids = []
            for feed_item in feed.items:
                content_meta = {
                    "author": feed_item.author,
                    "description": feed_item.description,
                }
                if feed_item.url in item_summaries:
                    content_meta["summary"] = item_summaries[feed_item.url]

                item = ItemRepository.create(
                    session,
                    source_id=source.id,
                    title=feed_item.title,
                    url=feed_item.url,
                    content_text=feed_item.content,
                    content_meta=content_meta,
                    published_at=feed_item.published_at,
                )
                item_ids.append(item.id)

            result = source_to_dict(source, self.base_url)

        # Queue for TTS processing if eager mode
        if processing_mode == ProcessingMode.EAGER:
            job_queue = get_job_queue()
            for item_id in item_ids:
                job_queue.enqueue(item_id)

        logger.info(
            f"Added RSS feed '{feed.title}' with {item_count} items "
            f"(mode: {processing_mode.value})"
        )

        return result

    def add_royal_road_book(
        self,
        book_url: str,
        name: Optional[str] = None,
        max_chapters: Optional[int] = None,
    ) -> dict:
        """
        Add a Royal Road book as a source.

        Args:
            book_url: URL of the Royal Road book
            name: Optional name for the source
            max_chapters: Optional limit on number of chapters to add

        Returns:
            Created source as dict
        """
        logger.info(f"Adding Royal Road book: {book_url}")

        # Parse the book (don't fetch chapter content yet)
        book = self.royal_road_parser.parse(book_url, fetch_chapters=False)

        chapters = book.chapters
        if max_chapters:
            chapters = chapters[:max_chapters]

        # Royal Road books are always lazy (usually many chapters)
        item_count = len(chapters)
        processing_mode = (
            ProcessingMode.LAZY
            if item_count >= self.settings.lazy_threshold
            else ProcessingMode.EAGER
        )

        with db_session() as session:
            # Create source
            source = SourceRepository.create(
                session,
                type=SourceType.ROYAL_ROAD,
                name=name or book.title,
                url=book_url,
                item_count=item_count,
                processing_mode=processing_mode,
                settings={
                    "author": book.author,
                    "description": book.description,
                    "cover_image": book.cover_image,
                },
            )

            # Create items for each chapter (without content)
            item_ids = []
            for chapter in chapters:
                item = ItemRepository.create(
                    session,
                    source_id=source.id,
                    title=chapter.title,
                    url=chapter.url,
                    content_text="",  # Content fetched on demand
                    content_meta={"chapter_number": chapter.chapter_number},
                    published_at=chapter.published_at,
                )
                item_ids.append(item.id)

            result = source_to_dict(source, self.base_url)

        logger.info(
            f"Added Royal Road book '{book.title}' with {item_count} chapters "
            f"(mode: {processing_mode.value})"
        )

        return result

    def fetch_chapter_content(self, item_id: int) -> bool:
        """
        Fetch content for a Royal Road chapter.

        Args:
            item_id: ID of the item

        Returns:
            True if content was fetched successfully
        """
        with db_session() as session:
            item = ItemRepository.get_by_id(session, item_id)
            if not item:
                return False

            if item.content_text:
                # Already has content
                return True

            item_url = item.url
            item_title = item.title
            chapter_number = item.content_meta.get("chapter_number", 0) if item.content_json else 0

        # Fetch chapter content
        from src.parsers.royal_road import Chapter

        chapter = Chapter(
            title=item_title,
            url=item_url,
            chapter_number=chapter_number,
        )

        self.royal_road_parser.fetch_chapter(chapter)

        # Update item with content
        with db_session() as session:
            item = ItemRepository.get_by_id(session, item_id)
            if item:
                item.content_text = chapter.content

        return True

    def get_source(self, source_id: int) -> Optional[dict]:
        """Get a source by ID."""
        with db_session() as session:
            source = SourceRepository.get_by_id(session, source_id)
            if source:
                return source_to_dict(source, self.base_url)
        return None

    def get_all_sources(self) -> List[dict]:
        """Get all sources."""
        with db_session() as session:
            sources = SourceRepository.get_all(session)
            return [source_to_dict(s, self.base_url) for s in sources]

    def get_items_for_source(
        self,
        source_id: int,
        status: Optional[ItemStatus] = None,
    ) -> List[dict]:
        """Get items for a source."""
        with db_session() as session:
            items = ItemRepository.get_by_source(session, source_id, status)
            return [item_to_dict(i, self.base_url) for i in items]

    def delete_source(self, source_id: int) -> bool:
        """Delete a source and its items."""
        with db_session() as session:
            return SourceRepository.delete(session, source_id)

    def refresh_source(self, source_id: int) -> dict:
        """
        Refresh a source by checking for new items.

        For RSS feeds: Re-parse the feed and add any new items.
        For Royal Road: Re-parse chapter list and add new chapters.
        For articles: No-op (single item).

        Args:
            source_id: ID of the source to refresh

        Returns:
            Dict with refresh results
        """
        from datetime import datetime

        with db_session() as session:
            source = SourceRepository.get_by_id(session, source_id)
            if not source:
                raise ValueError(f"Source {source_id} not found")

            source_type = source.type
            source_url = source.url
            source_name = source.name
            processing_mode = source.processing_mode

        new_items = 0
        
        if source_type == SourceType.RSS_FEED:
            # Re-parse RSS feed
            feed = self.rss_parser.parse(source_url, fetch_content=True)

            # Find new items and generate summaries for them
            from src.services.summary_service import generate_summary
            new_feed_items = []
            with db_session() as session:
                for feed_item in feed.items:
                    if not ItemRepository.exists_by_url(session, source_id, feed_item.url):
                        new_feed_items.append(feed_item)

            # Generate summaries for new items (outside db session to avoid long transactions)
            item_summaries = {}
            for feed_item in new_feed_items:
                if feed_item.content:
                    summary = generate_summary(feed_item.content)
                    if summary:
                        item_summaries[feed_item.url] = summary

            # Create the new items
            with db_session() as session:
                for feed_item in new_feed_items:
                    # Double-check it still doesn't exist
                    if not ItemRepository.exists_by_url(session, source_id, feed_item.url):
                        content_meta = {
                            "author": feed_item.author,
                            "description": feed_item.description,
                        }
                        if feed_item.url in item_summaries:
                            content_meta["summary"] = item_summaries[feed_item.url]

                        item = ItemRepository.create(
                            session,
                            source_id=source_id,
                            title=feed_item.title,
                            url=feed_item.url,
                            content_text=feed_item.content,
                            content_meta=content_meta,
                            published_at=feed_item.published_at,
                        )
                        new_items += 1

                        # Queue for TTS if eager mode
                        if processing_mode == ProcessingMode.EAGER:
                            job_queue = get_job_queue()
                            job_queue.enqueue(item.id)

                # Update source
                source = SourceRepository.get_by_id(session, source_id)
                if source:
                    source.item_count = len(ItemRepository.get_by_source(session, source_id))
                    source.last_refreshed_at = datetime.utcnow()

        elif source_type == SourceType.ROYAL_ROAD:
            # Re-parse Royal Road chapter list
            book = self.royal_road_parser.parse(source_url, fetch_chapters=False)
            
            with db_session() as session:
                for chapter in book.chapters:
                    if not ItemRepository.exists_by_url(session, source_id, chapter.url):
                        ItemRepository.create(
                            session,
                            source_id=source_id,
                            title=chapter.title,
                            url=chapter.url,
                            content_text="",  # Fetched on demand
                            content_meta={"chapter_number": chapter.chapter_number},
                            published_at=chapter.published_at,
                        )
                        new_items += 1

                # Update source
                source = SourceRepository.get_by_id(session, source_id)
                if source:
                    source.item_count = len(ItemRepository.get_by_source(session, source_id))
                    source.last_refreshed_at = datetime.utcnow()

        else:
            # Articles can't be refreshed
            with db_session() as session:
                source = SourceRepository.get_by_id(session, source_id)
                if source:
                    source.last_refreshed_at = datetime.utcnow()

        logger.info(f"Refreshed source '{source_name}': {new_items} new items")

        return {
            "source_id": source_id,
            "new_items": new_items,
            "message": f"Found {new_items} new items" if new_items else "No new items found",
        }

    def reparse_source(
        self,
        source_id: int,
        update_images: bool = True,
        generate_summaries: bool = False,
    ) -> dict:
        """
        Re-parse all items in a source to update metadata.

        Args:
            source_id: ID of the source to reparse
            update_images: Re-fetch pages to extract image URLs
            generate_summaries: Generate AI summaries (costs API credits)

        Returns:
            Dict with reparse results
        """
        from src.services.summary_service import generate_summary

        with db_session() as session:
            source = SourceRepository.get_by_id(session, source_id)
            if not source:
                raise ValueError(f"Source {source_id} not found")

            source_type = source.type
            items = ItemRepository.get_by_source(session, source_id)
            item_data = [(i.id, i.url, i.content_text, i.content_meta) for i in items]

        updated = 0
        failed = 0
        summaries_generated = 0

        for item_id, item_url, content_text, existing_meta in item_data:
            try:
                meta = existing_meta or {}
                needs_update = False

                # Update images if requested
                if update_images and (source_type == SourceType.ARTICLE or source_type == SourceType.RSS_FEED):
                    article = self.article_parser.parse(item_url)
                    meta["image_urls"] = article.image_urls or []
                    if article.image_url:
                        meta["image_url"] = article.image_url
                    if article.description:
                        meta["description"] = article.description
                    if article.author:
                        meta["author"] = article.author
                    needs_update = True

                # Generate summary if requested and not already present
                if generate_summaries and content_text:
                    if not meta.get("summary"):
                        summary = generate_summary(content_text)
                        if summary:
                            meta["summary"] = summary
                            summaries_generated += 1
                            needs_update = True

                if needs_update:
                    with db_session() as session:
                        item = ItemRepository.get_by_id(session, item_id)
                        if item:
                            item.content_meta = meta
                            session.commit()
                            updated += 1

            except Exception as e:
                logger.error(f"Failed to reparse item {item_id}: {e}")
                failed += 1

        return {
            "source_id": source_id,
            "updated": updated,
            "failed": failed,
            "summaries_generated": summaries_generated,
            "message": f"Updated {updated} items" + (f", {failed} failed" if failed else ""),
        }

    def generate_summaries_for_source(self, source_id: int, overwrite: bool = False) -> dict:
        """
        Generate AI summaries for all items in a source.

        Args:
            source_id: ID of the source
            overwrite: If True, regenerate even if summary exists

        Returns:
            Dict with results
        """
        from src.services.summary_service import generate_summary

        with db_session() as session:
            source = SourceRepository.get_by_id(session, source_id)
            if not source:
                raise ValueError(f"Source {source_id} not found")

            items = ItemRepository.get_by_source(session, source_id)
            item_data = [(i.id, i.content_text, i.content_meta) for i in items]

        generated = 0
        skipped = 0
        failed = 0

        for item_id, content_text, existing_meta in item_data:
            meta = existing_meta or {}

            # Skip if already has summary and not overwriting
            if meta.get("summary") and not overwrite:
                skipped += 1
                continue

            if not content_text:
                skipped += 1
                continue

            try:
                summary = generate_summary(content_text)
                if summary:
                    meta["summary"] = summary
                    with db_session() as session:
                        item = ItemRepository.get_by_id(session, item_id)
                        if item:
                            item.content_meta = meta
                            session.commit()
                            generated += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Failed to generate summary for item {item_id}: {e}")
                failed += 1

        return {
            "source_id": source_id,
            "generated": generated,
            "skipped": skipped,
            "failed": failed,
            "message": f"Generated {generated} summaries, skipped {skipped}" + (f", {failed} failed" if failed else ""),
        }

    def preview_article(self, url: str) -> dict:
        """Preview an article without creating a source."""
        article = self.article_parser.parse(url)
        return {
            "title": article.title,
            "url": article.url,
            "author": article.author,
            "description": article.description,
            "content_preview": article.text[:500] + "..." if len(article.text) > 500 else article.text,
            "content_length": len(article.text),
        }

    def preview_rss_feed(self, feed_url: str) -> dict:
        """Preview an RSS feed without creating a source."""
        feed = self.rss_parser.preview(feed_url)
        return {
            "title": feed.title,
            "url": feed.url,
            "description": feed.description,
            "item_count": len(feed.items),
            "items": [
                {
                    "title": item.title,
                    "url": item.url,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                }
                for item in feed.items[:20]  # Limit preview
            ],
            "processing_mode": "lazy" if len(feed.items) >= self.settings.lazy_threshold else "eager",
        }

    def preview_royal_road(self, book_url: str) -> dict:
        """Preview a Royal Road book without creating a source."""
        book = self.royal_road_parser.preview(book_url)
        return {
            "title": book.title,
            "url": book.url,
            "author": book.author,
            "description": book.description,
            "cover_image": book.cover_image,
            "chapter_count": len(book.chapters),
            "chapters": [
                {
                    "title": ch.title,
                    "url": ch.url,
                    "chapter_number": ch.chapter_number,
                    "published_at": ch.published_at.isoformat() if ch.published_at else None,
                }
                for ch in book.chapters[:20]  # Limit preview
            ],
            "processing_mode": "lazy" if len(book.chapters) >= self.settings.lazy_threshold else "eager",
        }
