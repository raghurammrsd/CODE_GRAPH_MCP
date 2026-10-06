"""OpenTelemetry span parser, adapter layer, and privacy sanitizer.

Guarantees:
1. Adapters for both standard OTLP JSON (resourceSpans) and flat span lists.
2. Privacy: Strips all message bodies, payloads, bearer tokens, cookies, and secrets.
3. Hashing: Salted SHA-256 for correlation/message IDs without saving raw identifiers.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from codegraph.async_queue.otel_models import OTelSpanRecord

_SENSITIVE_KEY_SUBSTRINGS = (
    "auth",
    "token",
    "cookie",
    "secret",
    "password",
    "credential",
    "payload",
    "body",
    "message_body",
    "raw_message",
    "data",
)


def hash_correlation_id(raw_id: str | int) -> str:
    """Generate a deterministic, salted SHA-256 hash for correlation identifiers."""
    clean = str(raw_id).strip()
    if not clean:
        return ""
    digest = hashlib.sha256(f"cg_corr_salt_v1:{clean}".encode()).hexdigest()
    return digest[:16]


def sanitize_attributes(raw_attrs: dict[str, Any]) -> dict[str, Any]:
    """Sanitize attributes dictionary, removing any payload bodies, headers, or secrets."""
    sanitized: dict[str, Any] = {}
    for k, v in raw_attrs.items():
        k_lower = k.lower()
        if any(bad in k_lower for bad in _SENSITIVE_KEY_SUBSTRINGS):
            continue
        # Preserve primitive values only
        if isinstance(v, (int, float, bool)):
            sanitized[k] = v
        elif isinstance(v, str):
            if len(v) > 256:
                v = v[:256] + "...[truncated]"
            sanitized[k] = v
        elif isinstance(v, (list, tuple)):
            if len(v) <= 10 and all(isinstance(x, (str, int, float, bool)) for x in v):
                sanitized[k] = list(v)
    return sanitized


def _extract_otlp_value(val_obj: Any) -> Any:
    """Unpack OTLP AnyValue object (e.g. {'stringValue': 'kafka'})."""
    if not isinstance(val_obj, dict):
        return val_obj
    if "stringValue" in val_obj:
        return val_obj["stringValue"]
    if "intValue" in val_obj:
        try:
            return int(val_obj["intValue"])
        except (ValueError, TypeError):
            return 0
    if "doubleValue" in val_obj:
        try:
            return float(val_obj["doubleValue"])
        except (ValueError, TypeError):
            return 0.0
    if "boolValue" in val_obj:
        return bool(val_obj["boolValue"])
    if "arrayValue" in val_obj and "values" in val_obj["arrayValue"]:
        return [_extract_otlp_value(x) for x in val_obj["arrayValue"]["values"]]
    return ""


def _unpack_otlp_key_values(kv_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert an OTLP KeyValue list [{'key': 'k', 'value': {...}}] to a dict."""
    out: dict[str, Any] = {}
    for item in kv_list:
        if isinstance(item, dict) and "key" in item:
            out[str(item["key"])] = _extract_otlp_value(item.get("value"))
    return out


