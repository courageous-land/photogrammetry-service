/**
 * Cloud Storage Configuration
 * 
 * Creates and configures storage buckets for:
 * - Uploads: Raw images uploaded by users
 * - Outputs: Processed photogrammetry results
 */
import * as gcp from "@pulumi/gcp";
import * as pulumi from "@pulumi/pulumi";

export interface StorageConfig {
    project: pulumi.Input<string>;
    region: string;
    serviceName: string;
    environment: string;
    allowedOrigins: string;
}

export interface StorageResources {
    uploadsBucket: gcp.storage.Bucket;
    outputsBucket: gcp.storage.Bucket;
}

export function createStorage(
    config: StorageConfig,
    dependsOn: pulumi.Resource[]
): StorageResources {
    const { project, region, serviceName, environment, allowedOrigins } = config;
    
    // Determine lifecycle based on environment
    const uploadsLifecycleDays = environment === "prod" ? 30 : 7;
    
    // Lifecycle configuration per environment
    const outputsLifecycleDays = environment === "prod" ? 365 : 30;

    const corsOrigins = allowedOrigins.split(",")
        .map((origin) => origin.trim())
        .filter((origin) => origin.length > 0);

    const effectiveCorsOrigins = corsOrigins.length > 0 ? corsOrigins : ["*"];

    // Uploads bucket - for raw images
    const uploadsBucket = new gcp.storage.Bucket(`${serviceName}-uploads`, {
        name: pulumi.interpolate`${project}-${serviceName}-uploads`,
        location: region,
        uniformBucketLevelAccess: true,
        publicAccessPrevention: "enforced",
        forceDestroy: environment !== "prod",
        lifecycleRules: [{
            action: { type: "Delete" },
            condition: { age: uploadsLifecycleDays },
        }],
        cors: [{
            origins: effectiveCorsOrigins,
            methods: ["GET", "PUT", "POST", "HEAD", "OPTIONS"],
            responseHeaders: [
                "*",
                "Content-Type",
                "Content-Length",
                "Content-Range",
                "Range",
                "X-GUploader-UploadID",
                "X-Upload-Content-Type",
                "X-Upload-Content-Length",
            ],
            maxAgeSeconds: 3600,
        }],
    }, { dependsOn });

    // Outputs bucket - for processed results
    const outputsBucket = new gcp.storage.Bucket(`${serviceName}-outputs`, {
        name: pulumi.interpolate`${project}-${serviceName}-outputs`,
        location: region,
        uniformBucketLevelAccess: true,
        publicAccessPrevention: "enforced",
        forceDestroy: environment !== "prod",
        lifecycleRules: [{
            action: { type: "Delete" },
            condition: { age: outputsLifecycleDays },
        }],
        cors: [{
            origins: effectiveCorsOrigins,
            methods: ["GET"],
            responseHeaders: ["*"],
            maxAgeSeconds: 3600,
        }],
    }, { dependsOn });

    return { uploadsBucket, outputsBucket };
}
