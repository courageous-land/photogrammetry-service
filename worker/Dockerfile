# Photogrammetry Worker
# Based on OpenDroneMap for photogrammetry processing

FROM opendronemap/odm:3.5.3

WORKDIR /worker

# Install Python dependencies (pinned versions for supply chain safety)
RUN pip install --no-cache-dir \
    google-cloud-storage==3.9.0 \
    google-cloud-firestore==2.23.0 \
    google-cloud-pubsub==2.35.0

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
