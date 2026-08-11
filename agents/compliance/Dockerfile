# =============================================================================
# Compliance Validation Agent — MAF Hosted Agent container
# =============================================================================
# Built with --platform linux/amd64 via 'az acr build --platform linux/amd64'
# (Foundry Hosted Agents run on Linux AMD64 infrastructure)
# See: https://aka.ms/foundry-hosted-agents
FROM python:3.12-slim

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

# Runs as root by design. Foundry injects HOME=/home/session and mounts the
# per-session state volume there owned by root; ResponsesHostServer creates
# $HOME/.sessions during startup, so a non-root UID gets EACCES and the
# container exits before /readiness binds (surfaces as HTTP 424
# session_not_ready). Matches the Foundry hosted-agent sample images.

ENV PYTHONUNBUFFERED=1

EXPOSE 8088

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8088/readiness || exit 1

CMD ["python", "main.py"]
