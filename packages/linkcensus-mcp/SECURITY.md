# Security reporting

Report vulnerabilities privately through [GitHub security advisories](https://github.com/pucilpet/linkcensus-agent-clients/security/advisories/new). Private vulnerability reporting is enabled for this repository. Include the package/SDK version, platform and a minimal reproduction using synthetic credentials. Do not post real keys, private configuration or account data in public issues. No response-time commitment is promised.

Boundaries include pre-SDK byte framing, request/notification fanout, output
backpressure, actual-thread permits through cancellation, audience-separated
private credentials and candidate/edition/quota truth. SDK logging/telemetry is
disabled in the launcher. Tools cannot execute commands, crawl or administer the
service. No remote MCP credential is passed upstream as an LC key.

Hosted OAuth and production service activation are outside this local gateway.
