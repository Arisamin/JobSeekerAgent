# SaaS / VM Hosting Options (Job Seeker Agent)

Objective: host the agent as a long-running service with browser automation reliability, acceptable cost, and easy operations.

Notes:
- Prices are indicative monthly ranges as of 2026 and should be rechecked before purchase.
- Browser automation with persistent profile is usually more stable on full VMs than on strict serverless platforms.

## Quick comparison

| Option | Typical price (entry) | Reputation | Pros | Cons | Best for |
|---|---:|---|---|---|---|
| Hetzner Cloud CX22/CX32 | ~$6 to $12 | Strong among developers, high value-for-money | Very low price, good performance per dollar, easy scaling | Fewer global regions than hyperscalers | Cost-efficient always-on bot |
| DigitalOcean Basic Droplet | ~$6 to $12 | Very good SMB/devops reputation | Simple UX, predictable billing, lots of tutorials | Slightly pricier than Hetzner for similar specs | Fast setup, low ops overhead |
| Linode (Akamai) Shared CPU | ~$5 to $12 | Long-standing, stable | Straightforward pricing, decent docs/support | Fewer managed ecosystem features than AWS/Azure | Budget VM with simple stack |
| AWS Lightsail | ~$5 to $12+ | Enterprise-grade reputation | Easy entry to AWS ecosystem, snapshots, networking | Costs can grow if unmanaged; pricing complexity beyond base | Teams already using AWS |
| Azure B1s/B2s VM | ~$8 to $20+ | Enterprise-grade reputation | Good for Microsoft-centric stack and identity integration | Cost and setup complexity can be higher | Windows-centric enterprise workflows |
| GCP e2-micro/e2-small | low to moderate | Enterprise-grade reputation | Good networking, solid cloud tooling | Billing model less beginner-friendly than DO/Hetzner | GCP-native teams |
| Oracle Cloud Always Free + paid upgrade path | Free tier available | Mixed but widely used | Can run very low-cost prototypes | Capacity limits/availability variability by region | Experimenting with minimal budget |

## Recommended shortlist for this project

## 1) Hetzner Cloud (best cost/performance)

Why:
- Lowest practical monthly cost for persistent Playwright + Python bot.
- Good enough CPU/RAM for headless Chromium and Telegram polling.

Suggested starter spec:
- 2 vCPU, 4 GB RAM, 40+ GB SSD

## 2) DigitalOcean (best ease-of-use)

Why:
- Easiest onboarding and operational simplicity.
- Good docs for systemd, reverse proxy, monitoring basics.

Suggested starter spec:
- Basic shared CPU, 2 GB RAM minimum (4 GB preferred for browser reliability)

## 3) AWS Lightsail (best if you want AWS alignment)

Why:
- Easy VM while preserving AWS migration path.
- Works well when you eventually need IAM, CloudWatch, S3 backups.

Suggested starter spec:
- Linux instance in ~$5-$10 range, monitor memory pressure closely.

## Architecture recommendation

For this agent, prefer VM-based deployment over pure serverless.

Baseline architecture:
1. Ubuntu VM
2. Python venv + Playwright + Chromium dependencies
3. systemd service for agent process
4. Optional lightweight API endpoint for health checks
5. Log rotation + daily DB backup

## Security and operations checklist

1. Use secrets in environment variables (never hardcode Telegram token).
2. Restrict SSH by IP where possible.
3. Enable firewall (allow only SSH + optional HTTPS).
4. Configure automatic security updates.
5. Use process supervisor (`systemd`) with restart policy.
6. Back up `processed_jobs.db` daily.
7. Keep `.playwright_profile` on persistent disk.

## Deployment complexity by option

- Lowest complexity: DigitalOcean
- Lowest cost: Hetzner
- Highest enterprise integration: AWS/Azure/GCP

## Suggested decision path

1. Start on Hetzner or DigitalOcean.
2. Run for 2-4 weeks and measure:
   - uptime,
   - successful applies,
   - memory/CPU under scan+apply load,
   - operational friction.
3. If enterprise controls are needed later, migrate to Lightsail/Azure with same service model.
