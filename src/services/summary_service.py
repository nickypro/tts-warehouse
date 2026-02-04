"""Summary generation using OpenRouter API."""

import logging
import re
from typing import Optional, List

import requests

from src.config import get_settings

logger = logging.getLogger(__name__)


def extract_image_urls(html_content: str) -> List[str]:
    """
    Extract image URLs from HTML content.

    Args:
        html_content: HTML string

    Returns:
        List of image URLs
    """
    if not html_content:
        return []

    # Match src attributes in img tags
    img_pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
    urls = re.findall(img_pattern, html_content, re.IGNORECASE)

    # Also match srcset
    srcset_pattern = r'<img[^>]+srcset=["\']([^"\']+)["\']'
    srcsets = re.findall(srcset_pattern, html_content, re.IGNORECASE)
    for srcset in srcsets:
        # srcset contains "url size, url size, ..."
        for part in srcset.split(','):
            url = part.strip().split()[0]
            if url and url not in urls:
                urls.append(url)

    return urls


def generate_summary(text: str, max_length: int = 3000) -> Optional[str]:
    """
    Generate a summary of the text using OpenRouter API.

    Args:
        text: Text to summarize
        max_length: Maximum text length to send (truncate if longer)

    Returns:
        Summary string or None if failed
    """
    settings = get_settings()

    if not settings.openrouter_api_key:
        logger.warning("OpenRouter API key not configured, skipping summary")
        return None

    # Truncate very long texts
    if len(text) > max_length:
        text = text[:max_length] + "..."

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.summary_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that creates concise summaries. Provide a 2-3 sentence summary of the article. Be direct and informative.",
                    },
                    {
                        "role": "user",
                        "content": f"Summarize this article:\n\n{text}",
                    },
                ],
                "max_tokens": 200,
                "temperature": 0.3,
            },
            timeout=30,
        )

        response.raise_for_status()
        data = response.json()

        summary = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return summary.strip() if summary else None

    except requests.RequestException as e:
        logger.error(f"Failed to generate summary: {e}")
        return None
    except (KeyError, IndexError) as e:
        logger.error(f"Unexpected API response format: {e}")
        return None
