"""RSS feed generator for output podcast feeds."""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree as ET

from src.config import get_settings
from src.database import db_session, Source, Item, ItemRepository, ItemStatus, SourceRepository, SourceType
from src.services.summary_service import generate_summary

logger = logging.getLogger(__name__)

# TTS speaking rate: ~150 words/min, ~5 chars/word = ~750 chars/min
CHARS_PER_MINUTE = 750


def build_enhanced_description(
    content_text: str,
    content_meta: dict,
    url: str,
    max_preview: int = 300,
) -> str:
    """
    Build an enhanced description with preview, summary, link, and images.

    Uses pre-generated summary from content_meta if available.
    Returns HTML for proper rendering in podcast apps.

    Args:
        content_text: The full text content
        content_meta: Metadata dict (may contain description, image_urls, summary)
        url: Original article URL
        max_preview: Maximum length of text preview

    Returns:
        Enhanced description as HTML string
    """
    parts = []

    # 1. Short text preview
    preview = content_meta.get("description", "")
    if not preview and content_text:
        preview = content_text[:max_preview]
        if len(content_text) > max_preview:
            preview += "..."
    if preview:
        parts.append(f"<p>{preview}</p>")

    # 2. AI Summary (use cached if available)
    summary = content_meta.get("summary")
    if summary:
        parts.append(f"<p><strong>Summary:</strong> {summary}</p>")

    # 3. Link to original
    parts.append(f'<p><a href="{url}" target="_blank">Read the original article</a></p>')

    # 4. Separator and rendered images
    image_urls = content_meta.get("image_urls", [])
    if not image_urls and content_meta.get("image_url"):
        image_urls = [content_meta["image_url"]]

    if image_urls:
        parts.append("<p>---</p>")
        parts.append('<div style="max-width: 100%;">')
        parts.append("<p><strong>Images from the article:</strong></p>")

        for img_url in image_urls[:10]:  # Limit to 10 images
            parts.append(
                f'<a href="{img_url}" target="_blank">'
                f'<img src="{img_url}" style="max-width: 100%;" />'
                f'</a>'
                f'<hr style="margin-top: 12px; margin-bottom: 12px;" />'
            )

        parts.append(
            "<p><em>Apple Podcasts and Spotify do not show images in episode descriptions. "
            'Try <a href="https://pocketcasts.com/" target="_blank">Pocket Casts</a> '
            "or another podcast app.</em></p>"
        )
        parts.append("</div>")

    return "".join(parts)


def estimate_duration_from_text(text: str, round_to: int = 5) -> int:
    """
    Estimate audio duration in seconds from text character count.

    Args:
        text: The text content
        round_to: Round to nearest N minutes (1 or 5)

    Returns:
        Estimated duration in seconds, rounded to nearest minute or 5 minutes
    """
    if not text:
        return 60  # Default 1 minute if no text

    char_count = len(text)
    estimated_minutes = char_count / CHARS_PER_MINUTE

    # Round to nearest N minutes
    rounded_minutes = round(estimated_minutes / round_to) * round_to

    # Minimum 1 minute
    return max(int(rounded_minutes * 60), 60)


