# Playwright's Python image: Python 3.12 + Chromium and its system libraries preinstalled.
# The browser version matches playwright==1.60.0 in requirements.txt — keep them in step.
FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

# FFmpeg + build tools (PyAV / faster-whisper for YouTube ingestion)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg gcc g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# requirements.lock.txt is the fully pinned resolution of requirements.txt (uv pip compile, Linux
# x86_64, Python 3.12). Installing the lock keeps a new transitive release from breaking the
# build — a pip ResolutionImpossible on python-dateutil took the backend deploy down on 2026-09-28.
# Regenerate after editing requirements.txt:
#   uv pip compile requirements.txt --python-version 3.12 --python-platform x86_64-manylinux_2_28 --no-header -o requirements.lock.txt
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY . .

EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
