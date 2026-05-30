from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
SYNTHETIC_KNOWLEDGE_PATH = BASE_DIR / "synthetic_data" / "park_synthetic_knowledge.json"
TOKEN_STOPWORDS = {"the", "and", "for", "with", "near", "from", "that", "this", "while", "into", "are", "was", "were", "has", "have", "had", "not", "but", "out", "all", "show", "give"}


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_synthetic_park_knowledge() -> dict[str, Any]:
    data = _load_json(SYNTHETIC_KNOWLEDGE_PATH)
    return deepcopy(data)


def _tokens(value: Any) -> set[str]:
    if isinstance(value, str):
        text = value.lower()
    elif isinstance(value, list):
        text = " ".join(str(item).lower() for item in value)
    elif isinstance(value, dict):
        text = json.dumps(value, sort_keys=True).lower()
    else:
        text = str(value).lower() if value is not None else ""
    normalized = text.replace("_", " ").replace("-", " ").replace("/", " ")
    return {
        token
        for token in (raw.strip(".,:;!?()[]{}\"'") for raw in normalized.split())
        if len(token) >= 3 and token not in TOKEN_STOPWORDS
    }


def _example_search_text(example: dict[str, Any]) -> list[Any]:
    return [
        example.get("id"),
        example.get("domain"),
        example.get("utterances", []),
        example.get("expected_owner"),
        example.get("expected_case_id"),
        example.get("expected_action"),
        example.get("expected_answer_facts", []),
        example.get("hard_constraints", []),
        example.get("evaluation_assertions", []),
    ]


def retrieve_synthetic_park_context(message: str, compact_state: dict[str, Any] | None = None, limit: int = 6) -> dict[str, Any]:
    compact_state = compact_state or {}
    dataset = get_synthetic_park_knowledge()
    query_tokens = _tokens(message)
    query_tokens |= _tokens(compact_state.get("scenario"))
    for zone in compact_state.get("top_zones", []) or []:
        if isinstance(zone, dict):
            query_tokens |= _tokens([zone.get("id"), zone.get("name")])
    for ride in compact_state.get("constrained_rides", []) or []:
        if isinstance(ride, dict):
            query_tokens |= _tokens([ride.get("id"), ride.get("name"), ride.get("status")])

    object_matches: list[dict[str, Any]] = []
    for obj in dataset.get("park_objects", []) or []:
        if not isinstance(obj, dict):
            continue
        searchable = [obj.get("id"), obj.get("name"), obj.get("type"), obj.get("aliases", []), obj.get("facts", []), obj.get("adjacent", [])]
        object_tokens: set[str] = set()
        for value in searchable:
            object_tokens |= _tokens(value)
        overlap = sorted(query_tokens & object_tokens)
        if overlap:
            object_matches.append(
                {
                    "id": obj.get("id"),
                    "name": obj.get("name"),
                    "type": obj.get("type"),
                    "score": len(overlap) * 10,
                    "matched_terms": overlap[:10],
                    "facts": obj.get("facts", [])[:4],
                    "adjacent": obj.get("adjacent", [])[:6],
                    "allowed_actions": obj.get("allowed_actions", [])[:6],
                }
            )

    example_matches: list[dict[str, Any]] = []
    lowered = (message or "").lower()
    for example in dataset.get("operator_examples", []) or []:
        if not isinstance(example, dict):
            continue
        example_tokens: set[str] = set()
        for value in _example_search_text(example):
            example_tokens |= _tokens(value)
        overlap = sorted(query_tokens & example_tokens)
        exact_utterance_hits = [
            utterance
            for utterance in example.get("utterances", []) or []
            if isinstance(utterance, str) and utterance.lower() in lowered
        ]
        score = len(overlap) * 10 + (400 if exact_utterance_hits else 0)
        if score > 0:
            example_matches.append(
                {
                    "id": example.get("id"),
                    "domain": example.get("domain"),
                    "score": score,
                    "matched_terms": sorted(set([*overlap, *exact_utterance_hits]))[:14],
                    "expected_owner": example.get("expected_owner"),
                    "expected_case_id": example.get("expected_case_id"),
                    "expected_action": example.get("expected_action"),
                    "expected_gate": example.get("expected_gate"),
                    "expected_answer_facts": example.get("expected_answer_facts", [])[:6],
                    "hard_constraints": example.get("hard_constraints", [])[:6],
                    "evaluation_assertions": example.get("evaluation_assertions", [])[:8],
                }
            )

    object_matches.sort(key=lambda item: int(item.get("score") or 0), reverse=True)
    example_matches.sort(key=lambda item: int(item.get("score") or 0), reverse=True)
    primary_example = example_matches[0] if example_matches else None
    return {
        "dataset_id": dataset.get("dataset_id"),
        "version": dataset.get("version"),
        "retrieval_status": "matched" if object_matches or example_matches else "no_match",
        "query_terms": sorted(query_tokens)[:24],
        "matched_objects": object_matches[:limit],
        "matched_examples": example_matches[:limit],
        "primary_example": primary_example,
        "coverage": synthetic_coverage_report(dataset),
    }


def synthetic_coverage_report(dataset: dict[str, Any] | None = None) -> dict[str, Any]:
    dataset = dataset or get_synthetic_park_knowledge()
    examples = [item for item in dataset.get("operator_examples", []) or [] if isinstance(item, dict)]
    objects = [item for item in dataset.get("park_objects", []) or [] if isinstance(item, dict)]
    domains = sorted({str(item.get("domain")) for item in examples if item.get("domain")})
    utterance_count = sum(len(item.get("utterances", []) or []) for item in examples)
    case_ids = sorted({str(item.get("expected_case_id")) for item in examples if item.get("expected_case_id")})
    return {
        "object_count": len(objects),
        "example_count": len(examples),
        "utterance_count": utterance_count,
        "domain_count": len(domains),
        "domains": domains,
        "expected_case_count": len(case_ids),
        "expected_case_ids": case_ids,
        "time_pattern_count": len(dataset.get("time_patterns", []) or []),
    }