class RSSGenerator:
    """Generator for podcast RSS feeds."""

    def __init__(self):
        self.settings = get_settings()

    def generate_source_feed(self, source_id: int) -> str:
        """
        Generate an RSS feed for a source.

        Args:
            source_id: ID of the source

        Returns:
            Path to the generated RSS file
        """
        with db_session() as session:
            source = SourceRepository.get_by_id(session, source_id)
            if not source:
                raise ValueError(f"Source {source_id} not found")

            # For lazy sources, include all items (audio generated on-demand)
            # For eager sources, only include ready items
            from src.database import ProcessingMode
            if source.processing_mode == ProcessingMode.LAZY:
                items = ItemRepository.get_by_source(session, source_id)
            else:
                items = ItemRepository.get_ready_items(session, source_id)

            return self._generate_feed(
                title=source.name,
                slug=source.slug,
                description=source.settings.get("description", f"TTS feed for {source.name}"),
                link=source.url,
                items=items,
                image_url=source.settings.get("image_url") or source.settings.get("cover_image"),
                is_lazy=source.processing_mode == ProcessingMode.LAZY,
            )

    def generate_all_feeds(self) -> List[str]:
        """
        Generate RSS feeds for all sources.

        Returns:
            List of paths to generated RSS files
        """
        with db_session() as session:
            sources = SourceRepository.get_all(session)

        paths = []
        for source in sources:
            try:
                path = self.generate_source_feed(source.id)
                paths.append(path)
            except Exception as e:
                logger.error(f"Failed to generate feed for source {source.id}: {e}")

        return paths

    def _generate_feed(
        self,
        title: str,
        slug: str,
        description: str,
        link: str,
        items: List[Item],
        image_url: Optional[str] = None,
        is_lazy: bool = False,
    ) -> str:
        """
        Generate an RSS feed XML file.

        Args:
            title: Feed title
            slug: Feed slug (for filename)
            description: Feed description
            link: Original source link
            items: List of items
            image_url: Optional feed image URL
            is_lazy: If True, include items without audio (on-demand generation)

        Returns:
            Path to the generated RSS file
        """
        base_url = self.settings.base_url.rstrip("/")

        # Create RSS structure
        rss = ET.Element("rss", version="2.0")
        rss.set("xmlns:itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
        rss.set("xmlns:content", "http://purl.org/rss/1.0/modules/content/")

        channel = ET.SubElement(rss, "channel")

        # Channel metadata
        ET.SubElement(channel, "title").text = title
        ET.SubElement(channel, "link").text = link
        ET.SubElement(channel, "description").text = description
        ET.SubElement(channel, "language").text = "en-us"
        ET.SubElement(channel, "generator").text = "TTS Warehouse"

        # iTunes metadata
        ET.SubElement(channel, "itunes:author").text = "TTS Warehouse"
        ET.SubElement(channel, "itunes:summary").text = description

        # Feed image
        if image_url:
            image = ET.SubElement(channel, "image")
            ET.SubElement(image, "url").text = image_url
            ET.SubElement(image, "title").text = title
            ET.SubElement(image, "link").text = link

            itunes_image = ET.SubElement(channel, "itunes:image")
            itunes_image.set("href", image_url)

        # Add items
        for item in items:
            # Skip items without audio unless lazy mode (on-demand generation)
            if not item.audio_path and not is_lazy:
                continue

            item_elem = ET.SubElement(channel, "item")

            ET.SubElement(item_elem, "title").text = item.title
            ET.SubElement(item_elem, "link").text = item.url

            # Description (enhanced with summary, link, images)
            description_text = build_enhanced_description(
                content_text=item.content_text or "",
                content_meta=item.content_meta or {},
                url=item.url,
            )
            ET.SubElement(item_elem, "description").text = description_text

            # Publication date (RFC 822 format)
            if item.published_at:
                pub_date = item.published_at.strftime("%a, %d %b %Y %H:%M:%S +0000")
            else:
                pub_date = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
            ET.SubElement(item_elem, "pubDate").text = pub_date

            # GUID
            ET.SubElement(item_elem, "guid", isPermaLink="false").text = f"tts-warehouse-{item.id}"

            # Audio enclosure - URL always points to our endpoint (triggers lazy TTS if needed)
            audio_url = f"{base_url}/audio/{item.id}.mp3"
            
            # Get file size if audio exists
            file_size = 0
            if item.audio_path:
                audio_path = Path(item.audio_path)
                try:
                    file_size = audio_path.stat().st_size
                except OSError:
                    pass

            enclosure = ET.SubElement(item_elem, "enclosure")
            enclosure.set("url", audio_url)
            # Use placeholder size for lazy items without audio yet
            enclosure.set("length", str(file_size) if file_size > 0 else "1000000")
            enclosure.set("type", "audio/mpeg")

            # iTunes duration
            if file_size > 0:
                # Actual file: estimate from file size (192kbps = 24KB/s)
                estimated_duration = file_size // 24000
            else:
                # No audio yet: estimate from text length
                # Round to 5 min for longer content (>10 min), 1 min for shorter
                text = item.content_text or ""
                raw_estimate = len(text) / CHARS_PER_MINUTE
                round_to = 5 if raw_estimate > 10 else 1
                estimated_duration = estimate_duration_from_text(text, round_to)

            minutes, seconds = divmod(estimated_duration, 60)
            hours, minutes = divmod(minutes, 60)
            if hours:
                duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                duration_str = f"{minutes}:{seconds:02d}"
            ET.SubElement(item_elem, "itunes:duration").text = duration_str

        # Write to file
        feeds_dir = Path(self.settings.database_path).parent / "feeds"
        feeds_dir.mkdir(parents=True, exist_ok=True)

        output_path = feeds_dir / f"{slug}.xml"

        tree = ET.ElementTree(rss)
        tree.write(str(output_path), encoding="utf-8", xml_declaration=True)

        logger.info(f"Generated RSS feed: {output_path}")
        return str(output_path)

    def get_feed_url(self, slug: str) -> str:
        """Get the public URL for a feed."""
        base_url = self.settings.base_url.rstrip("/")
        return f"{base_url}/feeds/{slug}.xml"

    def generate_unified_feed(self) -> str:
        """
        Generate a unified RSS feed combining all sources.
        Each item includes an icon based on its source.

        Returns:
            Path to the generated RSS file
        """
        base_url = self.settings.base_url.rstrip("/")

        with db_session() as session:
            sources = SourceRepository.get_all(session)

            # Filter out books (Royal Road) from unified feed
            sources = [s for s in sources if s.type != SourceType.ROYAL_ROAD]

            # Build a map of source_id -> source info
            source_map = {}
            for source in sources:
                source_map[source.id] = {
                    "name": source.name,
                    "slug": source.slug,
                    "icon_url": f"{base_url}/icons/{source.slug}.png",
                }

            # Get all items from all sources, extract data while in session
            all_items = []
            for source in sources:
                items = ItemRepository.get_by_source(session, source.id)
                for item in items:
                    # Extract all needed data while in session
                    all_items.append({
                        "id": item.id,
                        "title": item.title,
                        "url": item.url,
                        "content_text": item.content_text,
                        "content_meta": item.content_meta or {},
                        "audio_path": item.audio_path,
                        "published_at": item.published_at,
                        "source_name": source_map[source.id]["name"],
                        "source_icon": source_map[source.id]["icon_url"],
                    })

        # Sort by published date (newest first)
        all_items.sort(
            key=lambda x: x["published_at"] or datetime.min,
            reverse=True
        )

        # Create RSS structure
        rss = ET.Element("rss", version="2.0")
        rss.set("xmlns:itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
        rss.set("xmlns:content", "http://purl.org/rss/1.0/modules/content/")

        channel = ET.SubElement(rss, "channel")

        # Channel metadata
        ET.SubElement(channel, "title").text = "TTS Warehouse - All Feeds"
        ET.SubElement(channel, "link").text = base_url
        ET.SubElement(channel, "description").text = "Unified feed combining all TTS Warehouse sources"
        ET.SubElement(channel, "language").text = "en-us"
        ET.SubElement(channel, "generator").text = "TTS Warehouse"

        # iTunes metadata
        ET.SubElement(channel, "itunes:author").text = "TTS Warehouse"
        ET.SubElement(channel, "itunes:summary").text = "Unified feed combining all TTS Warehouse sources"

        # Feed image (radio icon)
        feed_icon_url = f"{base_url}/icons/all.png"
        image = ET.SubElement(channel, "image")
        ET.SubElement(image, "url").text = feed_icon_url
        ET.SubElement(image, "title").text = "TTS Warehouse - All Feeds"
        ET.SubElement(image, "link").text = base_url

        itunes_image = ET.SubElement(channel, "itunes:image")
        itunes_image.set("href", feed_icon_url)

        # Add items
        for item_data in all_items:
            source_name = item_data["source_name"]
            source_icon = item_data["source_icon"]

            item_elem = ET.SubElement(channel, "item")

            # Prefix title with source name
            ET.SubElement(item_elem, "title").text = f"[{source_name}] {item_data['title']}"
            ET.SubElement(item_elem, "link").text = item_data["url"]

            # Description (enhanced with summary, link, images)
            description_text = build_enhanced_description(
                content_text=item_data["content_text"] or "",
                content_meta=item_data["content_meta"] or {},
                url=item_data["url"],
            )
            ET.SubElement(item_elem, "description").text = description_text

            # Publication date
            if item_data["published_at"]:
                pub_date = item_data["published_at"].strftime("%a, %d %b %Y %H:%M:%S +0000")
            else:
                pub_date = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
            ET.SubElement(item_elem, "pubDate").text = pub_date

            # GUID
            ET.SubElement(item_elem, "guid", isPermaLink="false").text = f"tts-warehouse-{item_data['id']}"

            # Audio enclosure
            audio_url = f"{base_url}/audio/{item_data['id']}.mp3"
            file_size = 0
            if item_data["audio_path"]:
                audio_path = Path(item_data["audio_path"])
                try:
                    file_size = audio_path.stat().st_size
                except OSError:
                    pass

            enclosure = ET.SubElement(item_elem, "enclosure")
            enclosure.set("url", audio_url)
            enclosure.set("length", str(file_size) if file_size > 0 else "1000000")
            enclosure.set("type", "audio/mpeg")

            # iTunes image for this item (source-specific icon)
            itunes_image = ET.SubElement(item_elem, "itunes:image")
            itunes_image.set("href", source_icon)

            # iTunes duration
            if file_size > 0:
                # Actual file: estimate from file size (192kbps = 24KB/s)
                estimated_duration = file_size // 24000
            else:
                # No audio yet: estimate from text length
                text = item_data["content_text"] or ""
                raw_estimate = len(text) / CHARS_PER_MINUTE
                round_to = 5 if raw_estimate > 10 else 1
                estimated_duration = estimate_duration_from_text(text, round_to)

            minutes, seconds = divmod(estimated_duration, 60)
            hours, minutes = divmod(minutes, 60)
            if hours:
                duration_str = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                duration_str = f"{minutes}:{seconds:02d}"
            ET.SubElement(item_elem, "itunes:duration").text = duration_str

        # Write to file
        feeds_dir = Path(self.settings.database_path).parent / "feeds"
        feeds_dir.mkdir(parents=True, exist_ok=True)

        output_path = feeds_dir / "all.xml"

        tree = ET.ElementTree(rss)
        tree.write(str(output_path), encoding="utf-8", xml_declaration=True)

        logger.info(f"Generated unified RSS feed: {output_path}")
        return str(output_path)
