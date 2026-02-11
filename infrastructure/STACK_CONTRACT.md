# Pulumi Stack Contract

This file defines the infrastructure-owned contract for runtime configuration.

## Source of truth

- `Pulumi.dev.yaml`
- `Pulumi.prod.yaml`
- `pulumi config set ...` for additional stacks

## Required stack keys

- `gcp:project`
- `gcp:region`
- `photogrammetry-service:environment`
- `photogrammetry-service:allowedOrigins`
- `photogrammetry-service:batchAllowedZones`
- `photogrammetry-service:batchMaxRunDuration`
- `photogrammetry-service:batchMaxRetryCount`
- `photogrammetry-service:batchProvisioningModel`
- `photogrammetry-service:apiMinScale`
- `photogrammetry-service:apiMaxScale`
- `photogrammetry-service:cloudRunPublicAccess`
- `photogrammetry-service:enableOperationalAlerts`

## Capacity planning keys (with defaults)

- `photogrammetry-service:batchMachineTiers` — JSON array de tiers (default: 5 tiers, n2-standard-4 a n2-highmem-32)
- `photogrammetry-service:batchMinBootDiskMb` — tamanho mínimo do disco em MiB (default: 51200)
- `photogrammetry-service:batchDiskSafetyMargin` — multiplicador de margem de segurança (default: 1.15)
- `photogrammetry-service:batchAvgImageSizeMb` — tamanho médio de uma imagem em MB (default: 9)
- `photogrammetry-service:batchWorkerCommand` — comando de entrada do worker (default: `python3,/worker/main.py`)
- `photogrammetry-service:batchLogDestination` — destino de logs do Batch (default: `CLOUD_LOGGING`)

## Optional stack keys

- `photogrammetry-service:alertNotificationEmail`
- `photogrammetry-service:pubsubBacklogSubscriptions`

## Example (new stack)

```bash
pulumi stack init sandbox
pulumi config set gcp:project cl-operational
pulumi config set gcp:region southamerica-east1
pulumi config set photogrammetry-service:environment dev
pulumi config set photogrammetry-service:allowedOrigins "*"
pulumi config set --path photogrammetry-service:batchAllowedZones[0] southamerica-east1-a
pulumi config set --path photogrammetry-service:batchAllowedZones[1] southamerica-east1-b
pulumi config set photogrammetry-service:batchMaxRunDuration 43200s
pulumi config set photogrammetry-service:batchMaxRetryCount 2
pulumi config set photogrammetry-service:batchProvisioningModel STANDARD
pulumi config set photogrammetry-service:apiMinScale 0
pulumi config set photogrammetry-service:apiMaxScale 10
pulumi config set photogrammetry-service:cloudRunPublicAccess true
pulumi config set photogrammetry-service:enableOperationalAlerts false
```

After configuration, run `pulumi up`.
