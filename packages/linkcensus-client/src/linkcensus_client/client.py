"""One bounded REST read; no retries, redirects, proxies, cookies or crawling."""

from datetime import datetime
from http.client import HTTPException
import ipaddress
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request

MAX_BODY_BYTES = 512 * 1024
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


class ClientError(Exception):
    def __init__(self, code, message, *, status=None, retry_after=None):
        super().__init__(message)
        self.code, self.message = code, message
        self.status, self.retry_after = status, retry_after

    def as_dict(self):
        return {"code": self.code, "message": self.message,
                "status": self.status, "retry_after": self.retry_after}


def validate_base_url(value, allow_localhost=False):
    if not isinstance(value, str):
        raise ClientError("configuration", "Invalid API origin")
    try:
        parts = urllib.parse.urlsplit(value)
        port = parts.port
        local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
        try:
            ipaddress.ip_address(parts.hostname or "")
            host_valid = True
        except ValueError:
            host_valid = bool(parts.hostname and all(_LABEL.fullmatch(label) for label in parts.hostname.split(".")))
    except ValueError:
        raise ClientError("configuration", "Invalid API origin") from None
    if (not host_valid or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or parts.path not in ("", "/")
            or any(marker in value for marker in ("?", "#", "\\"))
            or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
            or parts.scheme not in {"https", "http"} or port == 0
            or (parts.scheme == "http" and not (allow_localhost and local))):
        raise ClientError("configuration", "Use an HTTPS origin; HTTP requires explicit loopback development mode")
    # Never let a DNS alias named localhost move a development bearer off loopback.
    if parts.scheme == "http" and parts.hostname == "localhost":
        return "http://127.0.0.1" + (":" + str(port) if port is not None else "")
    return value.rstrip("/")


def validate_key(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"lc_live_[A-Za-z0-9_-]{1,248}", value)):
        raise ClientError("configuration", "Invalid LinkCensus API credential format")
    return value


def _domain(value):
    if not isinstance(value, str) or not value or any(ord(c) <= 32 for c in value):
        raise ClientError("input", "Provide a domain without URL, IP address or credentials")
    try:
        value = value.lower().rstrip(".").encode("idna").decode("ascii")
        labels = value.split(".")
        if len(value) > 253 or len(labels) < 2 or any(not _LABEL.fullmatch(label) for label in labels) or labels[-1].isdigit():
            raise ValueError()
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return value
    except (ValueError, UnicodeError):
        pass
    raise ClientError("input", "Provide a domain without URL, IP address or credentials")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _string(value, maximum):
    return isinstance(value, str) and 1 <= len(value) <= maximum


def _integer(value, minimum=0, maximum=None):
    return type(value) is int and value >= minimum and (maximum is None or value <= maximum)


def _edition(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", value)
                              or value.startswith("lc_live_")):
        raise ClientError("input", "Invalid edition pin")
    return value


def _validate_response(payload, limit, edition, domain):
    valid = isinstance(payload, dict)
    if valid:
        valid = (
            payload.get("api_version") == "v1" and payload.get("relationship") == "candidate"
            and _string(payload.get("edition"), 100)
            and payload.get("ranking_mode") in ("embedding", "cocitation")
            and _string(payload.get("query"), 253)
            and payload.get("resolution") in ("exact", "www", "registrable_domain", "not_covered")
            and "resolved_host" in payload
            and (payload["resolved_host"] is None or _string(payload["resolved_host"], 253))
            and _integer(payload.get("total"))
            and type(payload.get("gated")) is bool and type(payload.get("truncated")) is bool
            and payload.get("tier") in ("free", "paid")
            and isinstance(payload.get("filters"), dict)
            and _string(payload.get("selection_reason"), 1024)
            and _string(payload.get("shared_linkers_scope"), 200)
            and isinstance(payload.get("results"), list) and len(payload["results"]) <= limit
            and isinstance(payload.get("quota"), dict)
        )
    if valid:
        quota = payload["quota"]
        valid = (_integer(quota.get("used")) and _integer(quota.get("limit"), 1)
                 and _string(quota.get("resets_at"), 100)
                 and payload["total"] >= len(payload["results"])
                 and payload["truncated"] == (len(payload["results"]) < payload["total"]))
        try:
            valid = valid and datetime.fromisoformat(quota["resets_at"].replace("Z", "+00:00")).utcoffset() is not None
            valid = valid and _domain(payload["query"]) == domain
        except (ValueError, ClientError):
            valid = False
        if payload["resolution"] == "not_covered":
            valid = valid and payload["resolved_host"] is None and payload["total"] == 0
        else:
            valid = valid and payload["resolved_host"] is not None
        for row in payload["results"]:
            valid = valid and isinstance(row, dict)
            if not valid:
                break
            valid = (
                _string(row.get("domain"), 253) and _string(row.get("host"), 253)
                and _integer(row.get("similarity"), 0, 100) and _integer(row.get("shared_linkers"))
                and isinstance(row.get("shared_linker_names"), list) and len(row["shared_linker_names"]) <= 5
                and all(_string(name, 253) for name in row["shared_linker_names"])
                and _string(row.get("tld"), 63) and _string(row.get("rank_band"), 100)
                and row.get("explanation_kind") in ("shared_linkers", "embedding_only")
                and row.get("suppressed") is False
            )
    if not valid or (edition is not None and payload["edition"] != edition):
        raise ClientError("invalid_response", "Unsupported or inconsistent neighborhood response", status=200)