class OTLPJsonAdapter:
    """Adapter for standard OpenTelemetry OTLP JSON (resourceSpans)."""

    @classmethod
    def can_handle(cls, data: dict[str, Any]) -> bool:
        return "resourceSpans" in data

    @classmethod
    def parse(cls, data: dict[str, Any]) -> list[OTelSpanRecord]:
        records: list[OTelSpanRecord] = []
        resource_spans = data.get("resourceSpans", [])
        if not isinstance(resource_spans, list):
            return records

        for rs in resource_spans:
            service_name = ""
            if isinstance(rs, dict):
                res = rs.get("resource", {})
                if isinstance(res, dict):
                    res_attrs = res.get("attributes", [])
                    if isinstance(res_attrs, list):
                        attrs_map = _unpack_otlp_key_values(res_attrs)
                        service_name = str(attrs_map.get("service.name", ""))

                scope_spans = rs.get("scopeSpans", [])
                if isinstance(scope_spans, list):
                    for ss in scope_spans:
                        if isinstance(ss, dict):
                            spans = ss.get("spans", [])
                            if isinstance(spans, list):
                                for s in spans:
                                    rec = cls._parse_span(s, service_name)
                                    if rec:
                                        records.append(rec)
        return records

    @classmethod
    def _parse_span(cls, s: dict[str, Any], default_service: str) -> OTelSpanRecord | None:
        trace_id = str(s.get("traceId", "")).strip()
        span_id = str(s.get("spanId", "")).strip()
        if not trace_id or not span_id:
            return None

        parent_span_id = str(s.get("parentSpanId", "")).strip()
        name = str(s.get("name", "")).strip()
        kind_raw = s.get("kind", 0)

        # Map OTLP SpanKind int or str
        kind_map = {
            1: "INTERNAL",
            2: "SERVER",
            3: "CLIENT",
            4: "PRODUCER",
            5: "CONSUMER",
            "SPAN_KIND_INTERNAL": "INTERNAL",
            "SPAN_KIND_SERVER": "SERVER",
            "SPAN_KIND_CLIENT": "CLIENT",
            "SPAN_KIND_PRODUCER": "PRODUCER",
            "SPAN_KIND_CONSUMER": "CONSUMER",
        }
        kind = kind_map.get(kind_raw, str(kind_raw).replace("SPAN_KIND_", ""))

        start_nano = int(s.get("startTimeUnixNano", 0) or 0)
        end_nano = int(s.get("endTimeUnixNano", 0) or 0)
        duration_ms = (end_nano - start_nano) / 1_000_000.0 if end_nano > start_nano else 0.0

        # Status
        status_code = "OK"
        status_dict = s.get("status", {})
        if isinstance(status_dict, dict):
            raw_code = str(status_dict.get("code", "")).upper()
            if "ERROR" in raw_code or raw_code == "2":
                status_code = "ERROR"

        # Attributes
        raw_attrs: dict[str, Any] = {}
        if isinstance(s.get("attributes"), list):
            raw_attrs = _unpack_otlp_key_values(s["attributes"])
        elif isinstance(s.get("attributes"), dict):
            raw_attrs = dict(s["attributes"])

        service_name = str(raw_attrs.get("service.name") or default_service)

        # Semantic conventions for messaging
        msg_system = str(raw_attrs.get("messaging.system", "")).lower()
        msg_dest = str(raw_attrs.get("messaging.destination", ""))
        msg_op = str(raw_attrs.get("messaging.operation", "")).lower()

        # If operation wasn't explicitly set, infer from span kind
        if not msg_op:
            if kind == "PRODUCER":
                msg_op = "publish"
            elif kind == "CONSUMER":
                msg_op = "process"

        # Correlation ID hashing
        corr_id = raw_attrs.get("messaging.message_id") or raw_attrs.get("messaging.conversation_id") or raw_attrs.get("correlation_id") or ""
        corr_hash = hash_correlation_id(corr_id) if corr_id else ""

        # Span links
        links_list: list[tuple[str, str]] = []
        raw_links = s.get("links", [])
        if isinstance(raw_links, list):
            for lk in raw_links:
                if isinstance(lk, dict):
                    l_trace = str(lk.get("traceId", "")).strip()
                    l_span = str(lk.get("spanId", "")).strip()
                    if l_trace and l_span:
                        links_list.append((l_trace, l_span))

        sanitized = sanitize_attributes(raw_attrs)

        return OTelSpanRecord(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            service_name=service_name,
            name=name,
            kind=kind,
            start_time_unix_nano=start_nano,
            end_time_unix_nano=end_nano,
            duration_ms=duration_ms,
            status_code=status_code,
            messaging_system=msg_system,
            messaging_destination=msg_dest,
            messaging_operation=msg_op,
            correlation_id_hash=corr_hash,
            attributes=sanitized,
            links=tuple(links_list),
        )


