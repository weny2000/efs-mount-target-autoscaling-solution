# Dockerfile for Fargate Application

FROM python:3.11-slim

# Install system dependencies for NFS mounting
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    nfs-common \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .

# Create mount point directories
RUN mkdir -p /mnt/efs-base

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "app.py"]
