# LinkCensus agent clients - release candidate

Release-candidate source for the LinkCensus REST client/CLI and local
stdio MCP gateway. This export contains only the two client packages, their
source, tests, notices, license and release metadata. It contains no application
server, graph, customer state, deployment configuration or repository history.
The public source repository is [linkcensus-agent-clients](https://github.com/pucilpet/linkcensus-agent-clients). Package-index releases, Registry listing and live API enrollment are still pending.

## Packages

| Package | Version | Purpose |
| --- | --- | --- |
| [linkcensus-client](packages/linkcensus-client/README.md) | 0.1.0 | Standard-library REST client and `linkcensus` CLI |
| [linkcensus-mcp](packages/linkcensus-mcp/README.md) | 0.1.0 | Three read-only stdio tools over the same REST client |

The API must be enabled and your own key issued before live use. Free access is
15 admitted neighborhood attempts per account per UTC calendar month, at most
five candidate rows. REST, CLI and MCP share that counter; rotation does not
reset it. Editions and domain resolution do not spend monthly neighborhood
attempts but still require authentication and execution admission. Candidates
are not independently confirmed competitors; retain edition, provenance,
truncation and quota notes. The website ledger and VerifiedPricing budgets are
separate. No request triggers a crawl or retries automatically.

This is local stdio over HTTPS REST, not a hosted MCP/OAuth service. Linux/Python
3.12 is tested; other source-supported Python 3.10+/POSIX combinations need
acceptance, and Windows is unsupported. See each package's transport limits.

## Candidate installation

Public package-index installation is not available from this release candidate. A placeholder
wheelhouse path below is not evidence of a public package or downloadable bundle.
Use a separately reviewed isolated environment and complete wheelhouse:

```sh
python3 -m venv .venv-linkcensus
.venv-linkcensus/bin/python -m pip install --no-index \
  --find-links /path/to/reviewed-wheelhouse \
  linkcensus-client==0.1.0 linkcensus-mcp==0.1.0 mcp==2.3.0
.venv-linkcensus/bin/linkcensus --version
.venv-linkcensus/bin/linkcensus-mcp --version
```

Provide a key through the private environment or owned regular mode-0600
configuration. Never put it in arguments, public examples or repository files.
`linkcensus configure` saves an already provisioned `LINKCENSUS_API_KEY`; it does
not sign in or issue keys. See [client setup](packages/linkcensus-client/README.md)
and [the secret-free launcher template](examples/mcp-client.template.json).

## Local source checks

No installation or backend is needed for the client package's bounded unit and
loopback tests:

```sh
cd packages/linkcensus-client
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

For gateway checks, use a reviewed separate environment with the exact pinned
SDK and both distributions installed; add the two source directories to its
PYTHONPATH, then run the gateway tests. Tests use synthetic credentials/fixtures,
not production. The initial SDK installation and public-index clean-install
acceptance are separate operations, not test side effects.

## Distribution and security

The Registry manifest is a schema-validated candidate under
`io.github.pucilpet/linkcensus-mcp`. Namespace authentication, PyPI ownership,
publication and Registry readback remain separate gates. Source and issue links point to this public repository; they do not establish
package-index or API availability.

Do not post credentials or private responses. Use [private GitHub vulnerability reporting](https://github.com/pucilpet/linkcensus-agent-clients/security/advisories/new) for security issues. This feature is enabled; no response-time commitment is promised. See the [client policy](packages/linkcensus-client/SECURITY.md)
and [gateway policy](packages/linkcensus-mcp/SECURITY.md).

Both packages retain their existing MIT licenses, copied unchanged to the root.
Original VerifiedPricing and LinkCensus copyright notices are preserved. The
[gateway provenance note](packages/linkcensus-mcp/PROVENANCE.md) records the
licensed transport adaptation; no new copyright attribution is invented.

`EXPORT_ALLOWLIST.json` names every exported file. `EXPORT_MANIFEST.json` binds
all payload files except itself by SHA-256 and byte length; the private review
receipt separately records the manifest's hash. No secret scan establishes that
credentials can never exist: review the exact candidate and artifact before
publication, and retain any reported synthetic-test classification.
