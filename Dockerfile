FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY src/ ./src/
COPY run.py ./

# Create data directory
RUN mkdir -p data

# Expose the port
EXPOSE 8775

# Run the application
CMD ["uv", "run", "python", "run.py"]
