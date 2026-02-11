# Photogrammetry Service

Microservice for photogrammetry processing using OpenDroneMap on Google Cloud Platform.

Transforms aerial images into orthophotos, digital surface models (DSM), digital terrain models (DTM), and point clouds.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Google Cloud Platform                            │
│                                                                          │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────┐ │
│  │  Cloud Run   │     │   Firestore  │     │      Cloud Storage       │ │
│  │    (API)     │────▶│  (Metadata)  │     │  ┌────────┐ ┌─────────┐  │ │
│  └──────────────┘     └──────────────┘     │  │Uploads │ │ Outputs │  │ │
│         │                                   │  └────────┘ └─────────┘  │ │
│         │ creates job                       └──────────────────────────┘ │
│         ▼                                              ▲                 │
│  ┌──────────────┐                                      │                 │
│  │ Cloud Batch  │──────────────────────────────────────┘                 │
│  │   (Worker)   │     downloads images, processes, uploads results       │
│  │ OpenDroneMap │                                                        │
│  └──────────────┘                                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
photogrammetry-service/
├── api/                    # REST API (FastAPI)
│   ├── main.py            # Application entry point
│   ├── models.py          # Pydantic models
│   ├── routers/           # API endpoints
│   │   └── projects.py    # Project management routes
│   ├── services/          # Business logic
│   │   ├── storage.py     # Cloud Storage & Firestore
│   │   ├── batch.py       # Cloud Batch jobs
│   │   └── processor.py   # Processing orchestration
│   ├── Dockerfile
│   └── requirements.txt
│
├── worker/                 # Processing worker (OpenDroneMap)
│   ├── main.py            # Worker entry point
│   └── Dockerfile
│
├── infrastructure/         # Pulumi IaC
│   ├── index.ts           # Main infrastructure
│   ├── src/
│   │   ├── storage.ts     # Storage buckets
│   │   ├── iam.ts         # Service accounts
│   │   └── cloud-run.ts   # Cloud Run service
│   ├── Pulumi.yaml
│   ├── Pulumi.dev.yaml
│   └── Pulumi.prod.yaml
│
├── frontend/               # Integration example
│   ├── index.html
│   ├── style.css
│   └── app.js
│
└── README.md
```

## Responsibility Boundaries (Infra vs Runtime)

| Layer | Ownership | Examples in this repository |
|------|-----------|-----------------------------|
| **Infrastructure (Pulumi)** | Persistent resources and environment contracts | Buckets, Firestore DB, Artifact Registry, IAM, Cloud Run service, operational alerts, stack configs |
| **Runtime (API/Worker)** | Request-driven and ephemeral operations | Create Batch jobs per project, read/write Firestore documents, upload/download GCS objects, execute ODM |

### Why this boundary matters

- **Reproducibility**: new environments are created from Pulumi stack config.
- **Scalability**: runtime only handles workload orchestration, not infrastructure mutation.
- **Traceability**: infrastructure decisions are versioned in Pulumi files.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/projects` | Create a new project |
| `GET` | `/projects` | List all projects |
| `GET` | `/projects/{id}` | Get project status |
| `POST` | `/projects/{id}/upload-url` | Generate upload URL |
| `POST` | `/projects/{id}/finalize-upload` | Finalize uploads |
| `POST` | `/projects/{id}/process` | Start processing |
| `GET` | `/projects/{id}/result` | Get processing results |

## Workflow

1. **Create project**: `POST /projects`
2. **Get upload URLs**: `POST /projects/{id}/upload-url` (for each image)
3. **Upload images**: Direct PUT to Cloud Storage URLs
4. **Finalize upload**: `POST /projects/{id}/finalize-upload`
5. **Start processing**: `POST /projects/{id}/process`
6. **Poll status**: `GET /projects/{id}` (until completed)
7. **Get results**: `GET /projects/{id}/result`

## Processing Options

| Option | Values | Description |
|--------|--------|-------------|
| `ortho_quality` | `low`, `medium`, `high` | Orthophoto quality (affects processing time) |
| `generate_dtm` | `true`, `false` | Generate Digital Terrain Model |
| `multispectral` | `true`, `false` | Enable multispectral processing |

## Outputs

