"""
SQS (subscribed to SNS) -> Monolith POST /logRevisionAsync.

Expects RawMessageDelivery=false so each SQS body is the SNS envelope JSON with a string "Message" field.

Environment:
  MONOLITH_REVISION_LOG_URL  Full URL for POST (e.g. https://monolith/api/logRevisionAsync)
  REVISION_LOG_AUTH_HEADER   Optional static value for Authorization header
  HTTP_TIMEOUT_SECONDS       Optional, default 30
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict

LOG = logging.getLogger()
LOG.setLevel(logging.INFO)

URL = os.environ["MONOLITH_REVISION_LOG_URL"]
AUTH = os.environ.get("REVISION_LOG_AUTH_HEADER")
TIMEOUT = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30"))


def _parse_sns_wrapped_sqs_body(body: str) -> Dict[str, Any]:
    outer = json.loads(body)
    inner_raw = outer.get("Message")
    if not isinstance(inner_raw, str):
        raise ValueError("SNS Message field missing or not a string")
    payload = json.loads(inner_raw)
    return payload


def _monolith_body(export_event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map export notification to Monolith contract. Adjust keys to match real /logRevisionAsync OpenAPI.
    """
    return {
        "source": "async-export",
        "schemaVersion": export_event.get("schemaVersion"),
        "eventType": export_event.get("eventType"),
        "traceId": export_event.get("traceId"),
        "jobId": export_event.get("jobId"),
        "projectId": export_event.get("projectId"),
        "status": export_event.get("status"),
        "createdBy": export_event.get("createdBy"),
        "input": export_event.get("input"),
        "result": export_event.get("result"),
        "timestamps": {
            "createdAt": export_event.get("createdAt"),
            "updatedAt": export_event.get("updatedAt"),
        },
    }


def handler(event, context):
    """Return partial batch failures so SQS can retry only failed messages (ReportBatchItemFailures)."""
    failures: list = []
    for record in event.get("Records", []):
        body = record.get("body", "")
        msg_id = record.get("messageId")
        try:
            export_event = _parse_sns_wrapped_sqs_body(body)
            event_type = export_event.get("eventType")
            if event_type not in {"connect.export.completed", "connect.export.failed"}:
                LOG.info("Skipping unsupported eventType=%s msgId=%s", event_type, msg_id)
                continue

            mono_payload = _monolith_body(export_event)
            data = json.dumps(mono_payload, default=str).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            job_id = export_event.get("jobId", "")
            headers["X-Idempotency-Key"] = f"{job_id}:{event_type}"
            if AUTH:
                headers["Authorization"] = AUTH

            req = urllib.request.Request(URL, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                if resp.status >= 300:
                    raise RuntimeError(f"Monolith HTTP {resp.status}")

            LOG.info("Logged revision for jobId=%s eventType=%s", job_id, event_type)
        except Exception:
            LOG.exception("Revision log failed msgId=%s", msg_id)
            failures.append({"itemIdentifier": msg_id})

    return {"batchItemFailures": failures}
