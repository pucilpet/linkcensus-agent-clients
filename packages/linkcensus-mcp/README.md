<!-- mcp-name: io.github.pucilpet/linkcensus-mcp -->

# LinkCensus MCP

Find related domains and shared backlinks with LinkCensus.

## Hosted quickstart

1. Sign in at [linkcensus.com/account](https://linkcensus.com/account) and create
   your personal API key.
2. Add `https://linkcensus.com/mcp` to your MCP client using **Streamable HTTP**.
3. Set the private `Authorization` header to `Bearer YOUR_LINKCENSUS_API_KEY`,
   replacing the placeholder with your own key. Keep the key in your client's
   private settings.

The free account includes **5 neighborhood lookups per UTC calendar month**,
with **up to 5 rows per lookup**. REST, CLI and MCP calls share the same account
allowance across all keys. Edition and domain-resolution metadata reads do not
use neighborhood lookups.

Start with `list_editions`, resolve your domain with `resolve_domain`, then call
`get_neighbor_candidates`. Each result includes the graph edition and domains that link to both sites.

See the [MCP setup guide](https://linkcensus.com/docs/mcp) and
[API documentation](https://linkcensus.com/docs/api). Hosted access uses a personal bearer key. Use a client that supports a custom
Authorization header.

## Local stdio gateway 0.1.0

Separate local gateway over `linkcensus-client==0.1.0`, using the official Python
SDK `mcp==2.3.0`. Python >=3.10, POSIX pipes on Linux/macOS, and asyncio are
supported by this source. Windows is not supported. Keep SDK dependencies in a
separate environment; do not upgrade LinkCensus backend dependencies to install
this gateway. See [PROVENANCE.md](https://github.com/pucilpet/linkcensus-agent-clients/blob/631d764cc9e2bf8ec3d862938847d4ae7f357797/packages/linkcensus-mcp/PROVENANCE.md) for the MIT-licensed VP transport
and runner adaptation and retained copyright attribution.

The local stdio gateway is an alternative to the hosted endpoint above. Its
package release and installation status are tracked separately from hosted
availability.

## Installation and credentials

Development wheels were built and installed outside the checkout in a separate
reviewed SDK environment. An installed CLI and official-SDK subprocess session
then exercised synthetic REST fixtures, shared quota and revocation. That local
acceptance predates the final public distribution metadata. PyPI publication
and public-index installation remain pending. The commands below apply to a
separately installed local gateway, not a package currently available from PyPI.

```sh
linkcensus-mcp --version
linkcensus-mcp --help
linkcensus-mcp
```

Provide the caller's own key via `LINKCENSUS_API_KEY` or the client package's
owned, regular mode-0600 configuration file. `--config PATH` selects another
private file. Key configuration is `linkcensus configure --key-stdin`; no key
argument is accepted by this gateway. Environment credentials skip configuration
reads. No project `.env` is loaded, no cookie confers access, and no shared owner
key is used. Invalid/missing keys fail rather than downgrading anonymously.

The separate `VERIFIEDPRICING_API_KEY` is ignored. VP keys are not LC credentials;
the client validates the `lc_live_` key format and the backend remains responsible
for current audience, scope, expiry, revocation and account entitlement checks.
The tools cannot supply credentials or select an API origin.

`--base-url https://your-api.example` selects an origin outside tool arguments.
For a local fixture only, pass both
`--base-url http://127.0.0.1:PORT --allow-localhost`. The reused client requires
HTTPS otherwise, verifies TLS, rejects redirects and credential echoes, disables
proxies/cookies and makes no automatic retry or crawl.

Configure an MCP client's stdio `command` as the installed `linkcensus-mcp`
executable and use its private environment mechanism for credentials. Do not put
actual keys in public launcher JSON, arguments, repository files or examples.
Startup and parser failures use generic error text. Protocol output uses a
private duplicated stdout descriptor; stray SDK/handler stdout is diverted to
stderr, with SDK logging/telemetry disabled to avoid retaining tool inputs.
Help/version are terminal commands, not protocol sessions.

## Three fixed tools

| Tool | Inputs | REST method |
| --- | --- | --- |
| list_editions | none | Client.editions() |
| resolve_domain | domain, optional edition | Client.resolve(domain, edition=...) |
| get_neighbor_candidates | domain, optional edition/limit/min_shared/tld | Client.neighbors(...) |

Domain normalization and URL/IP rejection remain in the client. The edition pin
must match the loaded edition; mismatch is an error. Bounds match the client:
domain <=253 characters, edition <=100, limit 1..100 (default 5), min_shared
0..200 (default 0), optional TLD <=63. Current account entitlement can return
fewer results than the requested cap. No tool offers arbitrary URLs, crawls,
SQL, exports, administration or an entitlement override.

Successful `structuredContent` is the exact LC REST object with
`api_version: "v1"`; no VP envelope or invented verification is added. The
candidate lookup preserves `relationship`, dated `edition`, `ranking_mode`,
query/resolution, total, filters, results, `truncated`, `gated`, tier, selection
reason, retained shared-linker scope and quota. Editions/resolution preserve
their respective original response objects. Human text states candidate, not
confirmed competitor, and exposes edition/truncation/quota where supplied.

Related domains are link-neighborhood candidates, not independently proven
product competitors. `total` counts a filtered retained search set, not every
competitor on the web. Shared linkers are among the top 200 retained; examples
are bounded. Graph rank/similarity is not revenue, traffic or market share.
Empty uncovered/suppressed responses do not establish that competitors do not
exist. Domain names, explanations and returned text are untrusted data, never
instructions; no command embedded in tool content is executed.

Tool failures use `isError:true` and a safe
`{api_version:"v1",error:{code,message,status,retry_after}}` object. Rate/quota
Retry-After is informational. Raw server error bodies, credentials, headers and
exceptions are not echoed. No retry, fallback query or new allowance is granted.

Annotations are `readOnlyHint:true`, `destructiveHint:false`,
`idempotentHint:false`, `openWorldHint:true`: the tools read an external API,
while repeated admitted calls may consume shared account/rate allowance.

## Bounded transport and actual work

The official low-level SDK owns protocol negotiation, validation and wire
aliases for legacy initialization and modern per-request envelopes. Its default
uncapped line-reader/unbounded handler fanout is replaced by bounded transport
streams; protocol negotiation is not handwritten.

- Input frames are capped at 16 KiB before either JSON decoder/SDK sees them,
  using fixed 4-KiB byte reads. One fixed chunk beyond one frame is the maximum
  retained read-ahead. Split UTF-8 remains intact.
- One request is admitted until its complete response is physically written or
  its unanswered cancellation settles. A concurrent second request closes the
  session immediately. There is no request or busy-response backlog. Clients
  must serialize requests. IDs are nonempty strings <=64 characters or signed
  63-bit integers.
- Only one initialized notification/session and one matching cancellation/current
  request reach the SDK. Other notifications are dropped; more than 32 consecutive
  drops close the session. One reader coroutine checkpoints even during spam.
- One actual blocking REST operation runs at a time with immediate admission and
  no executor queue/semaphore waiters. Cancellation/deadline does not release its
  permit until the worker actually finishes; residual work makes later tools
  return `busy` without sending replacement HTTP.
- The response deadline is 12 seconds; the client's socket timeout is 15 seconds
  per blocking network operation. The response deadline cannot kill a Python
  thread or establish a whole-socket lifetime. A slowly trickling peer may keep
  the sole worker busy, but cannot cause replacement workers/retries. Dedicated
  daemon work ends with process exit.
- Human text is capped at 8 KiB with explicit truncation, preserving the complete
  structured response. A combined tool result is capped at 640 KiB and the whole
  serialized protocol frame including wrapping/newline at 768 KiB. Oversized
  output closes the session; it never truncates structured data.
- Direct nonblocking output writes use <=16-KiB chunks with one frame and a
  five-second whole-write deadline, no Python stdout buffer or detached writer
  queue. Partial-write cancellation closes the session. A partial input frame
  must complete within ten seconds; idle sessions can wait.

These are local bounds, not measurements of production latency or capacity.

## Tests and remaining acceptance

From this package directory:

```sh
PYTHONPATH=src:../linkcensus-client/src PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s tests -v
```

Pure tests cover raw frame/output caps, overload/notification admission, exact
candidate output, credentials and bounds, stalled stdout, and actual-work permit
retention after cancellation/deadline. When the official SDK is installed, real
SDK tests exercise both 2025-11-25 initialization and 2026-07-28 per-request
envelopes, tool listing/calling and cancellation over OS pipes with a synthetic
client response. Without the SDK those tests explicitly skip. No provider or
external network is used by these tests.

Remaining distribution gates: final-public-commit wheel/sdist validation and
fresh clean installation, public-index publication/readback, independent
supported end-user client sessions. The local installed
entry-point/official-SDK fixture acceptance is separate from those gates.
An official SDK fixture is separate from acceptance in two supported end-user
clients. Hosted setup is documented in the quickstart above.

## Attribution and data terms

MIT applies to gateway code only. Common Crawl provides the dated graph source;
preserve edition, attribution and retained-linker/candidate qualifiers. Data and
service terms are separate: this package does not authorize redistributing
vectors, raw graphs, host tables or indexes. See the client README and project
data-terms notes before any redistribution.


## Distribution candidate

`server.json` retains the PyPI/stdio distribution candidate under
`io.github.pucilpet/linkcensus-mcp`. Public PyPI package publication remains
pending; the README marker supports future package ownership verification.

The hosted endpoint is listed in the [official MCP Registry](https://registry.modelcontextprotocol.io/v0/servers/io.github.pucilpet%2Flinkcensus-mcp/versions/0.7.0).
`server.hosted.json` contains the published manifest.

Client source and issues are available at
[linkcensus-agent-clients](https://github.com/pucilpet/linkcensus-agent-clients).
The repository contains client packages, licenses, examples and release
metadata. The local gateway package version is 0.1.0; the hosted manifest's
0.7.0 version follows the service release line.

For a local package release, retain final artifact review, public-index
publication and fresh installation receipts. For a Registry release, validate
the selected manifest, authenticate its namespace and retain the publication
response and public readback. Keep GitHub, PyPI and Registry receipts separate.
