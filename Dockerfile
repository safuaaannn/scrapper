FROM python:3.13-slim

# Shared browser path — accessible by both root (install) and scraper (runtime)
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers

# Install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Install Chromium + all required system libraries
RUN playwright install --with-deps chromium

# Non-root user for security
RUN useradd -m -s /bin/bash scraper \
    && chmod -R o+rx /opt/browsers
USER scraper
WORKDIR /home/scraper/app

# Copy application code
COPY --chown=scraper:scraper app.py .
COPY --chown=scraper:scraper scraper/ ./scraper/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]
