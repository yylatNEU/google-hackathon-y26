# ParkPulse Runtime Location

Run ParkPulse from the external disk copy:

```text
/Volumes/Backup drive /parkpulse-runtime/google-hackathon-y26
```

The Desktop folder is now kept as a lightweight source fallback only. Do not reinstall
`backend/venv`, `frontend/node_modules`, `.next*`, or other generated runtime caches here.

Use:

```sh
./start-external-runtime.sh
```

Active runtime services:

```text
Backend:  http://127.0.0.1:8000
Frontend: http://127.0.0.1:5174
```
