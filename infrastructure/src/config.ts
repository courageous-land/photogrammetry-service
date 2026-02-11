import * as pulumi from "@pulumi/pulumi";

export type BatchProvisioningModel = "STANDARD" | "SPOT";

export interface BatchMachineTier {
    maxImages: number;
    machineType: string;
    cpuMilli: number;
    memoryMib: number;
}

export interface RuntimeInfraConfig {
    allowedOrigins: string;
    batchAllowedZones: string[];
    batchMaxRunDuration: string;
    batchMaxRetryCount: number;
    batchProvisioningModel: BatchProvisioningModel;
    batchMachineTiers: BatchMachineTier[];
    batchMinBootDiskMb: number;
    batchDiskSafetyMargin: number;
    batchAvgImageSizeMb: number;
    batchWorkerCommand: string;
    batchLogDestination: string;
    apiMinScale: number;
    apiMaxScale: number;
    cloudRunPublicAccess: boolean;
    enableOperationalAlerts: boolean;
    alertNotificationEmail?: string;
    pubsubBacklogSubscriptions: string[];
}

function parseBatchProvisioningModel(value: string): BatchProvisioningModel {
    const normalized = value.trim().toUpperCase();
    if (normalized === "STANDARD" || normalized === "SPOT") {
        return normalized;
    }
    throw new Error(
        `Invalid batchProvisioningModel '${value}'. Expected STANDARD or SPOT.`,
    );
}

export function loadRuntimeInfraConfig(config: pulumi.Config): RuntimeInfraConfig {
    const environment = config.get("environment") || "dev";
    const defaultApiMinScale = environment === "prod" ? 1 : 0;
    const defaultApiMaxScale = 10;
    const defaultAllowedOrigins = environment === "prod" ? "https://www.courageousland.com" : "*";
    const defaultBatchZones = [
        "southamerica-east1-a",
        "southamerica-east1-b",
    ];

    const batchAllowedZones = config.getObject<string[]>("batchAllowedZones") || defaultBatchZones;
    if (batchAllowedZones.length === 0) {
        throw new Error("batchAllowedZones cannot be empty.");
    }

    const defaultMachineTiers: BatchMachineTier[] = [
        { maxImages: 200,  machineType: "n2-standard-4",  cpuMilli: 4000,  memoryMib: 16384  },
        { maxImages: 500,  machineType: "n2-standard-8",  cpuMilli: 8000,  memoryMib: 32768  },
        { maxImages: 1000, machineType: "n2-highmem-8",   cpuMilli: 8000,  memoryMib: 65536  },
        { maxImages: 2000, machineType: "n2-highmem-16",  cpuMilli: 16000, memoryMib: 131072 },
        { maxImages: 99999, machineType: "n2-highmem-32", cpuMilli: 32000, memoryMib: 262144 },
    ];

    const batchMachineTiers = config.getObject<BatchMachineTier[]>("batchMachineTiers") || defaultMachineTiers;
    if (batchMachineTiers.length === 0) {
        throw new Error("batchMachineTiers must have at least one tier.");
    }

    return {
        allowedOrigins: config.get("allowedOrigins") || defaultAllowedOrigins,
        batchAllowedZones,
        batchMaxRunDuration: config.get("batchMaxRunDuration") || "43200s",
        batchMaxRetryCount: config.getNumber("batchMaxRetryCount") ?? 2,
        batchProvisioningModel: parseBatchProvisioningModel(
            config.get("batchProvisioningModel") || "STANDARD",
        ),
        batchMachineTiers,
        batchMinBootDiskMb: config.getNumber("batchMinBootDiskMb") ?? 51200,
        batchDiskSafetyMargin: config.getNumber("batchDiskSafetyMargin") ?? 1.15,
        batchAvgImageSizeMb: config.getNumber("batchAvgImageSizeMb") ?? 9,
        batchWorkerCommand: config.get("batchWorkerCommand") || "python3,/worker/main.py",
        batchLogDestination: config.get("batchLogDestination") || "CLOUD_LOGGING",
        apiMinScale: config.getNumber("apiMinScale") ?? defaultApiMinScale,
        apiMaxScale: config.getNumber("apiMaxScale") ?? defaultApiMaxScale,
        cloudRunPublicAccess: config.getBoolean("cloudRunPublicAccess") ?? true,
        enableOperationalAlerts: config.getBoolean("enableOperationalAlerts") ?? false,
        alertNotificationEmail: config.get("alertNotificationEmail") || undefined,
        pubsubBacklogSubscriptions: config.getObject<string[]>("pubsubBacklogSubscriptions") || [],
    };
}
