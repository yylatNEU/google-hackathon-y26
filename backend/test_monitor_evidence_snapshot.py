from __future__ import annotations

import asyncio
import sys
import types
from copy import deepcopy

import main


class FakeMonitorCollection:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.find_count = 0
        self.replace_count = 0
        self.indexes: list[tuple] = []

    def replace_one(self, query, document, upsert=False):
        self.replace_count += 1
        assert upsert is True
        self.docs[str(query["_id"])] = deepcopy(document)

    def find_one(self, query, projection=None, max_time_ms=None):
        self.find_count += 1
        assert max_time_ms >= 250
        document = self.docs.get(str(query["_id"]))
        if document is None:
            return None
        clean = deepcopy(document)
        if projection and projection.get("_id") == 0:
            clean.pop("_id", None)
        return clean

    def create_index(self, spec, **options):
        self.indexes.append((spec, options))
        return options.get("name")


class FakeMonitorDb:
    def __init__(self, collection: FakeMonitorCollection):
        self.collection = collection

    def __getitem__(self, _name):
        return self.collection


class FakeMonitorClient:
    def __init__(self, collection: FakeMonitorCollection):
        self.collection = collection
        self.uri = None
        self.kwargs = {}

    def __call__(self, uri, **kwargs):
        self.uri = uri
        self.kwargs = kwargs
        return self

    def __getitem__(self, _name):
        return FakeMonitorDb(self.collection)


def test_monitor_evidence_cache_uses_mongodb_snapshot_across_cold_reads(tmp_path, monkeypatch):
    collection = FakeMonitorCollection()
    fake_client = FakeMonitorClient(collection)
    fake_mongo = types.ModuleType("mongo_memory")
    fake_mongo.MongoClient = fake_client
    fake_mongo._ensure_mongo_driver = lambda: True
    fake_mongo._normalized_mongodb_uri = lambda uri: f"normalized:{uri}"
    monkeypatch.setitem(sys.modules, "mongo_memory", fake_mongo)
    monkeypatch.setenv("PARKPULSE_MONITOR_EVIDENCE_STORAGE", "mongodb")
    monkeypatch.setenv("MONGODB_DIRECT_URI", '"mongodb://example.invalid/parkpulse"')
    monkeypatch.setenv("PARKPULSE_MONITOR_EVIDENCE_MONGO_DATABASE", "parkpulse_monitor")
    monkeypatch.setenv("PARKPULSE_MONITOR_EVIDENCE_MONGO_COLLECTION", "monitor_snapshots")
    monkeypatch.setenv("PARKPULSE_MONITOR_EVIDENCE_SNAPSHOT_PATH", str(tmp_path / "monitor-evidence.json"))
    monkeypatch.setattr(main, "_monitor_source_watermark", lambda: {"fingerprint": "source-fp"})
    main._monitor_evidence_mongo_client = None
    main._monitor_evidence_cache.clear()
    main._monitor_evidence_refreshing.clear()
    main._monitor_evidence_storage_status_cache = None

    graph = {
        "status": "ready",
        "mode": "monitor_evidence_graph",
        "case_count": 1,
        "summary": {"trace_record_count": 1},
        "cases": [{"case_id": "case-1", "trace_ids": ["trace-1"], "policy_refs": ["POL-1"]}],
        "source_watermark": {"fingerprint": "source-fp"},
    }

    async def fake_graph(case_id=None, limit=30):
        return deepcopy(graph)

    monkeypatch.setattr(main, "_monitor_evidence_graph", fake_graph)
    rebuilt = asyncio.run(main._monitor_evidence_graph_cached(limit=40, force_refresh=True))

    assert rebuilt["evidence_cache"]["state"] == "rebuilt"
    assert rebuilt["evidence_cache"]["snapshot_store"]["backend"] == "mongodb"
    assert rebuilt["evidence_cache"]["snapshot_store"]["database"] == "parkpulse_monitor"
    assert fake_client.uri == "normalized:mongodb://example.invalid/parkpulse"
    assert collection.replace_count == 1
    assert "monitor-evidence-limit-40" in collection.docs

    (tmp_path / "monitor-evidence.json").unlink()
    main._monitor_evidence_cache.clear()

    async def fail_graph(case_id=None, limit=30):
        raise AssertionError("cold read should use the Mongo snapshot")

    monkeypatch.setattr(main, "_monitor_evidence_graph", fail_graph)
    cached = asyncio.run(main._monitor_evidence_graph_cached(case_id="case-1", limit=40))

    assert cached["case_count"] == 1
    assert cached["cases"][0]["case_id"] == "case-1"
    assert cached["evidence_cache"]["state"] == "snapshot_fresh"
    assert cached["evidence_cache"]["source_current"] is True
    assert collection.find_count == 1


