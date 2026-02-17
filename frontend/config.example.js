/**
 * Configuration Example
 * Copy this file to config.js and set your API URL.
 *
 * Production (frontend served from GCS bucket behind same LB):
 *   API_URL: ''  (empty = same origin, no CORS)
 *
 * Local dev (via gcloud run services proxy photogrammetry-api --region=southamerica-east1):
 *   API_URL: 'http://localhost:8080'
 */
window.PHOTOGRAMMETRY_CONFIG = {
    API_URL: ''
};
