"""Kokoro API TTS engine implementation (self-hosted OpenAI-compatible endpoint)."""

import logging
from pathlib import Path

import requests

from src.config import get_settings
from .engine import BaseTTSEngine

logger = logging.getLogger(__name__)


class KokoroAPIEngine(BaseTTSEngine):
    """Kokoro TTS API engine (self-hosted, OpenAI-compatible)."""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.kokoro_api_url
        self.voice = self.settings.tts_voice_id or "af_bella"
        self.model = "kokoro"

    def is_available(self) -> bool:
        """Check if the API is reachable."""
        try:
            # Simple check - just verify the URL is configured
            return bool(self.base_url)
        except Exception:
            return False

    def synthesize(self, text: str, output_path: Path) -> Path:
        """
        Synthesize text using Kokoro API.

        Args:
            text: Text to convert to speech
            output_path: Path to save the audio file

        Returns:
            Path to the generated audio file
        """
        # Ensure .mp3 extension
        if output_path.suffix.lower() != ".mp3":
            output_path = output_path.with_suffix(".mp3")

        headers = {
            "Content-Type": "application/json",
        }

        # Kokoro can handle longer texts, but let's be safe
        max_chars = 5000
        chunks = self._split_text(text, max_chars)

        audio_parts = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")

            payload = {
                "model": self.model,
                "voice": self.voice,
                "input": chunk,
                "response_format": "mp3",
            }

            response = requests.post(
                f"{self.base_url}/audio/speech",
                headers=headers,
                json=payload,
                timeout=300,  # Longer timeout for self-hosted
            )
            response.raise_for_status()
            audio_parts.append(response.content)

        # Combine audio parts
        combined_audio = b"".join(audio_parts)

        # Write to file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(combined_audio)

        logger.info(f"Audio saved to {output_path}")
        return output_path

    def _split_text(self, text: str, max_chars: int) -> list[str]:
        """Split text into chunks at sentence boundaries."""
        if len(text) <= max_chars:
            return [text]

        chunks = []
        current_chunk = ""
        sentences = text.replace("\n\n", "\n").split(". ")

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if not sentence.endswith("."):
                sentence += "."

            if len(current_chunk) + len(sentence) + 1 <= max_chars:
                current_chunk += (" " if current_chunk else "") + sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks if chunks else [text[:max_chars]]
