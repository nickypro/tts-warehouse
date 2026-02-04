#!/usr/bin/env python
"""Entry point that loads .env and starts uvicorn with correct settings."""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

import uvicorn

if __name__ == "__main__":
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8000"))
    reload = "--reload" in sys.argv or "-r" in sys.argv

    uvicorn.run(
        "src.main:app",
        host=host,
        port=port,
        reload=reload,
    )
