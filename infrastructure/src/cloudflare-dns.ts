/**
 * Cloudflare DNS Configuration
 *
 * Creates DNS A record for the photogrammetry service Load Balancer.
 * Record must be unproxied (DNS Only) for IAP to work correctly.
 */
import * as cloudflare from "@pulumi/cloudflare";
import * as pulumi from "@pulumi/pulumi";

const config = new pulumi.Config();
const zoneId = config.get("cloudflareZoneId");

export function createCloudflareDnsRecord({
    hostname,
    loadBalancerIp,
}: {
    hostname: string;
    loadBalancerIp: pulumi.Output<string>;
}) {
    if (!zoneId) {
        pulumi.log.info(
            "Skipping Cloudflare DNS records: cloudflareZoneId not configured"
        );
        return;
    }

    // Extract subdomain from full hostname
    // e.g., "photogrammetry.courageousland.com" -> "photogrammetry"
    const subdomain = hostname.replace(".courageousland.com", "");

    // A record pointing to the Load Balancer IP
    new cloudflare.DnsRecord(`${subdomain}-a-record`, {
        zoneId,
        name: subdomain,
        type: "A",
        content: loadBalancerIp,
        ttl: 300,
        proxied: false, // Must be unproxied for IAP to work
    });
}
