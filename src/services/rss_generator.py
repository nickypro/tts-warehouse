"""RSS feed generator for output podcast feeds."""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree as ET

from src.config import get_settings
from src.database import db_session, Source, Item, ItemRepository, ItemStatus, SourceRepository

logger = logging.getLogger(__name__)


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

            # Description
            description_text = item.content_meta.get("description", "")
            if not description_text and item.content_text:
                description_text = item.content_text[:500] + "..." if len(item.content_text) > 500 else item.content_text
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

            # iTunes duration (estimate based on file size or placeholder)
            # Rough estimate: 192kbps = 24KB/s, so duration = size / 24000
            if file_size > 0:
                estimated_duration = file_size // 24000
            else:
                # Placeholder: estimate ~10 minutes for chapters without audio yet
                estimated_duration = 600
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
