FROM python:3.11-slim

# Install system dependencies including ffmpeg (required by yt-dlp)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install with --no-build-isolation
COPY requirements.txt .
RUN pip install --no-cache-dir --no-build-isolation -r requirements.txt

# Copy app files
COPY index.html .
COPY app.py .

# Expose port
EXPOSE 8000

# Run the app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
