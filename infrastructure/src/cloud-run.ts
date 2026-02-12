/**
 * Cloud Run Configuration
 * 
 * Deploys the Photogrammetry API as a Cloud Run service.
 */
import * as gcp from "@pulumi/gcp";
import * as pulumi from "@pulumi/pulumi";

export interface CloudRunConfig {
    project: pulumi.Input<string>;
    region: string;
    serviceName: string;
    apiServiceAccountEmail: pulumi.Input<string>;
    workerServiceAccountEmail: pulumi.Input<string>;
    uploadsBucketName: pulumi.Input<string>;
    outputsBucketName: pulumi.Input<string>;
    artifactRegistryUrl: pulumi.Input<string>;
    environment: string;
    allowedOrigins: string;
    batchAllowedZones: string[];
    batchMaxRunDuration: string;
    batchMaxRetryCount: number;
    batchProvisioningModel: "STANDARD" | "SPOT";
    batchMachineTiers: string;
    batchMinBootDiskMb: number;
    batchDiskSafetyMargin: number;
    batchAvgImageSizeMb: number;
    batchWorkerCommand: string;
    batchLogDestination: string;
    apiMinScale: number;
    apiMaxScale: number;
    cloudRunPublicAccess: boolean;
}

export interface CloudRunResources {
    service: gcp.cloudrun.Service;
    url: pulumi.Output<string>;
}

export function createCloudRunService(
    config: CloudRunConfig,
    dependsOn: pulumi.Resource[]
): CloudRunResources {
    const {
        project,
        region,
        serviceName,
        apiServiceAccountEmail,
        workerServiceAccountEmail,
        uploadsBucketName,
        outputsBucketName,
        artifactRegistryUrl,
        environment,
        allowedOrigins,
        batchAllowedZones,
        batchMaxRunDuration,
        batchMaxRetryCount,
        batchProvisioningModel,
        batchMachineTiers,
        batchMinBootDiskMb,
        batchDiskSafetyMargin,
        batchAvgImageSizeMb,
        batchWorkerCommand,
        batchLogDestination,
        apiMinScale,
        apiMaxScale,
        cloudRunPublicAccess,
    } = config;

    const service = new gcp.cloudrun.Service(`${serviceName}-api`, {
        name: `${serviceName}-api`,
        location: region,
        template: {
            spec: {
                serviceAccountName: apiServiceAccountEmail,
                containers: [{
                    image: pulumi.interpolate`${artifactRegistryUrl}/api:latest`,
                    ports: [{ containerPort: 8080 }],
                    envs: [
                        { name: "GCP_PROJECT", value: project },
                        { name: "GCP_REGION", value: region },
                        { name: "UPLOADS_BUCKET", value: uploadsBucketName },
                        { name: "OUTPUTS_BUCKET", value: outputsBucketName },
                        { name: "ENVIRONMENT", value: environment },
                        { name: "ALLOWED_ORIGINS", value: allowedOrigins },
                        { name: "SERVICE_ACCOUNT_EMAIL", value: apiServiceAccountEmail },
                        { 
                            name: "WORKER_IMAGE", 
                            value: pulumi.interpolate`${artifactRegistryUrl}/worker:latest` 
                        },
                        { name: "WORKER_SERVICE_ACCOUNT", value: workerServiceAccountEmail },
                        { name: "PUBSUB_TOPIC", value: "photogrammetry-status" },
                        { name: "BATCH_ALLOWED_ZONES", value: batchAllowedZones.join(",") },
                        { name: "BATCH_MAX_RUN_DURATION", value: batchMaxRunDuration },
                        { name: "BATCH_MAX_RETRY_COUNT", value: String(batchMaxRetryCount) },
                        { name: "BATCH_PROVISIONING_MODEL", value: batchProvisioningModel },
                        { name: "BATCH_MACHINE_TIERS", value: batchMachineTiers },
                        { name: "BATCH_MIN_BOOT_DISK_MB", value: String(batchMinBootDiskMb) },
                        { name: "BATCH_DISK_SAFETY_MARGIN", value: String(batchDiskSafetyMargin) },
                        { name: "BATCH_AVG_IMAGE_SIZE_MB", value: String(batchAvgImageSizeMb) },
                        { name: "BATCH_WORKER_COMMAND", value: batchWorkerCommand },
                        { name: "BATCH_LOG_DESTINATION", value: batchLogDestination },
                    ],
                    resources: {
                        limits: {
                            memory: "512Mi",
                            cpu: "1",
                        },
                    },
                }],
                containerConcurrency: 80,
                timeoutSeconds: 300,
            },
            metadata: {
                annotations: {
                    "autoscaling.knative.dev/minScale": String(apiMinScale),
                    "autoscaling.knative.dev/maxScale": String(apiMaxScale),
                    "run.googleapis.com/ingress": "all",
                },
            },
        },
        traffics: [{
            percent: 100,
            latestRevision: true,
        }],
    }, { dependsOn });

    if (cloudRunPublicAccess) {
        // Allow public access (configure authentication as needed)
        new gcp.cloudrun.IamMember(`${serviceName}-api-invoker`, {
            service: service.name,
            location: region,
            role: "roles/run.invoker",
            member: "allUsers",
        });
    }

    return {
        service,
        url: service.statuses[0].url,
    };
}
