/**
 * Cloud Batch Configuration
 * 
 * Creates Compute Engine Instance Templates for each processing tier.
 * These templates define the VM specs used by Cloud Batch jobs and are
 * referenced by the API service at runtime.
 * 
 * Machine sizing based on:
 * "OpenDroneMap: Multi-Platform Performance Analysis" (Gbagir et al., 2023)
 * https://www.mdpi.com/2673-7086/3/3/23
 */
import * as gcp from "@pulumi/gcp";
import * as pulumi from "@pulumi/pulumi";

export interface BatchConfig {
    project: pulumi.Input<string>;
    region: string;
    serviceName: string;
    workerServiceAccountEmail: pulumi.Input<string>;
}

export interface MachineTier {
    name: string;
    machineType: string;
    cpuMilli: number;
    memoryMib: number;
    diskSizeGb: number;
    maxImages: number;
    description: string;
}

/**
 * Machine tier definitions.
 * Each tier is optimized for a range of image counts based on research findings.
 */
export const MACHINE_TIERS: MachineTier[] = [
    {
        name: "small",
        machineType: "n2-standard-4",
        cpuMilli: 4000,
        memoryMib: 16 * 1024,
        diskSizeGb: 50,
        maxImages: 200,
        description: "Small datasets - up to 200 images (4 vCPU, 16 GB RAM)",
    },
    {
        name: "medium",
        machineType: "n2-standard-8",
        cpuMilli: 8000,
        memoryMib: 32 * 1024,
        diskSizeGb: 100,
        maxImages: 500,
        description: "Medium datasets - up to 500 images (8 vCPU, 32 GB RAM)",
    },
    {
        name: "large",
        machineType: "n2-highmem-8",
        cpuMilli: 8000,
        memoryMib: 64 * 1024,
        diskSizeGb: 200,
        maxImages: 1000,
        description: "Large datasets - up to 1000 images (8 vCPU, 64 GB RAM)",
    },
    {
        name: "xlarge",
        machineType: "n2-highmem-16",
        cpuMilli: 16000,
        memoryMib: 128 * 1024,
        diskSizeGb: 400,
        maxImages: 2000,
        description: "XL datasets - up to 2000 images (16 vCPU, 128 GB RAM)",
    },
    {
        name: "xxlarge",
        machineType: "n2-highmem-32",
        cpuMilli: 32000,
        memoryMib: 256 * 1024,
        diskSizeGb: 800,
        maxImages: 99999,
        description: "XXL datasets - 2000+ images (32 vCPU, 256 GB RAM)",
    },
];

export interface BatchResources {
    /** Map of tier name -> instance template self link */
    templates: Record<string, pulumi.Output<string>>;
    /** Allowed zones for batch jobs (comma-separated) */
    allowedZones: string;
}

export function createBatchTemplates(
    config: BatchConfig,
    dependsOn: pulumi.Resource[]
): BatchResources {
    const { project, region, serviceName, workerServiceAccountEmail } = config;
    const allowedZones = `zones/${region}-a,zones/${region}-b`;

    const templates: Record<string, pulumi.Output<string>> = {};
    const batchNetwork = new gcp.compute.Network(`${serviceName}-batch-network`, {
        project,
        name: `${serviceName}-batch-network`,
        autoCreateSubnetworks: false,
    }, { dependsOn });

    const batchSubnetwork = new gcp.compute.Subnetwork(`${serviceName}-batch-subnet`, {
        project,
        name: `${serviceName}-batch-subnet`,
        region,
        network: batchNetwork.id,
        ipCidrRange: "10.90.0.0/24",
        privateIpGoogleAccess: true,
    }, { dependsOn: [batchNetwork] });

    for (const tier of MACHINE_TIERS) {
        const template = new gcp.compute.InstanceTemplate(`${serviceName}-batch-${tier.name}`, {
            project,
            namePrefix: `${serviceName}-${tier.name}-`,
            machineType: tier.machineType,
            description: tier.description,

            disks: [{
                sourceImage: "projects/cos-cloud/global/images/family/cos-stable",
                autoDelete: true,
                boot: true,
                diskSizeGb: tier.diskSizeGb,
                diskType: "pd-ssd",
            }],

            networkInterfaces: [{
                network: batchNetwork.id,
                subnetwork: batchSubnetwork.id,
            }],

            serviceAccount: {
                email: workerServiceAccountEmail,
                scopes: [
                    "https://www.googleapis.com/auth/devstorage.read_write",
                    "https://www.googleapis.com/auth/datastore",
                    "https://www.googleapis.com/auth/pubsub",
                    "https://www.googleapis.com/auth/logging.write",
                ],
            },

            labels: {
                service: serviceName,
                tier: tier.name,
                "managed-by": "pulumi",
            },

            scheduling: {
                automaticRestart: false,
                preemptible: false,
            },

            metadata: {
                "cos-metrics-enabled": "true",
            },
        }, { dependsOn });

        templates[tier.name] = template.selfLinkUnique;
    }

    return { templates, allowedZones };
}
