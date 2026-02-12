/**
 * IAP + Load Balancer Configuration
 *
 * Creates the full HTTPS Load Balancer stack with IAP enabled:
 * 1. Global static IP
 * 2. Serverless NEG -> Backend Service (IAP enabled)
 * 3. URL Map -> HTTPS Proxy -> Forwarding Rule
 * 4. Google-managed SSL certificate
 * 5. HTTP -> HTTPS redirect
 * 6. IAM binding for @courageousland.com
 *
 * IAP uses Google-managed OAuth clients automatically (no manual OAuth
 * client creation needed since the IAP OAuth Admin API was deprecated
 * in July 2025).
 *
 * Architecture:
 * User -> Global LB (static IP)
 *      -> HTTPS Proxy (managed SSL cert)
 *      -> URL Map
 *      -> IAP (auth: @courageousland.com)
 *      -> Backend Service
 *      -> Serverless NEG -> Cloud Run
 */
import * as gcp from "@pulumi/gcp";
import * as pulumi from "@pulumi/pulumi";

export interface IapBackendConfig {
    project: string;
    region: string;
    serviceName: string;
    cloudRunService: gcp.cloudrun.Service;
    /** Hostname for the managed SSL certificate (e.g., photogrammetry.courageousland.com) */
    iapHostname: string;
    environment: string;
}

export interface IapBackendResources {
    backendService: gcp.compute.BackendService;
    backendServiceName: pulumi.Output<string>;
    neg: gcp.compute.RegionNetworkEndpointGroup;
    globalIp: gcp.compute.GlobalAddress;
    ipAddress: pulumi.Output<string>;
}

export function createIapBackend(
    config: IapBackendConfig,
    dependsOn: pulumi.Resource[]
): IapBackendResources {
    const {
        project,
        region,
        serviceName,
        cloudRunService,
        iapHostname,
        environment,
    } = config;

    const cloudArmorPolicy = new gcp.compute.SecurityPolicy(`${serviceName}-armor`, {
        project,
        name: `${serviceName}-armor`,
        description: `Cloud Armor policy for ${serviceName} IAP backend`,
        rules: [
            {
                priority: 1000,
                action: "deny(403)",
                description: "Block known malicious patterns (OWASP CRS stable)",
                match: {
                    expr: {
                        expression: "evaluatePreconfiguredWaf('sqli-stable') || evaluatePreconfiguredWaf('xss-stable')",
                    },
                },
            },
            {
                priority: 2147483647,
                action: "allow",
                description: "Default allow",
                match: {
                    versionedExpr: "SRC_IPS_V1",
                    config: { srcIpRanges: ["*"] },
                },
            },
        ],
    }, { dependsOn });

    // ---------------------------------------------------------------
    // 1. Global static IP
    // ---------------------------------------------------------------
    const globalIp = new gcp.compute.GlobalAddress(`${serviceName}-lb-ip`, {
        project,
        name: `${serviceName}-lb-ip`,
        description: `Static IP for ${serviceName} HTTPS Load Balancer`,
    });

    // ---------------------------------------------------------------
    // 2. Serverless NEG pointing to Cloud Run
    // ---------------------------------------------------------------
    const neg = new gcp.compute.RegionNetworkEndpointGroup(`${serviceName}-neg`, {
        project,
        name: `${serviceName}-neg`,
        region,
        networkEndpointType: "SERVERLESS",
        cloudRun: {
            service: cloudRunService.name,
        },
    }, { dependsOn });

    // ---------------------------------------------------------------
    // 3. Backend Service with IAP enabled
    // ---------------------------------------------------------------
    const backendService = new gcp.compute.BackendService(`${serviceName}-backend`, {
        project,
        name: `${serviceName}-backend`,
        protocol: "HTTP",
        portName: "http",
        backends: [{
            group: neg.id,
        }],
        iap: {
            enabled: true,
        },
        logConfig: {
            enable: true,
            sampleRate: environment === "prod" ? 0.1 : 1.0,
        },
        securityPolicy: cloudArmorPolicy.id,
        description: `Backend for ${serviceName} API (Cloud Run via Serverless NEG, IAP enabled)`,
    }, { dependsOn: [neg, cloudArmorPolicy] });

    // ---------------------------------------------------------------
    // 4. URL Map (with explicit host-based routing)
    // ---------------------------------------------------------------
    const urlMap = new gcp.compute.URLMap(`${serviceName}-url-map`, {
        project,
        name: `${serviceName}-url-map`,
        defaultService: backendService.id,
        hostRules: [{
            hosts: [iapHostname],
            pathMatcher: "pm-photogrammetry",
        }],
        pathMatchers: [{
            name: "pm-photogrammetry",
            defaultService: backendService.id,
        }],
        description: `URL map for ${serviceName} (IAP protected)`,
    });

    // ---------------------------------------------------------------
    // 5. Google-managed SSL certificate
    // ---------------------------------------------------------------
    const sslCert = new gcp.compute.ManagedSslCertificate(`${serviceName}-ssl-cert`, {
        project,
        name: `${serviceName}-ssl-cert`,
        managed: {
            domains: [iapHostname],
        },
    });

    // ---------------------------------------------------------------
    // 6. HTTPS Target Proxy
    // ---------------------------------------------------------------
    const httpsProxy = new gcp.compute.TargetHttpsProxy(`${serviceName}-https-proxy`, {
        project,
        name: `${serviceName}-https-proxy`,
        urlMap: urlMap.id,
        sslCertificates: [sslCert.id],
    });

    // ---------------------------------------------------------------
    // 7. HTTPS Forwarding Rule (port 443)
    // ---------------------------------------------------------------
    new gcp.compute.GlobalForwardingRule(`${serviceName}-https-forwarding`, {
        project,
        name: `${serviceName}-https-forwarding`,
        ipAddress: globalIp.address,
        ipProtocol: "TCP",
        portRange: "443",
        target: httpsProxy.id,
        loadBalancingScheme: "EXTERNAL",
    });

    // ---------------------------------------------------------------
    // 8. HTTP -> HTTPS redirect
    // ---------------------------------------------------------------
    const redirectUrlMap = new gcp.compute.URLMap(`${serviceName}-http-redirect`, {
        project,
        name: `${serviceName}-http-redirect`,
        defaultUrlRedirect: {
            httpsRedirect: true,
            stripQuery: false,
            redirectResponseCode: "MOVED_PERMANENTLY_DEFAULT",
        },
        description: `HTTP to HTTPS redirect for ${serviceName}`,
    });

    const httpProxy = new gcp.compute.TargetHttpProxy(`${serviceName}-http-proxy`, {
        project,
        name: `${serviceName}-http-proxy`,
        urlMap: redirectUrlMap.id,
    });

    new gcp.compute.GlobalForwardingRule(`${serviceName}-http-forwarding`, {
        project,
        name: `${serviceName}-http-forwarding`,
        ipAddress: globalIp.address,
        ipProtocol: "TCP",
        portRange: "80",
        target: httpProxy.id,
        loadBalancingScheme: "EXTERNAL",
    });

    // ---------------------------------------------------------------
    // 9. IAP IAM - Grant access to all @courageousland.com users
    // ---------------------------------------------------------------
    new gcp.iap.WebBackendServiceIamBinding(`${serviceName}-iap-domain-access`, {
        project,
        webBackendService: backendService.name,
        role: "roles/iap.httpsResourceAccessor",
        members: ["domain:courageousland.com"],
    });

    return {
        backendService,
        backendServiceName: backendService.name,
        neg,
        globalIp,
        ipAddress: globalIp.address,
    };
}
