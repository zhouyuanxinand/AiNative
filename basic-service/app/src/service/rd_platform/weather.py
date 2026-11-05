"""Cached Jianxi weather; external data never becomes a case business fact."""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

LOCATION = "洛阳 · 涧西区"
LATITUDE, LONGITUDE = 34.65878, 112.3866
CURRENT_VARIABLES = ["temperature_2m", "apparent_temperature", "is_day", "weather_code", "wind_speed_10m"]
MET_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
MET_SOURCE_URL = "https://api.met.no/doc/Locationforecast"
DEFAULT_USER_AGENT = "JianxiWeather/1.0 (+https://gitee.com/JonSm/ai-zhonghang)"
MET_MAX_AGE_SECONDS = 3 * 3600
CURRENT_MAX_AGE_SECONDS = 2 * 3600
MET_CONDITIONS = {
    "clearsky": (0, "晴"), "fair": (1, "晴间多云"), "partlycloudy": (2, "多云"),
    "cloudy": (3, "阴"), "fog": (45, "雾"),
    "lightrain": (61, "小雨"), "rain": (63, "雨"), "heavyrain": (65, "大雨"),
    "lightsnow": (71, "小雪"), "snow": (73, "雪"), "heavysnow": (75, "大雪"),
    "lightrainshowers": (80, "小阵雨"), "rainshowers": (81, "阵雨"), "heavyrainshowers": (82, "强阵雨"),
    "lightsnowshowers": (85, "小阵雪"), "snowshowers": (86, "阵雪"), "heavysnowshowers": (86, "强阵雪"),
}


def _now():
    return datetime.now(timezone.utc)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("Invalid weather measurement")
    return value


def _optional_number(value):
    return None if value is None else _number(value)


def _object(value):
    if not isinstance(value, dict):
        raise TypeError("Expected weather response object")
    return value