class Client:
    def __init__(self, base_url="https://linkcensus.com", api_key=None, *, allow_localhost=False, timeout=15):
        self.base_url = validate_base_url(base_url, allow_localhost)
        self._key = validate_key(api_key)
        if self._key is None:
            raise ClientError("configuration", "A LinkCensus API key is required")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ClientError("configuration", "Timeout must be greater than zero and at most 60 seconds")
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def neighbors(self, domain, *, edition=None, limit=5, min_shared=0, tld=None):
        domain = _domain(domain)
        if not _integer(limit, 1, 100) or not _integer(min_shared, 0, 200):
            raise ClientError("input", "Limit must be 1..100 and min_shared 0..200")
        _edition(edition)
        if tld is not None and (not isinstance(tld, str) or len(tld) > 63 or not re.fullmatch(r"\.?[A-Za-z0-9-]+", tld)):
            raise ClientError("input", "Invalid TLD filter")
        query = {"limit": limit, "min_shared": min_shared}
        if edition is not None:
            query["edition"] = edition
        if tld is not None:
            query["tld"] = tld
        payload = self._request("/api/v1/neighbors/" + domain, query)
        _validate_response(payload, limit, edition, domain)
        return payload

    def editions(self):
        payload = self._request("/api/v1/editions")
        if (not isinstance(payload, dict) or payload.get("api_version") != "v1"
                or not isinstance(payload.get("editions"), list) or len(payload["editions"]) > 100
                or "loaded_edition" not in payload
                or (payload["loaded_edition"] is not None and not _string(payload["loaded_edition"], 100))
                or any(not isinstance(row, dict) or not _string(row.get("id"), 100) for row in payload["editions"])):
            raise ClientError("invalid_response", "Unsupported edition metadata", status=200)
        return payload

    def resolve(self, domain, *, edition=None):
        domain = _domain(domain)
        _edition(edition)
        payload = self._request("/api/v1/resolve/" + domain, {"edition": edition} if edition is not None else None)
        valid = isinstance(payload, dict)
        if valid:
            valid = (payload.get("api_version") == "v1" and payload.get("relationship") == "candidate"
                     and _string(payload.get("query"), 253) and _string(payload.get("edition"), 100)
                     and _string(payload.get("selection_reason"), 1024)
                     and payload.get("resolution") in ("exact", "www", "registrable_domain", "not_covered")
                     and "resolved_host" in payload
                     and (payload["resolved_host"] is None if payload.get("resolution") == "not_covered"
                          else _string(payload["resolved_host"], 253)))
        try:
            valid = valid and _domain(payload["query"]) == domain and (edition is None or payload["edition"] == edition)
        except ClientError:
            valid = False
        if not valid:
            raise ClientError("invalid_response", "Unsupported domain resolution", status=200)
        return payload

    def _request(self, path, query=None):
        request = urllib.request.Request(
            self.base_url + path + ("?" + urllib.parse.urlencode(query) if query else ""),
            headers={"Accept": "application/json", "Accept-Encoding": "identity",
                     "Authorization": "Bearer " + self._key, "User-Agent": "linkcensus-client/0.1.0"},
            method="GET",
        )
        try:
            response = self._opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            response = exc
        except (OSError, urllib.error.URLError, HTTPException, ValueError):
            raise ClientError("transport", "API connection failed or timed out") from None
        with response:
            status = response.status
            try:
                raw = response.read(MAX_BODY_BYTES + 1)
            except (OSError, HTTPException, ValueError):
                raise ClientError("transport", "API response failed or timed out") from None
            retry = response.headers.get("Retry-After")
            if retry is not None and (len(retry) > 80 or any(ord(c) < 32 or ord(c) >= 127 for c in retry) or self._key in retry):
                retry = None
            if len(raw) > MAX_BODY_BYTES:
                raise ClientError("response_too_large", "API response exceeds the client size limit", status=status)
            try:
                def invalid_constant(value):
                    raise ValueError()
                payload = json.loads(raw, parse_constant=invalid_constant)
            except (ValueError, UnicodeError, RecursionError):
                payload = None
            if status != 200:
                detail = payload.get("detail") if isinstance(payload, dict) else None
                code = detail.get("code") if isinstance(detail, dict) else None
                if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code) or self._key in code:
                    code = "rate_limited" if status == 429 else "http_error"
                message = ("API redirect refused" if 300 <= status < 400 else
                           "API authentication failed" if status in (401, 403) else
                           "API request limited" if status == 429 else
                           "Requested edition is not loaded" if status == 409 else "API request failed")
                raise ClientError(code, message, status=status, retry_after=retry)
            pending = [payload]
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    pending.extend(value.keys())
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
                elif isinstance(value, str) and self._key in value:
                    raise ClientError("invalid_response", "API response contains credential material", status=status)
            return payload
