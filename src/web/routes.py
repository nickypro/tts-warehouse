"""FastAPI routes for the TTS Warehouse API."""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.config import get_settings
from src.database import (
    db_session,
    SourceRepository,
    ItemRepository,
    ItemStatus,
)
from src.services.content_service import ContentService
from src.services.job_queue import get_job_queue
from src.services.rss_generator import RSSGenerator
from src.services.icon_generator import generate_letter_icon, generate_radio_icon

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


# --- Request/Response Models ---


class AddArticleRequest(BaseModel):
    url: str
    name: Optional[str] = None


class AddFeedRequest(BaseModel):
    url: str
    name: Optional[str] = None


class AddRoyalRoadRequest(BaseModel):
    url: str
    name: Optional[str] = None
    max_chapters: Optional[int] = None


class PreviewRequest(BaseModel):
    url: str


# --- Helper Functions ---


def get_content_service() -> ContentService:
    return ContentService()


def get_rss_generator() -> RSSGenerator:
    return RSSGenerator()


# --- Source Endpoints ---


@router.get("/api/sources")
async def list_sources():
    """List all sources."""
    service = get_content_service()
    return service.get_all_sources()


@router.post("/api/sources/article")
async def add_article(request: AddArticleRequest):
    """Add a single article as a source."""
    try:
        service = get_content_service()
        source = service.add_article(request.url, request.name)

        return {
            **source,
            "message": "Article added and queued for TTS processing",
        }
    except Exception as e:
        logger.error(f"Failed to add article: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/sources/feed")
async def add_feed(request: AddFeedRequest):
    """Add an RSS feed as a source."""
    try:
        service = get_content_service()
        source = service.add_rss_feed(request.url, request.name)

        return {
            **source,
            "message": f"Feed added with {source['item_count']} items",
        }
    except Exception as e:
        logger.error(f"Failed to add feed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/sources/royalroad")
async def add_royal_road(request: AddRoyalRoadRequest):
    """Add a Royal Road book as a source."""
    try:
        service = get_content_service()
        source = service.add_royal_road_book(
            request.url, request.name, request.max_chapters
        )

        return {
            **source,
            "message": f"Book added with {source['item_count']} chapters",
        }
    except Exception as e:
        logger.error(f"Failed to add Royal Road book: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/sources/{source_id}")
async def get_source(source_id: int):
    """Get a source by ID."""
    service = get_content_service()
    source = service.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.delete("/api/sources/{source_id}")
async def delete_source(source_id: int):
    """Delete a source and its items."""
    service = get_content_service()
    if service.delete_source(source_id):
        return {"message": "Source deleted"}
    raise HTTPException(status_code=404, detail="Source not found")


