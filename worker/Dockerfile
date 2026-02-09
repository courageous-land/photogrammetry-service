# Photogrammetry Worker
# Based on OpenDroneMap for photogrammetry processing

FROM opendronemap/odm:latest

WORKDIR /worker

# Install Python dependencies
RUN pip install --no-cache-dir \
    google-cloud-storage \
    google-cloud-firestore

# Copy worker code
COPY main.py .

# Create work directory
RUN mkdir -p /work

# Entry point
CMD ["python3", "/worker/main.py"]
