# MongoDB Operational Memory

ParkPulse uses MongoDB as the operational memory layer when `MONGODB_URI` is configured.

## Collections

- `park_state`: current live park state
- `rides`: current ride capacity, queue, downtime, and staffing pressure
- `staff_shifts`: current role coverage and stress/break-window pressure
- `food_inventory`: current food capacity and stock constraints
- `playbooks`: seeded SOPs and response procedures
- `incidents`: seeded historical disruption memories and lessons
- `agent_decisions`: agent recommendations and retrieved context
- `guest_messages`: guest-message drafts tied to stored decisions
- `eval_results`: GCP trace/eval scorecards linked to decisions

`park_state`, `rides`, `staff_shifts`, `food_inventory`, `playbooks`, and `incidents` are upserted so routine demo ticks do not append duplicate documents. `agent_decisions`, `guest_messages`, and `eval_results` are append-style memory, but the backend stores only useful, deduped decisions.

## Local Setup

1. Install backend dependencies:

```bash
cd backend
venv/bin/python -m pip install -r requirements.txt
```

2. Add MongoDB variables to `backend/.env`:

```bash
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster-host>/?retryWrites=true&w=majority
MONGODB_DATABASE=parkpulse_ops
MONGODB_PLAYBOOK_VECTOR_INDEX=playbook_vector_index
MONGODB_DISABLE_DECISION_WRITES=false
MONGODB_MIN_USEFUL_EVAL_SCORE=75
```

3. Start the backend:

```bash
cd backend
venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

4. Verify:

```bash
curl http://127.0.0.1:8001/api/park/memory
```

Expected status:

```json
{
  "status": {
    "mode": "mongodb",
    "connected": true
  }
}
```

If `MONGODB_URI` is missing or unreachable, the backend stays demo-safe and reports `mode: "demo_fallback"`.

## Pipeline Controls

- `MONGODB_DISABLE_DECISION_WRITES=true`: keeps live-state upserts and retrieval working, but blocks append writes to `agent_decisions`, `guest_messages`, and `eval_results`.
- `MONGODB_MIN_USEFUL_EVAL_SCORE=75`: marks high-scoring decisions as useful. The gate also keeps selected actions, retrieval-grounded decisions, operator actions, and policy/safety review cases.
- Repeated identical decisions use a deterministic document id and are upserted instead of inserted again.

## Optional Atlas Vector Search

Create a vector search index named `playbook_vector_index` on `playbooks.embedding` with 64 dimensions and cosine similarity. If the index is unavailable, retrieval falls back to MongoDB text search or local keyword similarity.
