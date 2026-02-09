/**
 * IAM Configuration
 * 
 * Creates service accounts and configures permissions for:
 * - API: Cloud Run service for the REST API
 * - Worker: Cloud Batch jobs for photogrammetry processing
 */
import * as gcp from "@pulumi/gcp";
import * as pulumi from "@pulumi/pulumi";

export interface IamConfig {
    project: pulumi.Input<string>;
    serviceName: string;
}

export interface IamResources {
    apiServiceAccount: gcp.serviceaccount.Account;
    workerServiceAccount: gcp.serviceaccount.Account;
}

export function createServiceAccounts(config: IamConfig): IamResources {
    const { project, serviceName } = config;

    // Service Account for API (Cloud Run)
    const apiServiceAccount = new gcp.serviceaccount.Account(`${serviceName}-api-sa`, {
        accountId: `${serviceName}-api`,
        displayName: "Photogrammetry API Service Account",
        project,
    });

    // Service Account for Worker (Cloud Batch)
    const workerServiceAccount = new gcp.serviceaccount.Account(`${serviceName}-worker-sa`, {
        accountId: `${serviceName}-worker`,
        displayName: "Photogrammetry Worker Service Account",
        project,
    });

    return { apiServiceAccount, workerServiceAccount };
}

export function configureIamPermissions(
    config: IamConfig,
    serviceAccounts: IamResources
): void {
    const { project } = config;
    const { apiServiceAccount, workerServiceAccount } = serviceAccounts;

    // API permissions
    const apiPermissions = [
        "roles/storage.objectAdmin",            // Manage storage objects
        "roles/pubsub.publisher",               // Publish messages
        "roles/datastore.user",                 // Access Firestore
        "roles/batch.jobsEditor",               // Create Batch jobs
        "roles/iam.serviceAccountTokenCreator", // Sign URLs in Cloud Run
    ];

    apiPermissions.forEach((role, index) => {
        new gcp.projects.IAMMember(`api-iam-${index}`, {
            project,
            role,
            member: pulumi.interpolate`serviceAccount:${apiServiceAccount.email}`,
        });
    });

    // Worker permissions
    const workerPermissions = [
        "roles/storage.objectAdmin",       // Read/write storage
        "roles/datastore.user",            // Update Firestore
        "roles/pubsub.publisher",          // Publish events
        "roles/logging.logWriter",         // Write logs
        "roles/batch.agentReporter",       // Report batch status
        "roles/artifactregistry.reader",   // Pull Docker images
    ];

    workerPermissions.forEach((role, index) => {
        new gcp.projects.IAMMember(`worker-iam-${index}`, {
            project,
            role,
            member: pulumi.interpolate`serviceAccount:${workerServiceAccount.email}`,
        });
    });

    // API can act as worker to create Batch jobs
    new gcp.serviceaccount.IAMMember(`api-act-as-worker`, {
        serviceAccountId: workerServiceAccount.name,
        role: "roles/iam.serviceAccountUser",
        member: pulumi.interpolate`serviceAccount:${apiServiceAccount.email}`,
    });
}
