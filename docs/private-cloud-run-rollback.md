# Private Cloud Run Rollback

Use this when the private ParkPulse API deploys but live validation fails, traffic points at a bad revision, or role/audit contracts regress.

## Default Rollback

```bash
PARKPULSE_ROLLBACK_REASON="post-deploy verifier failed" \
scripts/rollback_private_cloud_run.sh crypto-song-496607-d7 us-central1 parkpulse-private-api
```

The script selects the newest previous ready revision that passes rollback preflight. It skips ready revisions that are missing signed-role strict mode, the trusted issuer secret, or MongoDB audit requirements.

## Explicit Revision

```bash
PARKPULSE_ROLLBACK_REASON="manual rollback to known good role-auth revision" \
scripts/rollback_private_cloud_run.sh crypto-song-496607-d7 us-central1 parkpulse-private-api parkpulse-private-api-00079-n7x
```

## Safety Gates

Rollback refuses a target revision unless it is ready and has:

- `PARKPULSE_REQUIRE_SIGNED_ROLE_FOR_MUTATION=true`
- `PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN=true`
- `PARKPULSE_ROLE_AUTH_SECRET`
- `PARKPULSE_ROLE_SESSION_ISSUER_KEY`
- `MONGODB_URI`
- `PARKPULSE_LIVE_FEED_STORAGE=mongodb`

After promotion, it runs `scripts/verify_private_cloud_run_deploy.sh` with `PARKPULSE_EXPECTED_REVISION` set to the rollback target. That verifies readiness, MongoDB connectivity, signed-role issuer, spoof blocking, and Mongo-backed audit.

## Reports

Reports are written to `output/rollback/` by default. Override with:

```bash
PARKPULSE_ROLLBACK_REPORT_DIR=/tmp/parkpulse-rollbacks \
scripts/rollback_private_cloud_run.sh crypto-song-496607-d7 us-central1 parkpulse-private-api
```
