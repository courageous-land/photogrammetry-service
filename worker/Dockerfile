# Photogrammetry Worker
# Based on OpenDroneMap for photogrammetry processing

FROM opendronemap/odm:3.5.3

WORKDIR /worker

# Install Python dependencies
RUN pip install --no-cache-dir \
    google-cloud-storage \
    google-cloud-firestore \
    google-cloud-pubsub

# Copy worker code
COPY main.py .

# Create work directory and set permissions
RUN mkdir -p /work && \
    useradd -m -u 1000 worker && \
    chown -R worker:worker /work /worker

# Run as non-root
USER worker

# Override ODM entrypoint so our worker script runs instead
ENTRYPOINT []
CMD ["python3", "/worker/main.py"]
