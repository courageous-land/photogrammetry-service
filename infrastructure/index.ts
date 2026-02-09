/**
 * Photogrammetry Service Infrastructure
 * 
 * This Pulumi program provisions all GCP resources required for the
 * photogrammetry processing service:
 * 
 * - Cloud Storage: Buckets for uploads and outputs
 * - Firestore: Project metadata storage
 * - Artifact Registry: Docker image repository
 * - Cloud Run: API hosting
 * - Cloud Batch: Processing job execution
 * - IAM: Service accounts and permissions
 */
import * as pulumi from "@pulumi/pulumi";
import * as gcp from "@pulumi/gcp";

import { createStorage } from "./src/storage";
import { createServiceAccounts, configureIamPermissions } from "./src/iam";
import { createCloudRunService } from "./src/cloud-run";

// Configuration
const config = new pulumi.Config();
const gcpConfig = new pulumi.Config("gcp");

const project = gcpConfig.require("project");
const region = gcpConfig.require("region");
const environment = config.get("environment") || "dev";
const serviceName = "photogrammetry";

// Enable required APIs
const enabledApis = [
    "run.googleapis.com",
    "storage.googleapis.com",
    "firestore.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "batch.googleapis.com",
    "compute.googleapis.com",
].map((api) =>
    new gcp.projects.Service(`enable-${api.split(".")[0]}`, {
        project,
        service: api,
        disableOnDestroy: false,
    })
);

// Storage
const storage = createStorage(
    { project, region, serviceName, environment },
    enabledApis
);

// Firestore
const firestore = new gcp.firestore.Database(`${serviceName}-db`, {
    name: "(default)",
    locationId: region,
    type: "FIRESTORE_NATIVE",
}, { dependsOn: enabledApis });

// Artifact Registry
const artifactRegistry = new gcp.artifactregistry.Repository(`${serviceName}-repo`, {
    repositoryId: serviceName,
    location: region,
    format: "DOCKER",
    description: "Docker images for photogrammetry service",
}, { dependsOn: enabledApis });

const artifactRegistryUrl = pulumi.interpolate`${region}-docker.pkg.dev/${project}/${artifactRegistry.repositoryId}`;

// Service Accounts
const serviceAccounts = createServiceAccounts({ project, serviceName });
configureIamPermissions({ project, serviceName }, serviceAccounts);

// Cloud Run
const cloudRun = createCloudRunService(
    {
        project,
        region,
        serviceName,
        apiServiceAccountEmail: serviceAccounts.apiServiceAccount.email,
        workerServiceAccountEmail: serviceAccounts.workerServiceAccount.email,
        uploadsBucketName: storage.uploadsBucket.name,
        outputsBucketName: storage.outputsBucket.name,
        artifactRegistryUrl,
        environment,
    },
    enabledApis
);

// Exports
export const outputs = {
    // Buckets
    uploadsBucket: storage.uploadsBucket.name,
    outputsBucket: storage.outputsBucket.name,
    
    // Service Accounts
    apiServiceAccountEmail: serviceAccounts.apiServiceAccount.email,
    workerServiceAccountEmail: serviceAccounts.workerServiceAccount.email,
    
    // Artifact Registry
    artifactRegistryUrl,
    
    // Cloud Run
    apiUrl: cloudRun.url,
    
    // Configuration
    project,
    region,
    environment,
};

// Individual exports for easy access
export const uploadsBucketName = storage.uploadsBucket.name;
export const outputsBucketName = storage.outputsBucket.name;
export const apiUrl = cloudRun.url;