def _timestamp(value, offset_seconds=0):
    if not isinstance(value, str):
        raise TypeError("Missing weather timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone(timedelta(seconds=offset_seconds)))


def _fresh_timestamp(value, *, max_age, future_limit, offset_seconds=0):
    timestamp = _timestamp(value, offset_seconds)
    age = (_now() - timestamp).total_seconds()
    if age > max_age or age < -future_limit:
        raise ValueError("Weather timestamp is outside the current period")
    return timestamp.isoformat()


def _check_location(latitude, longitude):
    # Providers return the selected forecast grid cell, rather than the exact requested point.
    if abs(_number(latitude) - LATITUDE) > 0.25 or abs(_number(longitude) - LONGITUDE) > 0.25:
        raise ValueError("Weather location mismatch")


def _open_meteo_weather(payload):
    _check_location(payload["latitude"], payload["longitude"])
    current, units = _object(payload["current"]), _object(payload["current_units"])
    if units.get("temperature_2m") != "°C" or units.get("wind_speed_10m") != "km/h":
        raise ValueError("Unexpected weather units")
    if current.get("apparent_temperature") is not None and units.get("apparent_temperature") != "°C":
        raise ValueError("Unexpected apparent temperature unit")
    code = _number(current["weather_code"])
    if int(code) != code or not 0 <= code <= 99 or current.get("is_day") not in (0, 1):
        raise ValueError("Invalid weather classification")
    return {
        "temperature_c": _number(current["temperature_2m"]),
        "apparent_temperature_c": _optional_number(current.get("apparent_temperature")),
        "weather_code": int(code), "is_day": bool(current["is_day"]),
        "wind_speed_kmh": _optional_number(current.get("wind_speed_10m")),
        "observed_at": _fresh_timestamp(current["time"], max_age=CURRENT_MAX_AGE_SECONDS, future_limit=1800,
                                        offset_seconds=payload.get("utc_offset_seconds", 28800)),
    }


def _met_weather(payload):
    coordinates = payload["geometry"]["coordinates"]
    _check_location(coordinates[1], coordinates[0])
    properties = payload["properties"]
    units = _object(properties["meta"]["units"])
    if units.get("air_temperature") != "celsius" or units.get("wind_speed") != "m/s":
        raise ValueError("Unexpected weather units")
    rows = properties["timeseries"]
    if not rows:
        raise ValueError("Empty forecast")
    now = _now()
    current = rows[0]
    for row in rows:
        if _timestamp(row["time"]) > now:
            break
        current = row
    data = current["data"]
    details = _object(data["instant"]["details"])
    symbol = next((data[period]["summary"]["symbol_code"] for period in
                   ("next_1_hours", "next_6_hours", "next_12_hours") if period in data), "")
    base = re.sub(r"_(day|night|polartwilight)$", "", symbol)
    if "thunder" in base:
        code, condition = 95, "雷阵雨" if "snow" not in base and "sleet" not in base else "雷电伴雨雪"
    elif "sleet" in base:
        code, condition = None, "雨夹雪"
    else:
        code, condition = MET_CONDITIONS.get(base, (None, "天气状况暂缺"))
    wind = _optional_number(details.get("wind_speed"))
    return {
        "temperature_c": _number(details["air_temperature"]), "apparent_temperature_c": None,
        "weather_code": code, "condition": condition, "raw_symbol": symbol,
        "is_day": True if symbol.endswith("_day") else False if symbol.endswith("_night") else None,
        "wind_speed_kmh": round(wind * 3.6, 1) if wind is not None else None,
        "observed_at": _fresh_timestamp(current["time"], max_age=MET_MAX_AGE_SECONDS, future_limit=3600),
    }


class WeatherService:
    """One shared in-process cache for the REST endpoint and the MCP tool."""

    def __init__(self, *, mcp_url="", mcp_api_key="", open_meteo_api_key="", demo=False,
                 user_agent=DEFAULT_USER_AGENT, transport=None):
        self.mcp_url = mcp_url
        self.mcp_api_key = mcp_api_key
        self.open_meteo_api_key = open_meteo_api_key
        self.demo = demo
        self.user_agent = user_agent
        self.transport = transport
        self._lock = asyncio.Lock()
        self._cached = None
        self._expires_at = 0.0
        self._met_payload = None
        self._met_last_modified = ""
        self._met_expires_at = 0.0

    @classmethod
    def from_env(cls):
        return cls(
            mcp_url=os.getenv("JTB_WEATHER_MCP_URL", "").strip(),
            mcp_api_key=os.getenv("JTB_WEATHER_MCP_API_KEY", "").strip(),
            open_meteo_api_key=os.getenv("JTB_WEATHER_OPEN_METEO_API_KEY", "").strip(),
            demo=os.getenv("JTB_WEATHER_DEMO", "") == "1",
            user_agent=os.getenv("JTB_WEATHER_USER_AGENT", "").strip() or DEFAULT_USER_AGENT,
        )

    def _source(self):
        if self.mcp_url:
            return "Open-Meteo MCP", "https://open-meteo.com/", "天气通过配置的 MCP 服务获取。"
        if self.open_meteo_api_key:
            return "Open-Meteo", "https://open-meteo.com/", "天气来自 Open-Meteo 商业接口。"
        if self.demo:
            return "Open-Meteo（演示）", "https://open-meteo.com/", "演示数据源仅供非商业测试；企业部署请使用默认 MET Norway 或配置商业服务。"
        return "MET Norway · 预报", MET_SOURCE_URL, "MET Norway · CC BY 4.0；天气预报经中文归类与单位换算，非气象站实况。"

    async def get(self):
        async with self._lock:
            if self._cached is not None and time.monotonic() < self._expires_at:
                return dict(self._cached)
            source, source_url, notice = self._source()
            try:
                async with asyncio.timeout(10), httpx.AsyncClient(
                    timeout=httpx.Timeout(7, connect=4), transport=self.transport, trust_env=False,
                    headers={"User-Agent": self.user_agent},
                ) as client:
                    if self.mcp_url:
                        weather = _open_meteo_weather(await self._mcp_forecast(client))
                    elif self.open_meteo_api_key or self.demo:
                        weather = _open_meteo_weather(await self._open_meteo_forecast(client))
                    else:
                        weather = _met_weather(await self._met_forecast(client))
                result = {"status": "ok", "location": LOCATION, **weather, "fetched_at": _now().isoformat(),
                          "source": source, "source_url": source_url, "notice": notice}
                if source.startswith("MET Norway"):
                    result["license_url"] = "https://creativecommons.org/licenses/by/4.0/"
                max_age = MET_MAX_AGE_SECONDS if source.startswith("MET Norway") else CURRENT_MAX_AGE_SECONDS
                remaining = max_age - (_now() - _timestamp(weather["observed_at"])).total_seconds()
                ttl = max(0, min(600, remaining))
            except (httpx.HTTPError, TimeoutError, ValueError, TypeError, KeyError, IndexError):
                result = {"status": "unavailable", "location": LOCATION, "source": source,
                          "source_url": source_url, "notice": "天气暂时未能获取，稍后会再试。"}
                ttl = 60
            self._cached, self._expires_at = result, time.monotonic() + ttl
            return dict(result)

    async def _met_forecast(self, client):
        if self._met_payload is not None and time.monotonic() < self._met_expires_at:
            return self._met_payload
        headers = {"If-Modified-Since": self._met_last_modified} if self._met_last_modified else {}
        response = await client.get(MET_URL, params={"lat": "34.6588", "lon": "112.3866"},
                                    headers=headers, follow_redirects=True)
        if response.status_code == 304 and self._met_payload is not None:
            payload = self._met_payload
        else:
            response.raise_for_status()
            payload = response.json()
            _met_weather(payload)
        expires = response.headers.get("Expires")
        lifetime = max(600, (parsedate_to_datetime(expires) - _now()).total_seconds()) if expires else 600
        self._met_payload = payload
        self._met_expires_at = time.monotonic() + lifetime
        self._met_last_modified = response.headers.get("Last-Modified", self._met_last_modified)
        return payload

    async def _open_meteo_forecast(self, client):
        url = "https://customer-api.open-meteo.com/v1/forecast" if self.open_meteo_api_key else "https://api.open-meteo.com/v1/forecast"
        params = {"latitude": LATITUDE, "longitude": LONGITUDE, "current": ",".join(CURRENT_VARIABLES),
                  "timezone": "Asia/Shanghai", "forecast_days": 1}
        if self.open_meteo_api_key:
            params["apikey"] = self.open_meteo_api_key
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    async def _mcp_forecast(self, client):
        """Streamable HTTP with a fixed read-only Open-Meteo weather_forecast tool."""
        headers = {"Accept": "application/json, text/event-stream"}
        if self.mcp_api_key:
            headers["Authorization"] = "Bearer " + self.mcp_api_key

        async def rpc(method, params, request_id=None):
            body = {"jsonrpc": "2.0", "method": method, "params": params}
            if request_id is not None:
                body["id"] = request_id
            async with client.stream("POST", self.mcp_url, json=body, headers=headers) as response:
                response.raise_for_status()
                if response.headers.get("Mcp-Session-Id"):
                    headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
                if request_id is None:
                    return None
                if "text/event-stream" in response.headers.get("Content-Type", ""):
                    data = []
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data.append(line[5:].lstrip())
                        elif not line and data:
                            envelope = _object(json.loads("\n".join(data)))
                            data = []
                            if envelope.get("id") == request_id:
                                break
                    else:
                        raise ValueError("Missing MCP response")
                else:
                    envelope = _object(json.loads(await response.aread()))
                if envelope.get("id") != request_id or "error" in envelope:
                    raise ValueError("MCP request failed")
                return _object(envelope["result"])

        try:
            initialized = await rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "jianxi-weather", "version": "1.0"}}, 1)
            version = initialized["protocolVersion"]
            if version not in {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}:
                raise ValueError("Unsupported MCP version")
            headers["MCP-Protocol-Version"] = version
            await rpc("notifications/initialized", {})
            result = await rpc("tools/call", {"name": "weather_forecast", "arguments": {
                "latitude": LATITUDE, "longitude": LONGITUDE, "current": CURRENT_VARIABLES,
                "timezone": "Asia/Shanghai", "forecast_days": 1}}, 2)
            if result.get("isError"):
                raise ValueError("Weather tool failed")
            if isinstance(result.get("structuredContent"), dict):
                return result["structuredContent"]
            for content in result.get("content", []):
                if _object(content).get("type") == "text":
                    return json.loads(content["text"])
            raise ValueError("Missing weather tool data")
        finally:
            if "Mcp-Session-Id" in headers:
                try:
                    await client.delete(self.mcp_url, headers=headers, timeout=1)
                except httpx.HTTPError:
                    pass
