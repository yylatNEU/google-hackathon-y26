from __future__ import annotations

import json
import os
import ssl
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from live_feedback_loop import ingest_live_feed_event


OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def weather_feed_config() -> dict[str, Any]:
    return {
        "provider": "open_meteo",
        "latitude": _float_env("PARKPULSE_WEATHER_LATITUDE", 28.3852),
        "longitude": _float_env("PARKPULSE_WEATHER_LONGITUDE", -81.5639),
        "location_label": os.getenv("PARKPULSE_WEATHER_LOCATION_LABEL", "Park operations area"),
        "timeout_seconds": _int_env("PARKPULSE_WEATHER_FEED_TIMEOUT_SECONDS", 8),
        "source_url": OPEN_METEO_FORECAST_URL,
        "variables": [
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "precipitation",
            "rain",
            "weather_code",
            "cloud_cover",
            "wind_speed_10m",
            "wind_gusts_10m",
            "is_day",
        ],
        "boundary": "Weather is an input fact source only. Ride closure, guest messaging, and dispatch still require ParkPulse policy gates and human review where applicable.",
    }


def _weather_url(config: dict[str, Any]) -> str:
    params = {
        "latitude": config["latitude"],
        "longitude": config["longitude"],
        "current": ",".join(config["variables"]),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "auto",
        "forecast_days": 1,
    }
    return f"{OPEN_METEO_FORECAST_URL}?{urlencode(params)}"


def fetch_open_meteo_weather(config: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = config or weather_feed_config()
    url = _weather_url(resolved)
    request = Request(url, headers={"user-agent": "ParkPulse/1.0 live weather feed"})
    with urlopen(request, timeout=int(resolved.get("timeout_seconds") or 8), context=_ssl_context()) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {
        "status": "fetched",
        "mode": "open_meteo_weather_fetch",
        "fetched_at": _now_iso(),
        "provider": "open_meteo",
        "url": url,
        "config": {key: value for key, value in resolved.items() if key != "variables"},
        "payload": payload,
    }


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _weather_code_label(code: int | None) -> str:
    if code is None:
        return "unknown"
    if code in {0}:
        return "clear"
    if code in {1, 2, 3}:
        return "cloud_cover"
    if code in {45, 48}:
        return "fog"
    if code in {51, 53, 55, 56, 57}:
        return "drizzle"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow"
    if code in {95, 96, 99}:
        return "thunderstorm"
    return f"wmo_{code}"


def _risk_from_weather(current: dict[str, Any]) -> dict[str, Any]:
    code = _safe_int(current.get("weather_code"))
    apparent = _safe_float(current.get("apparent_temperature"))
    precipitation = _safe_float(current.get("precipitation"))
    rain = _safe_float(current.get("rain"))
    wind_gust = _safe_float(current.get("wind_gusts_10m"))
    storm_risk = 10
    if code in {95, 96, 99}:
        storm_risk = 92
    elif code in {80, 81, 82}:
        storm_risk = 68
    elif code in {61, 63, 65, 66, 67}:
        storm_risk = 54
    elif precipitation >= 0.05 or rain >= 0.05:
        storm_risk = 50
    elif wind_gust >= 35:
        storm_risk = 45
    heat_risk = "critical" if apparent >= 105 else "high" if apparent >= 95 else "watch" if apparent >= 88 else "normal"
    return {
        "weather_label": _weather_code_label(code),
        "storm_risk_pct": storm_risk,
        "heat_risk": heat_risk,
        "lightning_window": code in {95, 96, 99},
        "outdoor_ride_review_required": code in {95, 96, 99} or wind_gust >= 35 or apparent >= 105,
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any) -> int | None:
    try:
        if value in {None, ""}:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def build_weather_live_feed_events(fetch_result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = fetch_result.get("payload", {}) if isinstance(fetch_result.get("payload"), dict) else {}
    current = payload.get("current", {}) if isinstance(payload.get("current"), dict) else {}
    config = fetch_result.get("config", {}) if isinstance(fetch_result.get("config"), dict) else {}
    observed_at = str(current.get("time") or fetch_result.get("fetched_at") or _now_iso())
    location_label = str(config.get("location_label") or "Park operations area")
    risk = _risk_from_weather(current)
    source_url = str(fetch_result.get("url") or OPEN_METEO_FORECAST_URL)
    base_value = {
        "location": location_label,
        "provider": "open_meteo",
        "temperature_f": current.get("temperature_2m"),
        "humidity_pct": current.get("relative_humidity_2m"),
        "heat_index_f": current.get("apparent_temperature"),
        "precipitation_in": current.get("precipitation"),
        "rain_in": current.get("rain"),
        "weather_code": current.get("weather_code"),
        "weather_label": risk["weather_label"],
        "cloud_cover_pct": current.get("cloud_cover"),
        "wind_speed_mph": current.get("wind_speed_10m"),
        "wind_gust_mph": current.get("wind_gusts_10m"),
        "is_day": current.get("is_day"),
        "storm_risk_pct": risk["storm_risk_pct"],
        "heat_risk": risk["heat_risk"],
        "lightning_window": risk["lightning_window"],
        "outdoor_ride_review_required": risk["outdoor_ride_review_required"],
    }
    confidence = 0.91 if current else 0.35
    return [
        {
            "source": "weather",
            "source_event_id": f"open-meteo-weather-state:{observed_at}",
            "observed_at": observed_at,
            "entity_type": "park",
            "entity_id": "weather",
            "signal_type": "weather_state",
            "value": base_value,
            "confidence": confidence,
            "raw_payload_ref": source_url,
            "raw": {"provider": "open_meteo", "current_units": payload.get("current_units", {})},
        },
        {
            "source": "weather",
            "source_event_id": f"open-meteo-storm-risk:{observed_at}",
            "observed_at": observed_at,
            "entity_type": "park",
            "entity_id": "outdoor_operations",
            "signal_type": "storm_risk",
            "value": {key: base_value[key] for key in ["storm_risk_pct", "weather_label", "lightning_window", "precipitation_in", "wind_gust_mph"]},
            "confidence": confidence,
            "raw_payload_ref": source_url,
            "raw": {"provider": "open_meteo"},
        },
        {
            "source": "weather",
            "source_event_id": f"open-meteo-heat-index:{observed_at}",
            "observed_at": observed_at,
            "entity_type": "park",
            "entity_id": "guest_comfort",
            "signal_type": "heat_index",
            "value": {key: base_value[key] for key in ["temperature_f", "humidity_pct", "heat_index_f", "heat_risk"]},
            "confidence": confidence,
            "raw_payload_ref": source_url,
            "raw": {"provider": "open_meteo"},
        },
    ]


def ingest_live_weather_feed() -> dict[str, Any]:
    fetch_result = fetch_open_meteo_weather()
    events = build_weather_live_feed_events(fetch_result)
    ingested = [ingest_live_feed_event(event) for event in events]
    review_cases = [item.get("review_case") for item in ingested if item.get("review_case")]
    return {
        "status": "loaded" if ingested else "empty",
        "mode": "live_weather_feed_load",
        "loaded_at": _now_iso(),
        "provider": "open_meteo",
        "event_count": len(ingested),
        "review_case_count": len(review_cases),
        "events": [item.get("event") for item in ingested],
        "review_cases": review_cases,
        "fetch": {key: fetch_result.get(key) for key in ["status", "mode", "fetched_at", "provider", "url", "config"]},
        "boundary": weather_feed_config()["boundary"],
    }
