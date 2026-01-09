FROM python:3.11-slim

LABEL maintainer="Flamehaven Labs <info@flamehaven.space>"
LABEL description="AI SLOP Detector - Production-ready code quality analyzer"
LABEL version="2.0.0"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create non-root user
RUN useradd -m -u 1000 slopuser && \
    chown -R slopuser:slopuser /app

USER slopuser

# Default command
ENTRYPOINT ["slop-detector"]
CMD ["--help"]

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD slop-detector --version || exit 1