class GenericSpanListAdapter:
    """Adapter for flat list of spans (Jaeger, custom JSON, or SDK exports)."""

    @classmethod
    def can_handle(cls, data: Any) -> bool:
        if isinstance(data, list):
            return True
        if isinstance(data, dict) and "spans" in data:
            return True
        return False

    @classmethod
    def parse(cls, data: Any) -> list[OTelSpanRecord]:
        span_items = data if isinstance(data, list) else data.get("spans", [])
        records: list[OTelSpanRecord] = []
        if not isinstance(span_items, list):
            return records

        for s in span_items:
            if not isinstance(s, dict):
                continue
            trace_id = str(s.get("trace_id") or s.get("traceId") or "").strip()
            span_id = str(s.get("span_id") or s.get("spanId") or "").strip()
            if not trace_id or not span_id:
                continue

            parent_span_id = str(s.get("parent_span_id") or s.get("parentSpanId") or "").strip()
            name = str(s.get("name") or s.get("operation_name") or "").strip()
            kind = str(s.get("kind") or "INTERNAL").upper()
            service_name = str(s.get("service_name") or s.get("service") or "")

            duration_ms = float(s.get("duration_ms") or 0.0)
            if not duration_ms and "duration_us" in s:
                duration_ms = float(s["duration_us"]) / 1000.0

            status_code = str(s.get("status") or s.get("status_code") or "OK").upper()
            if "ERR" in status_code:
                status_code = "ERROR"

            raw_attrs = dict(s.get("attributes") or s.get("tags") or {})
            if not service_name and "service.name" in raw_attrs:
                service_name = str(raw_attrs["service.name"])

            msg_system = str(raw_attrs.get("messaging.system", "")).lower()
            msg_dest = str(raw_attrs.get("messaging.destination", ""))
            msg_op = str(raw_attrs.get("messaging.operation", "")).lower()

            if not msg_op:
                if "PROD" in kind:
                    msg_op = "publish"
                elif "CONS" in kind:
                    msg_op = "process"

            corr_id = raw_attrs.get("messaging.message_id") or raw_attrs.get("correlation_id") or ""
            corr_hash = hash_correlation_id(corr_id) if corr_id else ""

            links_list: list[tuple[str, str]] = []
            for lk in s.get("links", []):
                if isinstance(lk, dict):
                    l_trace = str(lk.get("trace_id") or lk.get("traceId") or "").strip()
                    l_span = str(lk.get("span_id") or lk.get("spanId") or "").strip()
                    if l_trace and l_span:
                        links_list.append((l_trace, l_span))

            sanitized = sanitize_attributes(raw_attrs)

            records.append(
                OTelSpanRecord(
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    service_name=service_name,
                    name=name,
                    kind=kind,
                    start_time_unix_nano=int(s.get("start_time_unix_nano", 0) or 0),
                    end_time_unix_nano=int(s.get("end_time_unix_nano", 0) or 0),
                    duration_ms=duration_ms,
                    status_code=status_code,
                    messaging_system=msg_system,
                    messaging_destination=msg_dest,
                    messaging_operation=msg_op,
                    correlation_id_hash=corr_hash,
                    attributes=sanitized,
                    links=tuple(links_list),
                )
            )
        return records


def parse_otel_spans(data_or_text: Any) -> list[OTelSpanRecord]:
    """Parse raw OpenTelemetry JSON string or dictionary/list into canonical records."""
    if isinstance(data_or_text, str):
        try:
            data = json.loads(data_or_text)
        except Exception:
            return []
    else:
        data = data_or_text

    if isinstance(data, dict) and OTLPJsonAdapter.can_handle(data):
        raw_records = OTLPJsonAdapter.parse(data)
    elif GenericSpanListAdapter.can_handle(data):
        raw_records = GenericSpanListAdapter.parse(data)
    else:
        raw_records = []

    # Deduplicate within batch by composite_id
    seen: set[str] = set()
    deduped: list[OTelSpanRecord] = []
    for r in raw_records:
        if r.composite_id not in seen:
            seen.add(r.composite_id)
            deduped.append(r)
    return deduped
