# =============================================================================
# Synthesis Decision Agent — MAF Hosted Agent container
# =============================================================================
# IMPORTANT: --platform=linux/amd64 is required — Foundry Hosted Agents run on
# Linux AMD64 infrastructure. Images built without this (e.g. on Apple Silicon)
# will fail at runtime. See: https://aka.ms/foundry-hosted-agents
FROM --platform=linux/amd64 python:3.12-slim

# Install curl for health check
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent code and skills
COPY main.py ./
COPY schemas.py ./
COPY skills/ ./skills/

# Non-root user
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "main.py"]
