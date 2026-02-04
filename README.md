# TTS Warehouse

A self-hosted application that converts articles, RSS feeds, and Royal Road books to TTS audio and generates podcast RSS feeds.

## Features

- **Single Article**: Add any URL, parse content, convert to audio
- **RSS/Substack Feeds**: Subscribe to feeds and auto-convert new articles
- **Royal Road Books**: Convert web novels to audiobook feeds
- **Smart Processing**: Eager mode for small sources (<10 items), lazy mode for large sources
- **Multiple TTS Engines**: Unreal Speech (default), OpenAI TTS, or self-hosted Kokoro

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Installation

```bash
cd tts_warehouse

# Install with uv
uv sync

# Copy and edit environment variables
cp env.example .env
# Edit .env with your API keys
```

### Run the Server

```bash
uv run uvicorn src.main:app --reload
```

Open http://localhost:8000 in your browser.

## Usage

1. **Add a single article**: Paste any URL to convert it to audio
2. **Add an RSS feed**: Subscribe to blogs/substacks for automatic conversion
3. **Add a Royal Road book**: Enter the book URL to create an audiobook feed

Each source generates its own podcast RSS feed that you can subscribe to in any podcast app.

## Configuration

Edit `.env` to configure:

- `UNREALSPEECH_API_KEY`: Your Unreal Speech API key
- `TTS_ENGINE`: Choose between `unrealspeech`, `openai`, or `kokoro_api`
- `TTS_VOICE_ID`: Voice to use for TTS
- `BASE_URL`: Public URL where the server is hosted (for RSS feeds)
- `LAZY_THRESHOLD`: Number of items above which lazy processing is used (default: 10)

## License

MIT
