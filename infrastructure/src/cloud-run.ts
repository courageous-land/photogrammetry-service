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
                        { name: "SERVICE_ACCOUNT_EMAIL", value: apiServiceAccountEmail },
                        { 
                            name: "WORKER_IMAGE", 
                            value: pulumi.interpolate`${artifactRegistryUrl}/worker:latest` 
                        },
                        { name: "WORKER_SERVICE_ACCOUNT", value: workerServiceAccountEmail },
                        { name: "PUBSUB_TOPIC", value: "photogrammetry-status" },
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
                    "autoscaling.knative.dev/minScale": environment === "prod" ? "1" : "0",
                    "autoscaling.knative.dev/maxScale": "10",
                },
            },
        },
        traffics: [{
            percent: 100,
            latestRevision: true,
        }],
    }, { dependsOn });

    // Allow public access (configure authentication as needed)
    new gcp.cloudrun.IamMember(`${serviceName}-api-invoker`, {
        service: service.name,
        location: region,
        role: "roles/run.invoker",
        member: "allUsers",
    });

    return {
        service,
        url: service.statuses[0].url,
    };
}
