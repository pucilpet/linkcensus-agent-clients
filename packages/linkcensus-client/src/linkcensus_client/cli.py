"""CLI for dated candidate neighborhoods; credentials never appear in arguments."""

import argparse
import json
import os
from pathlib import Path
import sys

from . import __version__, config
from .client import Client, ClientError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ClientError("input", "Invalid arguments; use --help for usage")


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--base-url", default=argparse.SUPPRESS, help="HTTPS API origin")
    common.add_argument("--config", type=Path, default=argparse.SUPPRESS, help="Private configuration file")
    common.add_argument("--allow-localhost", action="store_true", default=argparse.SUPPRESS, help="Explicit HTTP loopback development mode")
    common.add_argument("--timeout", type=float, default=argparse.SUPPRESS, help="Socket timeout, 0 < seconds <= 60")
    root = Parser(prog="linkcensus", parents=[common], description="Dated link-neighborhood candidates, not proven competitors.")
    root.add_argument("--version", action="version", version="%(prog)s " + __version__)
    commands = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    neighbors = commands.add_parser("neighbors", parents=[common])
    neighbors.add_argument("domain")
    neighbors.add_argument("--edition", help="Require this loaded edition ID; mismatch fails")
    neighbors.add_argument("--limit", type=int, default=5, help="Requested cap, 1..100; entitlement still applies")
    neighbors.add_argument("--min-shared", type=int, default=0, help="Minimum shared retained linkers, 0..200")
    neighbors.add_argument("--tld", help="Optional TLD filter")
    commands.add_parser("editions", parents=[common], help="Read public edition metadata")
    resolve = commands.add_parser("resolve", parents=[common], help="Resolve a domain in the loaded edition")
    resolve.add_argument("domain")
    resolve.add_argument("--edition", help="Require this loaded edition ID")
    configure = commands.add_parser("configure", parents=[common])
    configure.add_argument("--key-stdin", action="store_true", help="Read an existing LC key from stdin; otherwise use LINKCENSUS_API_KEY")
    return root


def human(payload):
    def display(value):
        return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False)
    if "editions" in payload:
        lines = ["Loaded edition: " + display(payload["loaded_edition"])]
        lines.extend("Edition metadata: " + display(row) for row in payload["editions"])
        lines.append("Metadata read; account rate and capacity limits still apply.")
        return "\n".join(lines)
    if "results" not in payload:
        return ("Candidate resolution - not proof of competition\n"
                + "Dated edition: " + display(payload["edition"]) + "\n"
                + "Query: " + display(payload["query"]) + " | resolved host: " + display(payload["resolved_host"])
                + " | resolution: " + display(payload["resolution"]) + "\n"
                + "Selection: " + display(payload["selection_reason"]))
    lines = [
        "Candidate neighbors - not proven competitors",
        "Dated edition: " + display(payload["edition"]) + " | mode: " + display(payload["ranking_mode"]),
        "Query: " + display(payload["query"]) + " | resolved host: " + display(payload["resolved_host"])
        + " | resolution: " + display(payload["resolution"]),
        "Retained candidate set: " + str(payload["total"]) + " | returned: " + str(len(payload["results"]))
        + " | truncated: " + display(payload["truncated"]) + " | entitlement gated: " + display(payload["gated"]),
        "Selection: " + display(payload["selection_reason"]),
        "Shared linkers: " + display(payload["shared_linkers_scope"]),
    ]
    for row in payload["results"]:
        lines.append(display(row["domain"]) + " | similarity: " + str(row["similarity"])
                     + " | shared linkers: " + str(row["shared_linkers"]) + " | explanation: " + display(row["explanation_kind"]))
        lines.append("  Retained linker examples: " + display(row["shared_linker_names"]))
    if not payload["results"]:
        lines.append("No visible candidates; absence does not establish that competitors do not exist.")
    quota = payload["quota"]
    lines.append("Shared account monthly quota: " + str(quota["used"]) + "/" + str(quota["limit"])
                 + " | resets: " + display(quota["resets_at"]) + " | tier: " + display(payload["tier"]))
    return "\n".join(lines)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in argv
    try:
        args = parser().parse_args(argv)
        json_output = getattr(args, "json", False)
        path = getattr(args, "config", None) or config.default_path()
        env_key = os.environ.get("LINKCENSUS_API_KEY")
        saved = {} if env_key is not None or args.command == "configure" else config.load(path)
        base = getattr(args, "base_url", None) or saved.get("base_url", "https://linkcensus.com")
        local = getattr(args, "allow_localhost", False)
        if args.command == "configure":
            key = sys.stdin.read(258).strip() if args.key_stdin else env_key
            if not key:
                raise ClientError("configuration", "Provide an existing LC key through stdin or LINKCENSUS_API_KEY")
            config.save(path, api_key=key, base_url=base, allow_localhost=local)
            payload = {"api_version": "v1", "configured": True}
        else:
            client = Client(base, env_key if env_key is not None else saved.get("api_key"),
                            allow_localhost=local, timeout=getattr(args, "timeout", 15))
            if args.command == "editions":
                payload = client.editions()
            elif args.command == "resolve":
                payload = client.resolve(args.domain, edition=args.edition)
            else:
                payload = client.neighbors(args.domain, edition=args.edition, limit=args.limit,
                                           min_shared=args.min_shared, tld=args.tld)
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True, allow_nan=False) if json_output
              else "Saved private LinkCensus configuration." if args.command == "configure" else human(payload))
        return 0
    except (OSError, ClientError) as exc:
        if not isinstance(exc, ClientError):
            exc = ClientError("local_io", "Local configuration or network I/O failed")
        if json_output:
            print(json.dumps({"api_version": "v1", "error": exc.as_dict()}, sort_keys=True), file=sys.stderr)
        else:
            suffix = " (Retry-After: " + exc.retry_after + ")" if exc.retry_after else ""
            print(exc.message + suffix, file=sys.stderr)
        return (2 if exc.code in {"input", "configuration", "local_io"} or exc.status == 422 else
                3 if exc.status in (401, 403) else 4 if exc.status == 429 else
                5 if exc.status in (404, 409) else 6)
