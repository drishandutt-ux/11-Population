# Playwright's Python image: Python 3.12 + Chromium and its system libraries preinstalled.
# The browser version matches playwright==1.60.0 in requirements.txt — keep them in step.
FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

# FFmpeg + build tools (PyAV / faster-whisper for YouTube ingestion)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg gcc g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
