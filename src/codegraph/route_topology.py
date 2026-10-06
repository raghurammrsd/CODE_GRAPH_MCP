"""Universal Parameterized Route Topology and Cross-Language Route Matching.

Bridges frontend fetch/axios/SWR/React-Query client calls with backend route declarations
across disparate frameworks (React, Next.js, Express, NestJS, Flask, FastAPI, Django).

Supported Syntax Conventions:
- JavaScript/TypeScript: `${param}`, `:param`, `[param]`, `[...slug]`
- Python Flask: `<param>`, `<int:param>`, `<path:param>`, `<uuid:param>`
- Python FastAPI: `{param}`
- Express/NestJS: `:param`
- Django: `<int:param>`, `<str:param>`, `<slug:param>`
- Literal client instances: `/users/42/orders` -> matches `/users/:id/orders`
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_PARAM_SEGMENT_TOKEN = "{*}"

# Common API Gateway / Reverse Proxy prefixes used in frontend apps
_KNOWN_PROXY_PREFIXES = (
    ("api", "v1"),
    ("api", "v2"),
    ("api",),
    ("v1",),
    ("v2",),
)

# Regex to detect parameter segments across all framework dialects
_IS_PARAM_SEGMENT = re.compile(
    r"""^(?:
        \$\{[^}]+\}                 | # JS/TS template literal: ${userId}
        :[a-zA-Z0-9_$]+            | # Express / NestJS: :userId
        \{[a-zA-Z0-9_$]+\}         | # FastAPI / Next.js: {userId}
        \[[a-zA-Z0-9_$]+\]         | # Next.js: [userId]
        \[\.\.\.[a-zA-Z0-9_$]+\]   | # Next.js catch-all: [...slug]
        <[a-zA-Z0-9_:]+>           | # Flask / Django: <int:user_id>, <user_id>
        \d+                        | # Literal integer in client URL: 42, 101
        [0-9a-fA-F-]{36}             # Literal UUID in client URL
    )$""",
    re.VERBOSE,
)


@dataclass(frozen=True)
class NormalizedRoute:
    method: str
    raw_path: str
    segments: tuple[str, ...]
    proxy_stripped_segments: tuple[str, ...]
    is_parameterized: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "raw_path": self.raw_path,
            "segments": list(self.segments),
            "proxy_stripped_segments": list(self.proxy_stripped_segments),
            "is_parameterized": self.is_parameterized,
        }


def normalize_route(method: str, path: str) -> NormalizedRoute:
    """Normalize a raw route into a canonical topological representation.

    Strips query strings, hashes, leading/trailing whitespace and slashes,
    normalizes all parameter styles into '{*}', and computes proxy-stripped segments.
    """
    clean_method = (method or "GET").strip().upper()
    # Strip query parameters (?foo=bar) and URL fragments (#anchor)
    clean_path = path.strip().split("?")[0].split("#")[0]
    # Remove leading and trailing slashes
    trimmed = clean_path.strip("/")

    if not trimmed:
        return NormalizedRoute(
            method=clean_method,
            raw_path=path,
            segments=("/",),
            proxy_stripped_segments=("/",),
            is_parameterized=False,
        )

    raw_parts = [p for p in trimmed.split("/") if p]
    normalized_parts: list[str] = []
    is_param = False

    for part in raw_parts:
        if _IS_PARAM_SEGMENT.match(part):
            normalized_parts.append(_PARAM_SEGMENT_TOKEN)
            is_param = True
        elif "${" in part:
            # Embedded template interpolation: e.g. "user-${id}"
            normalized_parts.append(_PARAM_SEGMENT_TOKEN)
            is_param = True
        else:
            normalized_parts.append(part.lower())

    segments_tuple = tuple(normalized_parts)

    # Compute proxy-stripped segments
    stripped_parts = list(segments_tuple)
    for prefix in _KNOWN_PROXY_PREFIXES:
        if len(stripped_parts) > len(prefix) and tuple(stripped_parts[: len(prefix)]) == prefix:
            stripped_parts = stripped_parts[len(prefix) :]
            break

    proxy_stripped_tuple = tuple(stripped_parts) if stripped_parts else ("/",)

    return NormalizedRoute(
        method=clean_method,
        raw_path=path,
        segments=segments_tuple,
        proxy_stripped_segments=proxy_stripped_tuple,
        is_parameterized=is_param,
    )


def match_route_topology(
    client_route: NormalizedRoute,
    backend_route: NormalizedRoute,
    allow_proxy_prefix: bool = True,
    match_methods: bool = True,
) -> tuple[bool, str]:
    """Deterministically match a client-side route against a backend route definition.

    Returns (matched, match_type):
    - "EXACT": Segments match exactly with parameter wildcards.
    - "PROXY_PREFIX": Client calls with /api or /v1 prefix matching backend root route.
    - "BACKEND_MOUNTED": Backend route has prefix (e.g. mounted blueprint) matching client.
    - "": No match.
    """
    # 1. Check HTTP method compatibility
    if match_methods and client_route.method and backend_route.method:
        client_m = client_route.method
        backend_m = backend_route.method
        if client_m != "*" and backend_m != "*" and client_m != backend_m:
            return False, ""

    # 2. Exact topological match
    if client_route.segments == backend_route.segments:
        return True, "EXACT"

    # 3. Proxy prefix match (e.g., Client: ['api', 'orders'] vs Backend: ['orders'])
    if allow_proxy_prefix:
        if client_route.proxy_stripped_segments == backend_route.segments:
            return True, "PROXY_PREFIX"

        # Reverse proxy prefix: Backend declared /api/orders, client called /orders (or vice-versa)
        if client_route.segments == backend_route.proxy_stripped_segments:
            return True, "PROXY_PREFIX"

        if client_route.proxy_stripped_segments == backend_route.proxy_stripped_segments:
            if client_route.proxy_stripped_segments != ("/",):
                return True, "PROXY_PREFIX"

    # 4. Suffix / sub-path mount match (e.g. Blueprint mounted at /api/shop and client calls /api/shop/checkout)
    # Check if backend route is a suffix of client route or vice versa with identical parameter topology
    c_segs = client_route.proxy_stripped_segments
    b_segs = backend_route.proxy_stripped_segments
    if len(c_segs) == len(b_segs):
        matched = True
        for cs, bs in zip(c_segs, b_segs, strict=True):
            if cs != bs and cs != _PARAM_SEGMENT_TOKEN and bs != _PARAM_SEGMENT_TOKEN:
                matched = False
                break
        if matched:
            return True, "TOPOLOGICAL_PARAM_MATCH"

    return False, ""
