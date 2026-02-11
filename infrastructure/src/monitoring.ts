import * as gcp from "@pulumi/gcp";
import * as pulumi from "@pulumi/pulumi";

export interface MonitoringConfig {
    project: pulumi.Input<string>;
    region: string;
    serviceName: string;
    enableOperationalAlerts: boolean;
    alertNotificationEmail?: string;
    pubsubBacklogSubscriptions: string[];
}

export function createOperationalMonitoring(config: MonitoringConfig): void {
    const {
        project,
        region,
        serviceName,
        enableOperationalAlerts,
        alertNotificationEmail,
        pubsubBacklogSubscriptions,
    } = config;

    if (!enableOperationalAlerts) {
        return;
    }

    const notificationChannels: pulumi.Input<string>[] = [];
    if (alertNotificationEmail) {
        const emailChannel = new gcp.monitoring.NotificationChannel(`${serviceName}-ops-email`, {
            project,
            displayName: `${serviceName} operations`,
            type: "email",
            labels: {
                email_address: alertNotificationEmail,
            },
        });
        notificationChannels.push(emailChannel.id);
    }

    new gcp.monitoring.AlertPolicy(`${serviceName}-run-5xx`, {
        project,
        displayName: `${serviceName} Cloud Run 5xx`,
        combiner: "OR",
        enabled: true,
        severity: "ERROR",
        notificationChannels,
        conditions: [{
            displayName: "Cloud Run 5xx count",
            conditionThreshold: {
                comparison: "COMPARISON_GT",
                duration: "300s",
                thresholdValue: 5,
                filter:
                    `resource.type = "cloud_run_revision" AND ` +
                    `resource.label.service_name = "${serviceName}-api" AND ` +
                    `resource.label.location = "${region}" AND ` +
                    `metric.type = "run.googleapis.com/request_count" AND ` +
                    `metric.label.response_code_class = "5xx"`,
                aggregations: [{
                    alignmentPeriod: "60s",
                    perSeriesAligner: "ALIGN_RATE",
                }],
                trigger: {
                    count: 1,
                },
            },
        }],
    });

    new gcp.monitoring.AlertPolicy(`${serviceName}-run-latency-p95`, {
        project,
        displayName: `${serviceName} Cloud Run high latency`,
        combiner: "OR",
        enabled: true,
        severity: "WARNING",
        notificationChannels,
        conditions: [{
            displayName: "Cloud Run p95 latency",
            conditionThreshold: {
                comparison: "COMPARISON_GT",
                duration: "300s",
                thresholdValue: 5,
                filter:
                    `resource.type = "cloud_run_revision" AND ` +
                    `resource.label.service_name = "${serviceName}-api" AND ` +
                    `resource.label.location = "${region}" AND ` +
                    `metric.type = "run.googleapis.com/request_latencies"`,
                aggregations: [{
                    alignmentPeriod: "60s",
                    perSeriesAligner: "ALIGN_PERCENTILE_95",
                }],
                trigger: {
                    count: 1,
                },
            },
        }],
    });

    new gcp.monitoring.AlertPolicy(`${serviceName}-batch-errors`, {
        project,
        displayName: `${serviceName} Batch errors`,
        combiner: "OR",
        enabled: true,
        severity: "ERROR",
        notificationChannels,
        conditions: [{
            displayName: "Batch error logs",
            conditionMatchedLog: {
                filter:
                    `resource.type = "batch_job" AND ` +
                    `resource.label.location = "${region}" AND ` +
                    `(severity >= ERROR OR textPayload : "FAILED")`,
            },
        }],
    });

    pubsubBacklogSubscriptions.forEach((subscription, index) => {
        new gcp.monitoring.AlertPolicy(`${serviceName}-pubsub-backlog-${index}`, {
            project,
            displayName: `${serviceName} Pub/Sub backlog ${subscription}`,
            combiner: "OR",
            enabled: true,
            severity: "WARNING",
            notificationChannels,
            conditions: [{
                displayName: `Backlog in ${subscription}`,
                conditionThreshold: {
                    comparison: "COMPARISON_GT",
                    duration: "300s",
                    thresholdValue: 100,
                    filter:
                        `resource.type = "pubsub_subscription" AND ` +
                        `resource.label.subscription_id = "${subscription}" AND ` +
                        `metric.type = "pubsub.googleapis.com/subscription/num_undelivered_messages"`,
                    aggregations: [{
                        alignmentPeriod: "60s",
                        perSeriesAligner: "ALIGN_MEAN",
                    }],
                    trigger: {
                        count: 1,
                    },
                },
            }],
        });
    });
}
