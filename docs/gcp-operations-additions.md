# ParkPulse GCP Operations Additions

ParkPulse now has optional adapters for three GCP operations services:

- Pub/Sub plus Eventarc for live park signal intake and delivery-event fanout.
- Firebase Cloud Messaging for guest and worker app notifications.
- Cloud Workflows for operator approval workflows.

The local JSONL delivery outbox remains the source of truth. GCP adapters decorate dispatches when enabled, and return `skipped` status when the required environment is not configured.

## Environment

```bash
ENABLE_PARKPULSE_PUBSUB=true
PARKPULSE_PUBSUB_TOPIC=parkpulse-ops-events

ENABLE_PARKPULSE_FCM=false
ENABLE_PARKPULSE_PSEUDO_FCM=true
PARKPULSE_FCM_GUEST_TOPIC=parkpulse-guest-app
PARKPULSE_FCM_WORKER_TOPIC=parkpulse-worker-device

ENABLE_PARKPULSE_WORKFLOWS=false
PARKPULSE_WORKFLOW_LOCATION=us-central1
PARKPULSE_WORKFLOW_ID=parkpulse-operator-approval
```

Run the private bootstrap script to enable the APIs, create the Pub/Sub topic, and update `backend/.env`:

```bash
scripts/gcp_bootstrap_private.sh <gcp-project-id> us-central1
```

Deploy the operator approval workflow and Eventarc trigger after the private Cloud Run service exists:

```bash
scripts/deploy_gcp_operations.sh <gcp-project-id> us-central1 parkpulse-private-api
```

This deploys:

- `infra/workflows/parkpulse-operator-approval.yaml`
- Pub/Sub topic `PARKPULSE_PUBSUB_TOPIC`, default `parkpulse-ops-events`
- Eventarc trigger `PARKPULSE_EVENTARC_TRIGGER`, default `parkpulse-ops-signal`
- Trigger service account `PARKPULSE_EVENTARC_SA`, default `parkpulse-eventarc-trigger`
- Pseudo Firebase topic inbox when real FCM is disabled

The workflow is conservative by default. It records a pending operator-review execution. For a demo-only auto-approval callback, set:

```bash
ENABLE_PARKPULSE_WORKFLOWS=true
PARKPULSE_WORKFLOW_AUTO_APPROVE=true
PARKPULSE_WORKFLOW_CALLBACK_URL=https://YOUR_PRIVATE_RUN_URL/api/park/delivery/acknowledge
```

Only use auto-approval for non-safety demo payloads. ParkPulse still blocks ride reopening, safety clearance, PII disclosure, and other policy violations in the governance layer.

## API Endpoints

Status:

```bash
curl http://127.0.0.1:8000/api/gcp/operations/status
```

Publish a manual Pub/Sub event:

```bash
curl -X POST http://127.0.0.1:8000/api/gcp/pubsub/park-event \
  -H 'Content-Type: application/json' \
  -d '{"event_type":"parkpulse.manual.signal","payload":{"text":"Food Court A pickup queue is backing up","source":"demo"}}'
```

Receive Pub/Sub push or Eventarc CloudEvents:

```bash
curl -X POST http://127.0.0.1:8000/api/gcp/eventarc/park-signal \
  -H 'Content-Type: application/json' \
  -d '{"message":{"data":"eyJ0ZXh0IjoiRHJhZ29uIENvYXN0ZXIgaXMgZG93biIsInNvdXJjZSI6InB1YnN1YiJ9"}}'
```

Start an operator approval workflow:

```bash
curl -X POST http://127.0.0.1:8000/api/gcp/workflows/operator-approval \
  -H 'Content-Type: application/json' \
  -d '{"payload":{"type":"parkpulse.delivery.approval","dispatchId":"demo"}}'
```

Read pseudo Firebase messages:

```bash
curl http://127.0.0.1:8000/api/gcp/pseudo-firebase/messages
curl 'http://127.0.0.1:8000/api/gcp/pseudo-firebase/messages?topic=parkpulse-worker-device'
```

Pseudo Firebase uses the same guest and worker topic names as FCM. It persists messages to `PARKPULSE_PSEUDO_FCM_OUTBOX`, defaulting to `/tmp/parkpulse/pseudo_firebase_messages.jsonl`.

## Eventarc Trigger

The script above creates or updates this trigger. The underlying command is:

```bash
gcloud eventarc triggers create parkpulse-ops-signal \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --location "$GOOGLE_CLOUD_LOCATION" \
  --destination-run-service parkpulse-private-api \
  --destination-run-region "$GOOGLE_CLOUD_LOCATION" \
  --destination-run-path /api/gcp/eventarc/park-signal \
  --event-filters type=google.cloud.pubsub.topic.v1.messagePublished \
  --transport-topic "projects/$GOOGLE_CLOUD_PROJECT/topics/$PARKPULSE_PUBSUB_TOPIC"
```

Keep the Cloud Run service authenticated-only. Grant the Eventarc trigger service account `roles/run.invoker` on the service if your project does not use the default Eventarc service agent for invocation.
