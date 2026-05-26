"""
DynamoDB Streams -> SNS: publish versioned export notifications when a job reaches a terminal status.

Environment:
  SNS_TOPIC_ARN      Target topic (e.g. TcFileServiceTopic)
  DEDUP_TABLE_NAME   Table for idempotency (PK jobId); optional TTL attribute "ttl" (epoch seconds)
"""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.types import TypeDeserializer

LOG = logging.getLogger()
LOG.setLevel(logging.INFO)

_sns = boto3.client("sns")
_ddb = boto3.resource("dynamodb")
_deser = TypeDeserializer()

DEDUP_TABLE = os.environ.get("DEDUP_TABLE_NAME")
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]

# Only emit when transitioning into these states (compare with old image)
_TERMINAL = frozenset({"DONE", "FAILED"})


def _unwrap_ddb(image: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _deser.deserialize(v) for k, v in image.items()}


def _to_jsonable(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    return obj


def _reserve_dedup(job_id: str) -> bool:
    """Return True if reserved (first time), False if duplicate."""
    if not DEDUP_TABLE:
        return True
    table = _ddb.Table(DEDUP_TABLE)
    ttl = int(os.environ.get("DEDUP_TTL_SECONDS", "2592000"))  # 30d default
    import time

    expires = int(time.time()) + ttl
    try:
        table.put_item(
            Item={"jobId": job_id, "ttl": expires},
            ConditionExpression="attribute_not_exists(jobId)",
        )
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def _release_dedup(job_id: str) -> None:
    if not DEDUP_TABLE:
        return
    _ddb.Table(DEDUP_TABLE).delete_item(Key={"jobId": job_id})


def _build_message(new_image: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    job_type = new_image.get("jobType")
    if job_type != "EXPORT":
        return None

    status = new_image.get("status")
    if status not in _TERMINAL:
        return None

    if status == "DONE":
        event_type = "connect.export.completed"
    else:
        event_type = "connect.export.failed"

    trace_id = new_image.get("traceId") or new_image.get("jobId")

    payload = {
        "schemaVersion": "1.0.0",
        "eventType": event_type,
        "traceId": trace_id,
        "jobId": new_image.get("jobId"),
        "jobType": job_type,
        "status": status,
        "projectId": new_image.get("projectId"),
        "createdBy": _to_jsonable(new_image.get("createdBy")) if new_image.get("createdBy") else None,
        "createdAt": new_image.get("createdAt"),
        "updatedAt": new_image.get("updatedAt"),
        "input": _to_jsonable(new_image.get("input")) if new_image.get("input") else None,
        "result": _to_jsonable(new_image.get("result")) if new_image.get("result") else None,
    }
    # Drop None for cleaner messages
    return {k: v for k, v in payload.items() if v is not None}


def _sns_attributes(event_type: str, job_type: str, schema_version: str) -> Dict[str, Dict[str, str]]:
    return {
        "eventType": {"DataType": "String", "StringValue": event_type},
        "jobType": {"DataType": "String", "StringValue": job_type},
        "schemaVersion": {"DataType": "String", "StringValue": schema_version},
    }


def handler(event, context):
    for record in event.get("Records", []):
        if record.get("eventName") != "MODIFY":
            continue
        ddb = record.get("dynamodb") or {}
        old_image = ddb.get("OldImage")
        new_image = ddb.get("NewImage")
        if not new_image:
            continue
        new_plain = _unwrap_ddb(new_image)
        old_plain = _unwrap_ddb(old_image) if old_image else {}

        new_status = new_plain.get("status")
        old_status = old_plain.get("status")
        if new_status == old_status:
            continue
        if new_status not in _TERMINAL:
            continue

        body = _build_message(new_plain)
        if not body:
            continue

        job_id = body["jobId"]
        if not job_id:
            LOG.warning("Skipping record without jobId: %s", record.get("eventID"))
            continue

        reserved = _reserve_dedup(job_id)
        if not reserved:
            LOG.info("Dedup skip duplicate stream delivery jobId=%s", job_id)
            continue

        msg_str = json.dumps(body, default=str)
        attrs = _sns_attributes(body["eventType"], body["jobType"], body["schemaVersion"])
        try:
            _sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Message=msg_str,
                MessageAttributes=attrs,
                Subject="Trimble Connect export notification",
            )
            LOG.info("Published export event jobId=%s eventType=%s", job_id, body["eventType"])
        except Exception:
            _release_dedup(job_id)
            LOG.exception("SNS publish failed jobId=%s", job_id)
            raise

    return {"ok": True}
