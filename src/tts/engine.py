"""TTS engine abstraction layer."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from src.config import get_settings

logger = logging.getLogger(__name__)


class BaseTTSEngine(ABC):
    """Abstract base class for TTS engines."""

    @abstractmethod
    def synthesize(self, text: str, output_path: Path) -> Path:
        """
        Synthesize text to speech and save to file.

        Args:
            text: Text to convert to speech
            output_path: Path to save the audio file

        Returns:
            Path to the generated audio file
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the TTS engine is properly configured and available."""
        pass


class TTSEngine:
    """
    Main TTS engine that delegates to the configured provider.
    
    Supports:
    - Unreal Speech API (default)
    - OpenAI TTS API
    - Kokoro API (self-hosted)
    """

    def __init__(self):
        self.settings = get_settings()
        self._engine: Optional[BaseTTSEngine] = None

    def _get_engine(self) -> BaseTTSEngine:
        """Get or create the appropriate TTS engine based on settings."""
        if self._engine is not None:
            return self._engine

        engine_type = self.settings.tts_engine

        if engine_type == "unrealspeech":
            from .unrealspeech import UnrealSpeechEngine
            self._engine = UnrealSpeechEngine()
        elif engine_type == "openai":
            from .openai_tts import OpenAITTSEngine
            self._engine = OpenAITTSEngine()
        elif engine_type == "kokoro_api":
            from .kokoro_api import KokoroAPIEngine
            self._engine = KokoroAPIEngine()
        else:
            raise ValueError(f"Unknown TTS engine: {engine_type}")

        return self._engine

    def synthesize(self, text: str, output_path: Path) -> Path:
        """
        Synthesize text to speech.

        Args:
            text: Text to convert to speech
            output_path: Path to save the audio file

        Returns:
            Path to the generated audio file
        """
        engine = self._get_engine()
        
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Synthesizing {len(text)} characters to {output_path}")
        return engine.synthesize(text, output_path)

    def is_available(self) -> bool:
        """Check if the TTS engine is available."""
        try:
            engine = self._get_engine()
            return engine.is_available()
        except Exception as e:
            logger.error(f"TTS engine not available: {e}")
            return False


# Singleton instance
_tts_engine: Optional[TTSEngine] = None


def get_tts_engine() -> TTSEngine:
    """Get the TTS engine singleton instance."""
    global _tts_engine
    if _tts_engine is None:
        _tts_engine = TTSEngine()
    return _tts_engine
