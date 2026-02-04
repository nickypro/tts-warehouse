"""Unreal Speech TTS API engine implementation."""

import logging
import re
import time
from pathlib import Path

import requests

from src.config import get_settings
from .engine import BaseTTSEngine

logger = logging.getLogger(__name__)


def normalize_text_for_tts(text: str) -> str:
    """Normalize text for TTS by replacing special characters."""
    # Replace smart quotes with regular quotes
    replacements = {
        ''': "'",
        ''': "'",
        '"': '"',
        '"': '"',
        '…': '...',
        '–': '-',
        '—': '-',
        '\u00a0': ' ',  # Non-breaking space
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    # Remove any remaining non-printable characters except newlines
    text = ''.join(c for c in text if c.isprintable() or c in '\n\r\t')
    
    return text


class UnrealSpeechEngine(BaseTTSEngine):
    """Unreal Speech TTS API engine."""

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.unrealspeech_api_key
        self.voice_id = self.settings.tts_voice_id
        self.base_url = "https://api.v6.unrealspeech.com"

    def is_available(self) -> bool:
        """Check if API key is configured."""
        return bool(self.api_key)

    def synthesize(self, text: str, output_path: Path) -> Path:
        """
        Synthesize text using Unreal Speech API.

        Args:
            text: Text to convert to speech
            output_path: Path to save the audio file

        Returns:
            Path to the generated audio file
        """
        if not self.is_available():
            raise ValueError("UNREALSPEECH_API_KEY not configured")

        # Ensure .mp3 extension
        if output_path.suffix.lower() != ".mp3":
            output_path = output_path.with_suffix(".mp3")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Normalize text to remove smart quotes and other problematic characters
        text = normalize_text_for_tts(text)
        
        # Split long text into chunks (Unreal Speech limit is 1000 chars)
        max_chars = 1000
        chunks = self._split_text(text, max_chars)

        audio_parts = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")
            
            payload = {
                "Text": chunk,
                "VoiceId": self.voice_id,
                "Bitrate": "192k",
                "Speed": 0,
                "Pitch": 1.0,
                "Codec": "libmp3lame",
                "Temperature": 0.25,
            }

            start_time = time.time()
            response = requests.post(
                f"{self.base_url}/stream",
                headers=headers,
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            elapsed = time.time() - start_time

            logger.info(f"Chunk {i + 1} generated in {elapsed:.2f}s")
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

        # Split by sentences (roughly)
        sentences = text.replace("\n\n", "\n").split(". ")

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # Add period back if it was removed by split
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