- **Orthophoto** (`orthophoto.tif`): Georeferenced mosaic image
- **DSM** (`dsm.tif`): Digital Surface Model
- **DTM** (`dtm.tif`): Digital Terrain Model (if enabled)
- **Point Cloud** (`pointcloud.laz`): 3D point cloud

## Deployment

### Prerequisites

- Google Cloud project with billing enabled
- Pulumi CLI installed
- Docker installed

### Infrastructure Setup

```bash
cd infrastructure
npm install
pulumi stack select dev  # or prod
pulumi up
```

## New Environment Checklist

```bash
cd infrastructure
npm install
pulumi stack init <new-stack>
pulumi config set gcp:project <gcp-project-id>
pulumi config set gcp:region southamerica-east1
pulumi config set photogrammetry-service:environment <dev|prod>
pulumi up
```

Then build and push API/worker images and run `pulumi up` again to roll latest image tags if needed.

### Build and Deploy API

```bash
# Build API image
gcloud builds submit --tag $REGION-docker.pkg.dev/$PROJECT/photogrammetry/api:latest ./api

# Build Worker image
gcloud builds submit --tag $REGION-docker.pkg.dev/$PROJECT/photogrammetry/worker:latest ./worker
```

### Runtime Contract (Pulumi-owned)

In deployed environments, runtime configuration is owned by Pulumi stack config and injected into Cloud Run.
The application contract is:

| Variable | Description |
|----------|-------------|
| `GCP_PROJECT` | Google Cloud project ID |
| `GCP_REGION` | Region (e.g., `southamerica-east1`) |
| `UPLOADS_BUCKET` | Cloud Storage bucket for uploads |
| `OUTPUTS_BUCKET` | Cloud Storage bucket for outputs |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins (`*` or explicit domains) |
| `SERVICE_ACCOUNT_EMAIL` | API service account email |
| `WORKER_IMAGE` | Worker Docker image URL |
| `WORKER_SERVICE_ACCOUNT` | Worker service account email |
| `PUBSUB_TOPIC` | Topic used for status events |
| `BATCH_ALLOWED_ZONES` | Comma-separated zones for Batch VM allocation |
| `BATCH_MAX_RUN_DURATION` | Max job run duration (e.g., `43200s`) |
| `BATCH_MAX_RETRY_COUNT` | Max retries per Batch task |
| `BATCH_PROVISIONING_MODEL` | `STANDARD` or `SPOT` |

### Platform integration mode

To stay aligned with the `agroforestry-intelligence-platform` pattern:

- Pulumi stack config + runtime environment are the primary source of truth.
- Keep secrets and environment-specific values outside the repository.
- Use `.env.example` only as local development convenience.
- Do not use `.env.example` as production/deployment source.

### Pulumi stack config contract

`Pulumi.<stack>.yaml` should define operational settings for reproducible environments:

- `allowedOrigins`
- `batchAllowedZones`
- `batchMaxRunDuration`
- `batchMaxRetryCount`
- `batchProvisioningModel`
- `apiMinScale`
- `apiMaxScale`
- `cloudRunPublicAccess`
- `enableOperationalAlerts`
- `alertNotificationEmail` (optional)
- `pubsubBacklogSubscriptions` (optional)

### Local development (optional)

For local API runs only, you may copy `.env.example` to `.env`.
This is optional and should never be used as deployment/source-of-truth config.

## Integration Example

See the `frontend/` directory for a minimal integration example.

```javascript
// Create project
const project = await fetch('/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'My Project' })
}).then(r => r.json());

// Get upload URL
const upload = await fetch(`/projects/${project.project_id}/upload-url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        filename: 'image.jpg',
        file_size: file.size,
        resumable: true
    })
}).then(r => r.json());

// Upload directly to GCS
await fetch(upload.upload_url, {
    method: 'PUT',
    body: file
});

// Start processing
await fetch(`/projects/${project.project_id}/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        options: {
            ortho_quality: 'medium',
            generate_dtm: false
        }
    })
});
```

## Estimated Costs

| Resource | Estimated Cost |
|----------|----------------|
| Cloud Run API | ~$5-10/month (based on usage) |
| Cloud Batch (n2-highmem-16) | ~$1.50/hour per processing job |
| Cloud Storage | ~$0.02/GB/month |
| Firestore | ~$0.18/100K reads |

## License

Internal use only.
