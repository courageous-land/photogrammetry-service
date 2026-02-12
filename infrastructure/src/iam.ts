/**
 * IAM Configuration
 *
 * Creates service accounts and configures permissions for:
 * - API: Cloud Run service for the REST API
 * - Worker: Cloud Batch jobs for photogrammetry processing
 *
 * Follows least-privilege: storage permissions are scoped to specific
 * buckets (not project-wide), and token-creator is scoped to the API SA.
 */
import * as gcp from "@pulumi/gcp";
import * as pulumi from "@pulumi/pulumi";

export interface IamConfig {
    project: pulumi.Input<string>;
    serviceName: string;
    uploadsBucketName: pulumi.Input<string>;
    outputsBucketName: pulumi.Input<string>;
}

export interface IamResources {
    apiServiceAccount: gcp.serviceaccount.Account;
    workerServiceAccount: gcp.serviceaccount.Account;
}

export function createServiceAccounts(
    config: Pick<IamConfig, "project" | "serviceName">
): IamResources {
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
    const { project, uploadsBucketName, outputsBucketName } = config;
    const { apiServiceAccount, workerServiceAccount } = serviceAccounts;

    // -----------------------------------------------------------------
    // Project-level IAM (non-storage, non-token roles only)
    // -----------------------------------------------------------------
    const apiProjectRoles: Record<string, string> = {
        "pubsub-publisher": "roles/pubsub.publisher",
        "datastore-user":   "roles/datastore.user",
        "batch-jobs-editor": "roles/batch.jobsEditor",
    };

    Object.entries(apiProjectRoles).forEach(([name, role]) => {
        new gcp.projects.IAMMember(`api-${name}`, {
            project,
            role,
            member: pulumi.interpolate`serviceAccount:${apiServiceAccount.email}`,
        });
    });

    const workerProjectRoles: Record<string, string> = {
        "datastore-user":       "roles/datastore.user",
        "pubsub-publisher":     "roles/pubsub.publisher",
        "logging-writer":       "roles/logging.logWriter",
        "batch-agent-reporter": "roles/batch.agentReporter",
        "artifact-reader":      "roles/artifactregistry.reader",
    };

    Object.entries(workerProjectRoles).forEach(([name, role]) => {
        new gcp.projects.IAMMember(`worker-${name}`, {
            project,
            role,
            member: pulumi.interpolate`serviceAccount:${workerServiceAccount.email}`,
        });
    });

    // -----------------------------------------------------------------
    // Bucket-scoped storage IAM (least privilege)
    // -----------------------------------------------------------------

    // API: full access on uploads (create signed URLs, list blobs),
    //      read-only on outputs (generate download URLs, check existence)
    new gcp.storage.BucketIAMMember("api-uploads-admin", {
        bucket: uploadsBucketName,
        role: "roles/storage.objectAdmin",
        member: pulumi.interpolate`serviceAccount:${apiServiceAccount.email}`,
    });
    new gcp.storage.BucketIAMMember("api-outputs-viewer", {
        bucket: outputsBucketName,
        role: "roles/storage.objectViewer",
        member: pulumi.interpolate`serviceAccount:${apiServiceAccount.email}`,
    });

    // Worker: read-only on uploads (download images),
    //         full access on outputs (upload results)
    new gcp.storage.BucketIAMMember("worker-uploads-viewer", {
        bucket: uploadsBucketName,
        role: "roles/storage.objectViewer",
        member: pulumi.interpolate`serviceAccount:${workerServiceAccount.email}`,
    });
    new gcp.storage.BucketIAMMember("worker-outputs-admin", {
        bucket: outputsBucketName,
        role: "roles/storage.objectAdmin",
        member: pulumi.interpolate`serviceAccount:${workerServiceAccount.email}`,
    });

    // -----------------------------------------------------------------
    // SA-scoped token creator (sign URLs using its own identity only)
    // -----------------------------------------------------------------
    new gcp.serviceaccount.IAMMember("api-self-token-creator", {
        serviceAccountId: apiServiceAccount.name,
        role: "roles/iam.serviceAccountTokenCreator",
        member: pulumi.interpolate`serviceAccount:${apiServiceAccount.email}`,
    });

    // API can act as worker to create Batch jobs
    new gcp.serviceaccount.IAMMember("api-act-as-worker", {
        serviceAccountId: workerServiceAccount.name,
        role: "roles/iam.serviceAccountUser",
        member: pulumi.interpolate`serviceAccount:${apiServiceAccount.email}`,
    });
}
