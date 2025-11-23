# Use official Python base image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies (ffmpeg + build essentials)
RUN apt-get update && \
    apt-get install -y ffmpeg libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy worker file
COPY worker.py .

# Expose nothing (worker only)
CMD ["python", "worker.py"]
