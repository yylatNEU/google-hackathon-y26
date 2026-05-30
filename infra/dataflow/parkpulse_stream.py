"""Apache Beam pipeline for ParkPulse real-time telemetry.

This Flex Template entrypoint consumes ParkPulse event envelopes from Pub/Sub,
normalizes them, and writes analytics-ready rows to BigQuery. The local backend
continues to mirror the same envelopes so demos work before the Dataflow job is
deployed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions, SetupOptions, StandardOptions


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_json(value: bytes | str) -> dict[str, Any]:
    raw = value.decode("utf-8") if isinstance(value, bytes) else value
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"payload": parsed}
    except json.JSONDecodeError:
        return {"payload": {"raw": raw}, "eventType": "parkpulse.unparsed"}


class NormalizeParkPulseEvent(beam.DoFn):
    """Convert Pub/Sub messages into a stable BigQuery row contract."""

    def process(self, message: bytes, publish_time=beam.DoFn.TimestampParam):
        envelope = _safe_json(message)
        payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else envelope
        event_type = str(envelope.get("eventType") or envelope.get("event_type") or "parkpulse.event")
        event_id_seed = json.dumps(envelope, sort_keys=True, default=str).encode("utf-8")
        created_at = str(envelope.get("createdAt") or envelope.get("created_at") or _utc_now())

        yield {
            "event_id": str(envelope.get("id") or f"dataflow_{hashlib.sha1(event_id_seed).hexdigest()[:16]}"),
            "event_type": event_type,
            "created_at": created_at,
            "ingested_at": _utc_now(),
            "publish_time": publish_time.to_rfc3339(),
            "scenario_key": str(payload.get("scenario_key") or payload.get("scenario") or ""),
            "zone_id": str(payload.get("zone_id") or payload.get("zone") or payload.get("targetZone") or ""),
            "dispatch_id": str(payload.get("dispatch_id") or payload.get("dispatchId") or payload.get("id") or ""),
            "risk_score": float(payload.get("risk_score") or payload.get("riskScore") or 0),
            "status": str(payload.get("status") or envelope.get("status") or ""),
            "payload_json": json.dumps(payload, sort_keys=True, default=str),
        }


def build_pipeline(pipeline: beam.Pipeline, input_subscription: str, output_table: str) -> None:
    (
        pipeline
        | "Read Pub/Sub events" >> beam.io.ReadFromPubSub(subscription=input_subscription)
        | "Normalize event envelope" >> beam.ParDo(NormalizeParkPulseEvent())
        | "Write BigQuery telemetry"
        >> beam.io.WriteToBigQuery(
            output_table,
            schema={
                "fields": [
                    {"name": "event_id", "type": "STRING", "mode": "REQUIRED"},
                    {"name": "event_type", "type": "STRING", "mode": "NULLABLE"},
                    {"name": "created_at", "type": "TIMESTAMP", "mode": "NULLABLE"},
                    {"name": "ingested_at", "type": "TIMESTAMP", "mode": "NULLABLE"},
                    {"name": "publish_time", "type": "TIMESTAMP", "mode": "NULLABLE"},
                    {"name": "scenario_key", "type": "STRING", "mode": "NULLABLE"},
                    {"name": "zone_id", "type": "STRING", "mode": "NULLABLE"},
                    {"name": "dispatch_id", "type": "STRING", "mode": "NULLABLE"},
                    {"name": "risk_score", "type": "FLOAT", "mode": "NULLABLE"},
                    {"name": "status", "type": "STRING", "mode": "NULLABLE"},
                    {"name": "payload_json", "type": "STRING", "mode": "NULLABLE"},
                ]
            },
            create_disposition=beam.io.BigQueryDisposition.CREATE_IF_NEEDED,
            write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
        )
    )


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_subscription", required=True, help="Pub/Sub subscription path for ParkPulse events.")
    parser.add_argument("--output_table", required=True, help="BigQuery table as PROJECT:DATASET.TABLE.")
    return parser.parse_known_args(argv)


def run(argv: list[str] | None = None) -> None:
    known_args, pipeline_args = parse_args(argv)
    options = PipelineOptions(pipeline_args, save_main_session=True, streaming=True)
    options.view_as(StandardOptions).streaming = True
    options.view_as(SetupOptions).save_main_session = True
    with beam.Pipeline(options=options) as pipeline:
        build_pipeline(pipeline, known_args.input_subscription, known_args.output_table)


if __name__ == "__main__":
    run()