@router.post("/api/sources/{source_id}/refresh")
async def refresh_source(source_id: int):
    """
    Refresh a source to check for new items.

    For RSS feeds and Royal Road books, this re-parses the source
    and adds any new items that weren't previously imported.
    """
    try:
        service = get_content_service()
        result = service.refresh_source(source_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to refresh source {source_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/sources/{source_id}/reparse")
async def reparse_source(
    source_id: int,
    images: bool = Query(True, description="Re-fetch pages to extract image URLs"),
    summaries: bool = Query(False, description="Generate AI summaries (costs API credits)"),
):
    """
    Re-parse all items in a source to update metadata.

    This re-fetches each item's URL and extracts updated metadata
    (like image URLs). Does not regenerate TTS audio.

    Query params:
    - images: Update image URLs (default: true)
    - summaries: Generate AI summaries (default: false, costs API credits)
    """
    try:
        service = get_content_service()
        result = service.reparse_source(
            source_id,
            update_images=images,
            generate_summaries=summaries,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to reparse source {source_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/sources/{source_id}/generate-summaries")
async def generate_summaries(
    source_id: int,
    overwrite: bool = Query(False, description="Overwrite existing summaries"),
):
    """
    Generate AI summaries for all items in a source.

    This only generates summaries, doesn't re-fetch content.
    Summaries are cached in the database.

    Query params:
    - overwrite: Regenerate even if summary exists (default: false)
    """
    try:
        service = get_content_service()
        result = service.generate_summaries_for_source(source_id, overwrite=overwrite)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to generate summaries for source {source_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Preview Endpoints ---


@router.post("/api/preview/article")
async def preview_article(request: PreviewRequest):
    """Preview an article before adding."""
    try:
        service = get_content_service()
        return service.preview_article(request.url)
    except Exception as e:
        logger.error(f"Failed to preview article: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/preview/feed")
async def preview_feed(request: PreviewRequest):
    """Preview an RSS feed before adding."""
    try:
        service = get_content_service()
        return service.preview_rss_feed(request.url)
    except Exception as e:
        logger.error(f"Failed to preview feed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/preview/royalroad")
async def preview_royal_road(request: PreviewRequest):
    """Preview a Royal Road book before adding."""
    try:
        service = get_content_service()
        return service.preview_royal_road(request.url)
    except Exception as e:
        logger.error(f"Failed to preview Royal Road book: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# --- Item Endpoints ---


@router.get("/api/items")
async def list_items(
    source_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
):
    """List items, optionally filtered by source and/or status."""
    settings = get_settings()
    base_url = settings.base_url.rstrip("/")

    with db_session() as session:
        if source_id:
            item_status = ItemStatus(status) if status else None
            items = ItemRepository.get_by_source(session, source_id, item_status)
        else:
            items = ItemRepository.get_ready_items(session)

        return [
            {
                "id": item.id,
                "source_id": item.source_id,
                "title": item.title,
                "url": item.url,
                "status": item.status.value,
                "audio_url": f"{base_url}/audio/{item.id}.mp3" if item.audio_path else None,
                "published_at": item.published_at.isoformat() if item.published_at else None,
            }
            for item in items
        ]


@router.get("/api/items/{item_id}")
async def get_item(item_id: int):
    """Get an item by ID."""
    settings = get_settings()
    base_url = settings.base_url.rstrip("/")

    with db_session() as session:
        item = ItemRepository.get_by_id(session, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        return {
            "id": item.id,
            "source_id": item.source_id,
            "title": item.title,
            "url": item.url,
            "status": item.status.value,
            "audio_url": f"{base_url}/audio/{item.id}.mp3" if item.audio_path else None,
            "audio_path": item.audio_path,
            "content_preview": (
                item.content_text[:500] + "..."
                if item.content_text and len(item.content_text) > 500
                else item.content_text
            ),
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "processed_at": item.processed_at.isoformat() if item.processed_at else None,
            "error_message": item.error_message,
        }


@router.post("/api/items/{item_id}/process")
async def process_item(item_id: int):
    """Trigger TTS processing for an item (for lazy items)."""
    with db_session() as session:
        item = ItemRepository.get_by_id(session, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        if item.status == ItemStatus.READY:
            return {"message": "Item already processed", "status": "ready"}

        if item.status == ItemStatus.PROCESSING:
            return {"message": "Item is currently processing", "status": "processing"}

    # Queue for processing
    job_queue = get_job_queue()
    job_queue.enqueue(item_id)

    return {"message": "Item queued for processing", "status": "pending"}


# --- Audio Endpoint (with lazy TTS trigger) ---


@router.get("/audio/{item_id}.mp3")
async def get_audio(item_id: int):
    """
    Serve audio for an item.
    
    For lazy items, this triggers TTS generation if not already processed.
    """
    with db_session() as session:
        item = ItemRepository.get_by_id(session, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        item_status = item.status
        item_audio_path = item.audio_path
        item_error = item.error_message
        item_title = item.title
        source_type = item.source.type.value if item.source else None

    # If ready, serve the file
    if item_status == ItemStatus.READY and item_audio_path:
        audio_path = Path(item_audio_path)
        if audio_path.exists():
            return FileResponse(
                audio_path,
                media_type="audio/mpeg",
                filename=f"{item_title}.mp3",
            )

    # If failed, return error
    if item_status == ItemStatus.FAILED:
        raise HTTPException(
            status_code=500,
            detail=f"TTS processing failed: {item_error}",
        )

    # If processing, return retry-after
    if item_status == ItemStatus.PROCESSING:
        return Response(
            content="Audio is being generated, please retry later",
            status_code=202,
            headers={"Retry-After": "30"},
        )

    # Lazy processing: trigger TTS now
    logger.info(f"Lazy TTS trigger for item {item_id}")

    # For Royal Road chapters, fetch content first if needed
    with db_session() as session:
        item = ItemRepository.get_by_id(session, item_id)
        if item and not item.content_text and source_type == "royal_road":
            service = get_content_service()
            service.fetch_chapter_content(item_id)

    # Process synchronously for lazy mode
    job_queue = get_job_queue()
    success = job_queue.process_one(item_id)

    if success:
        # Refetch item to get audio path
        with db_session() as session:
            item = ItemRepository.get_by_id(session, item_id)
            if item and item.audio_path:
                audio_path = Path(item.audio_path)
                if audio_path.exists():
                    return FileResponse(
                        audio_path,
                        media_type="audio/mpeg",
                        filename=f"{item.title}.mp3",
                    )

    raise HTTPException(status_code=500, detail="Failed to generate audio")


# --- Feed Endpoints ---


@router.get("/api/feeds")
async def list_feeds():
    """List all available RSS feeds."""
    service = get_content_service()
    sources = service.get_all_sources()

    return [
        {
            "source_id": s["id"],
            "name": s["name"],
            "slug": s["slug"],
            "feed_url": s["feed_url"],
            "item_count": s["item_count"],
        }
        for s in sources
    ]


@router.get("/icons/all.png")
async def get_unified_feed_icon():
    """Generate and serve the unified feed radio icon."""
    icon_bytes = generate_radio_icon()
    return Response(
        content=icon_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/icons/{slug}.png")
async def get_source_icon(slug: str):
    """Generate and serve a source icon."""
    with db_session() as session:
        source = SourceRepository.get_by_slug(session, slug)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        source_name = source.name

    # Generate icon
    icon_bytes = generate_letter_icon(source_name)
    return Response(
        content=icon_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},  # Cache for 1 day
    )


@router.get("/feeds/all.xml")
async def get_unified_feed():
    """Serve the unified RSS feed combining all sources."""
    generator = get_rss_generator()
    try:
        feed_path = generator.generate_unified_feed()
        return FileResponse(feed_path, media_type="application/rss+xml")
    except Exception as e:
        logger.error(f"Failed to generate unified feed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/feeds/{slug}.xml")
async def get_feed(slug: str):
    """Serve an RSS feed XML file."""
    with db_session() as session:
        source = SourceRepository.get_by_slug(session, slug)
        if not source:
            raise HTTPException(status_code=404, detail="Feed not found")
        source_id = source.id

    # Generate/update the feed
    generator = get_rss_generator()
    try:
        feed_path = generator.generate_source_feed(source_id)
        return FileResponse(feed_path, media_type="application/rss+xml")
    except Exception as e:
        logger.error(f"Failed to generate feed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/feeds/{source_id}/regenerate")
async def regenerate_feed(source_id: int):
    """Regenerate the RSS feed for a source."""
    generator = get_rss_generator()
    try:
        feed_path = generator.generate_source_feed(source_id)
        return {"message": "Feed regenerated", "path": feed_path}
    except Exception as e:
        logger.error(f"Failed to regenerate feed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Job Queue Endpoints ---


@router.get("/api/jobs")
async def get_job_status():
    """Get job queue status."""
    job_queue = get_job_queue()
    return job_queue.get_queue_status()


@router.get("/api/jobs/{item_id}")
async def get_job_for_item(item_id: int):
    """Get job status for a specific item."""
    job_queue = get_job_queue()
    job = job_queue.get_job_status(item_id)

    if not job:
        return {"item_id": item_id, "status": "not_found"}

    return {
        "item_id": job.item_id,
        "status": job.status.value,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error": job.error,
    }
