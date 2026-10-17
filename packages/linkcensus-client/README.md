# LinkCensus REST client

Version 0.1.0 is a standalone Python 3.10+ client and CLI for the versioned
LinkCensus neighborhood API. Runtime dependencies: Python standard library only.
The distribution uses setuptools at build time. This package is unpublished;
installation, production availability and MCP compatibility have not been proved.

The endpoint requires an existing LinkCensus API key with `neighborhoods:read`.
It returns candidates from a dated retained link-neighborhood set. Relatedness
does not prove product competition, market share, coverage or completeness.
The client never crawls a site or calls another provider.

## Python

Read credentials from the environment or an owned private configuration, never
from command arguments. Supply the actual secret through your secret manager.

```python
import os
from linkcensus_client import Client

client = Client(api_key=os.environ["LINKCENSUS_API_KEY"])
result = client.neighbors("example.com", edition="2026-01", limit=5)
```

`neighbors(domain, *, edition=None, limit=5, min_shared=0, tld=None)` performs
exactly one GET to `/api/v1/neighbors/{domain}`. Bounds match the API: limit
1..100, min_shared 0..200, TLD at most 63 characters and edition at most 100.
IDN input becomes punycode; URLs and IP addresses are rejected. Domain public
suffix coverage remains a server decision. Pinning a nonloaded edition returns
409; a successful response with a different edition is rejected by the client.

Results preserve the API's edition, ranking mode, resolution, filters, candidate
explanations, entitlement gate, truncation and quota. The client does not cache
responses or paginate beyond an entitlement. The default limit of five does not
request a full paid result. `total` describes the filtered retained candidate
set, not the web. Shared-linker explanations cover the top 200 retained linkers.

`client.editions()` reads `/api/v1/editions`, returning public manifest metadata
and the loaded edition ID (or null). `client.resolve(domain, edition=None)` reads
`/api/v1/resolve/{domain}` and preserves the edition and resolution reason.
Both metadata reads require the same key/scope and shared rate/capacity
admission, but do not charge monthly lookup units. Uncovered and suppressed
domains have the same `not_covered` resolution; the client cannot distinguish
an opt-out from absent coverage.

## CLI

After a separately validated installation, the console entry point is `linkcensus`:

```sh
linkcensus --version
linkcensus editions --json
linkcensus resolve example.com --edition 2026-01 --json
linkcensus neighbors example.com --edition 2026-01 --limit 5 --json
linkcensus neighbors example.com --tld com --min-shared 2
linkcensus configure
```

`configure` reads `LINKCENSUS_API_KEY`. Alternatively, `configure --key-stdin`
reads an existing secret from stdin. There is no key argument, browser sign-in,
enrollment or key-management API in this package. Default private storage is
`$XDG_CONFIG_HOME/linkcensus/config.json`, or `~/.config/linkcensus/config.json`.
Writes are atomic, with a private directory and owned regular mode-0600 file;
credential-file symlinks are rejected. No project `.env` is discovered or read.
An explicitly supplied environment key bypasses configuration-file reading.
`--config` changes the private file path.

The default origin is `https://linkcensus.com`; `--base-url` accepts an HTTPS
origin without path, userinfo, query or fragment. Explicit `--allow-localhost`
permits HTTP only for 127.0.0.1, ::1 or localhost. HTTP localhost is pinned to
127.0.0.1 so DNS cannot send the development bearer elsewhere. This opt-in is
required on every invocation even when an HTTP origin was saved.

JSON success output is the unchanged API response. Human output labels
candidates, the dated edition, resolution, truncated/gated results and shared
monthly quota. Errors go to stderr; JSON errors have `api_version: "v1"` and an
`error` object containing `code`, `message`, `status` and informational
`retry_after`. Server error bodies are never printed. No request is retried,
including a 429 with Retry-After. Transport exceptions and echoed credentials
are sanitized. Human strings escape terminal controls.

| Exit | Meaning |
| --- | --- |
| 0 | Success |
| 2 | Input/configuration/local I/O error, or server 422 |
| 3 | Authentication/scope failure (401/403) |
| 4 | Quota/rate/capacity limit (429) |
| 5 | Missing endpoint/domain resource (404) or unavailable edition pin (409) |
| 6 | Transport/timeout, redirect, invalid/oversized response or other server failure |

LC currently defines 15 free and 1000 paid monthly account attempts, shared
across keys. The server's returned quota is authoritative; rotation does not
reset it. These are distinct from VerifiedPricing's proposed weighted budgets.
The API is default-off and requires both server switches. This source package
does not prove an available production endpoint, purchase or paid fulfillment.

## Local checks

From this package directory, without installation or a build:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Tests use a bounded local HTTP fixture and synthetic secrets. They do not call
production. `python -m linkcensus_client` supports the same CLI with `src` on the
Python path. The package contains no backend/engine imports, MCP server, remote
OAuth authorization, scheduler or deployment action. A future MCP adapter may
reuse `Client.neighbors`, with its own separately reviewed authorization path.

## Transport limits

The socket timeout defaults to 15 seconds and must be finite, greater than zero
and at most 60. This is a socket-operation timeout, not a total wall-clock
deadline for DNS or a server sending a slow trickle. The response read is capped
at 512 KiB plus one sentinel byte, with no decompression. HTTPS uses standard
certificate validation. Environment proxy settings are ignored; redirects and
cookies are disabled. Linux private-file behavior is tested; other platforms
and Python minor versions need separate acceptance. Clean-install/package-build
smoke, real hosted readback and two MCP-client integrations remain later gates.

| Platform | Python | Evidence |
| --- | --- | --- |
| Linux | 3.12.3 | Source imports, CLI, private files and loopback tests |
| Other supported Python 3.10+ / OS combinations | Not tested | Separate acceptance required |


## Release status

Client source is available at [linkcensus-agent-clients](https://github.com/pucilpet/linkcensus-agent-clients).
This is version 0.1.0 release-candidate source. Package-index publication, a fresh
public-index installation and live API enrollment are still pending. Homepage
and Documentation metadata name intended product destinations; repository
availability alone does not establish that the new API/docs routes are deployed.
