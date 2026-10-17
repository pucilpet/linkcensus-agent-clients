# Security reporting

Report vulnerabilities privately through [GitHub security advisories](https://github.com/pucilpet/linkcensus-agent-clients/security/advisories/new). Private vulnerability reporting is enabled for this repository. Include the package/SDK version, platform and a minimal reproduction using synthetic credentials. Do not post real keys, private configuration or account data in public issues. No response-time commitment is promised.

The client ignores environment proxies, rejects redirects, requires explicit
HTTP loopback development mode, and never accepts a key argument. Configuration
must be an owned regular mode-0600 file. HTTP errors, transport exceptions and
decoded success responses cannot echo the supplied credential to CLI output.
This REST key client is not a remote MCP OAuth or interactive sign-in flow.
