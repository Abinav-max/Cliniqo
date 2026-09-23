# Cliniqo MediKiosk - Production Dockerfile for Render & Cloud Deployment
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr for real-time streaming logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DATA_DIR=/app/data

WORKDIR /app

# Install system dependencies:
# - tesseract-ocr & language packs (English, Hindi) for medical prescription & report OCR
# - libgl1 & libglib2.0-0 for Pillow & OpenCV image processing
# - curl for Render container health probes
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-hin \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure storage directories exist with full read/write permissions
RUN mkdir -p /app/data/documents /app/static && \
    chmod -R 777 /app/data

# Expose default port
EXPOSE 8000

# Health check probe for Render
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Start Uvicorn dynamically bound to $PORT (automatically assigned by Render) with reverse-proxy support
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=\"*\""]
