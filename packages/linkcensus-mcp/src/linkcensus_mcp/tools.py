"""Three fixed read tools; dated neighbors remain candidates, never proven competitors."""

import json
import re

from linkcensus_client import ClientError
from linkcensus_client.cli import human

from .runner import Busy, DeadlineExceeded

MAX_TEXT_BYTES = 8192
MAX_TOOL_BYTES = 640 * 1024


def schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}


DOMAIN = {"type": "string", "minLength": 3, "maxLength": 253,
          "description": "Domain only, no URL or IP; IDNA normalization occurs in the client"}
EDITION = {"type": "string", "minLength": 1, "maxLength": 100,
           "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$", "description": "Explicit loaded edition pin; mismatch fails"}
TOOLS = {
    "list_editions": ("Read public dated Common Crawl edition metadata; not a crawl or completeness guarantee.", schema()),
    "resolve_domain": ("Resolve a domain within a dated loaded edition. Resolution is not proof of product competition.",
                       schema({"domain": DOMAIN, "edition": EDITION}, ("domain",))),
    "get_neighbor_candidates": ("Read related-domain candidates, not confirmed competitors. Preserve dated edition, mode, retained-linker scope, truncation, entitlement and shared quota.",
                                schema({"domain": DOMAIN, "edition": EDITION,
                                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 5},
                                        "min_shared": {"type": "integer", "minimum": 0, "maximum": 200, "default": 0},
                                        "tld": {"type": "string", "minLength": 1, "maxLength": 63, "pattern": "^\\.?[A-Za-z0-9-]+$"}},
                                       ("domain",))),
}


class InvalidInput(Exception):
    pass


def validate(value, rule):
    kind = rule["type"]
    if kind == "object":
        if not isinstance(value, dict) or set(value) - rule["properties"].keys() or set(rule["required"]) - value.keys():
            raise InvalidInput()
        for name, item in value.items():
            validate(item, rule["properties"][name])
    elif kind == "string":
        if not isinstance(value, str) or any(ord(c) < 32 for c in value):
            raise InvalidInput()
        if not rule.get("minLength", 0) <= len(value) <= rule.get("maxLength", 128):
            raise InvalidInput()
        if "pattern" in rule and not re.fullmatch(rule["pattern"], value):
            raise InvalidInput()
    elif kind == "integer":
        if type(value) is not int or not rule["minimum"] <= value <= rule["maximum"]:
            raise InvalidInput()


def operation(client, name, arguments):
    if name not in TOOLS:
        raise InvalidInput()
    validate(arguments, TOOLS[name][1])
    if name == "list_editions":
        return client.editions
    if name == "resolve_domain":
        return lambda: client.resolve(arguments["domain"], edition=arguments.get("edition"))
    return lambda: client.neighbors(arguments["domain"], edition=arguments.get("edition"),
                                    limit=arguments.get("limit", 5), min_shared=arguments.get("min_shared", 0),
                                    tld=arguments.get("tld"))


def safe_error(code, message, *, status=None, retry_after=None):
    return {"api_version": "v1", "error": {"code": code, "message": message, "status": status, "retry_after": retry_after}}


async def execute(client, runner, name, arguments):
    try:
        action = operation(client, name, arguments)
        payload = await runner.run(action)
        text = ("Dated Common Crawl link-neighborhood evidence. Related domains are candidates, not confirmed competitors. Retained search sets are not the whole web.\n"
                + human(payload))
        text_bytes = text.encode("utf-8")
        if len(text_bytes) > MAX_TEXT_BYTES:
            text = text_bytes[:MAX_TEXT_BYTES - 96].decode("utf-8", errors="ignore") + "\nText truncated; full qualifications remain in structuredContent."
        bounded_json({"content": [{"type": "text", "text": text}], "structuredContent": payload}, MAX_TOOL_BYTES)
        return payload, text, False
    except InvalidInput:
        error = safe_error("invalid_input", "Unknown tool or invalid bounded arguments")
    except ClientError as exc:
        error = {"api_version": "v1", "error": exc.as_dict()}
    except Busy:
        error = safe_error("busy", "An earlier REST operation is still running; no new request was issued")
    except DeadlineExceeded:
        error = safe_error("deadline_exceeded", "Response deadline exceeded; the actual REST operation retains its permit until finished")
    except Exception:
        error = safe_error("operation_failed", "Candidate lookup failed safely")
    return error, error["error"]["message"], True


def bounded_json(value, maximum):
    output = bytearray()
    for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":")).iterencode(value):
        encoded = chunk.encode("utf-8")
        if len(output) + len(encoded) > maximum:
            raise ValueError("Serialized response exceeds bound")
        output.extend(encoded)
    return bytes(output)