def test_monitor_evidence_storage_status_warms_mongodb_indexes_and_write_check(tmp_path, monkeypatch):
    collection = FakeMonitorCollection()
    fake_client = FakeMonitorClient(collection)
    fake_mongo = types.ModuleType("mongo_memory")
    fake_mongo.MongoClient = fake_client
    fake_mongo._ensure_mongo_driver = lambda: True
    fake_mongo._normalized_mongodb_uri = lambda uri: uri
    monkeypatch.setitem(sys.modules, "mongo_memory", fake_mongo)
    monkeypatch.setenv("PARKPULSE_MONITOR_EVIDENCE_STORAGE", "mongodb")
    monkeypatch.setenv("MONGODB_URI", "mongodb://example.invalid/parkpulse")
    monkeypatch.setenv("PARKPULSE_MONITOR_EVIDENCE_MONGO_DATABASE", "parkpulse_monitor")
    monkeypatch.setenv("PARKPULSE_MONITOR_EVIDENCE_MONGO_TTL_SECONDS", "3600")
    monkeypatch.setenv("PARKPULSE_MONITOR_EVIDENCE_SNAPSHOT_PATH", str(tmp_path / "monitor-evidence.json"))
    main._monitor_evidence_mongo_client = None
    main._monitor_evidence_storage_status_cache = None

    status = main.monitor_evidence_storage_status(force_refresh=True)

    assert status["ready"] is True
    assert status["connected"] is True
    assert status["write_checked"] is True
    assert status["database"] == "parkpulse_monitor"
    assert "__monitor_evidence_readiness__" in collection.docs
    assert {options["name"] for _spec, options in collection.indexes} >= {
        "monitor_evidence_key_idx",
        "monitor_evidence_source_fingerprint_idx",
        "monitor_evidence_created_ttl_idx",
    }


def test_monitor_evidence_mongodb_snapshot_rejects_stale_source(tmp_path, monkeypatch):
    collection = FakeMonitorCollection()
    fake_client = FakeMonitorClient(collection)
    fake_mongo = types.ModuleType("mongo_memory")
    fake_mongo.MongoClient = fake_client
    fake_mongo._ensure_mongo_driver = lambda: True
    fake_mongo._normalized_mongodb_uri = lambda uri: uri
    monkeypatch.setitem(sys.modules, "mongo_memory", fake_mongo)
    monkeypatch.setenv("PARKPULSE_MONITOR_EVIDENCE_STORAGE", "mongodb")
    monkeypatch.setenv("MONGODB_URI", "mongodb://example.invalid/parkpulse")
    monkeypatch.setenv("PARKPULSE_MONITOR_EVIDENCE_SNAPSHOT_PATH", str(tmp_path / "monitor-evidence.json"))
    main._monitor_evidence_mongo_client = None
    main._monitor_evidence_cache.clear()
    main._monitor_evidence_storage_status_cache = None

    stale_graph = {"source_watermark": {"fingerprint": "old"}, "cases": [{"case_id": "case-1"}]}
    assert main._write_monitor_evidence_mongo_snapshot(40, stale_graph) is True

    assert main._read_monitor_evidence_mongo_snapshot(40, {"fingerprint": "new"}) is None
