"""Weather transport, freshness, and HTTP contract without external services."""
import asyncio
import importlib
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.common.platform_auth import AuthSettings


def weather_module():
    return importlib.import_module("src.service.rd_platform.weather")


@pytest.fixture(autouse=True)
def weather_clock(monkeypatch):
    monkeypatch.setattr(weather_module(), "_now", lambda: datetime(2026, 11, 4, 3, 30, tzinfo=timezone.utc))


def forecast():
    return {
        "latitude": 34.66, "longitude": 112.38, "timezone": "Asia/Shanghai",
        "utc_offset_seconds": 28800,
        "current_units": {"time": "iso8601", "interval": "seconds", "temperature_2m": "°C",
                          "apparent_temperature": "°C", "is_day": "", "weather_code": "wmo code",
                          "wind_speed_10m": "km/h"},
        "current": {"time": "2026-11-04T11:15", "interval": 900, "temperature_2m": 17.3,
                    "apparent_temperature": 16.1, "is_day": 1, "weather_code": 3,
                    "wind_speed_10m": 8.6},
    }


def met_forecast():
    return {
        "type": "Feature", "geometry": {"type": "Point", "coordinates": [112.3866, 34.6588, 147]},
        "properties": {
            "meta": {"updated_at": "2026-11-04T02:03:00Z",
                     "units": {"air_temperature": "celsius", "wind_speed": "m/s"}},
            "timeseries": [{"time": "2026-11-04T03:00:00Z", "data": {
                "instant": {"details": {"air_temperature": 17.3, "wind_speed": 2.4}},
                "next_1_hours": {"summary": {"symbol_code": "cloudy"}, "details": {"precipitation_amount": 0.0}},
            }}],
        },
    }


@pytest.mark.asyncio
async def test_default_provider_uses_met_norway_and_marks_forecast():
    def respond(request):
        assert request.url.host == "api.met.no"
        assert request.url.params["lat"] == "34.6588"
        assert request.url.params["lon"] == "112.3866"
        assert "JianxiWeather" in request.headers["User-Agent"]
        return httpx.Response(200, json=met_forecast())

    service = weather_module().WeatherService(transport=httpx.MockTransport(respond))
    result = await service.get()
    assert result["status"] == "ok"
    assert result["location"] == "洛阳 · 涧西区"
    assert result["temperature_c"] == 17.3
    assert result["apparent_temperature_c"] is None
    assert result["weather_code"] == 3
    assert result["wind_speed_kmh"] == 8.6
    assert result["observed_at"] == "2026-11-04T03:00:00+00:00"
    assert result["source"] == "MET Norway · 预报"
    assert "CC BY" in result["notice"]


@pytest.mark.asyncio
async def test_demo_queries_jianxi_and_preserves_actual_weather_units():
    def respond(request):
        assert request.url.host == "api.open-meteo.com"
        assert request.url.params["latitude"] == "34.65878"
        assert request.url.params["longitude"] == "112.3866"
        assert request.url.params["timezone"] == "Asia/Shanghai"
        assert "apparent_temperature" in request.url.params["current"]
        return httpx.Response(200, json=forecast())

    result = await weather_module().WeatherService(demo=True, transport=httpx.MockTransport(respond)).get()
    assert result["status"] == "ok"
    assert result["temperature_c"] == 17.3
    assert result["apparent_temperature_c"] == 16.1
    assert result["weather_code"] == 3
    assert result["wind_speed_kmh"] == 8.6
    assert result["is_day"] is True
    assert result["observed_at"] == "2026-11-04T11:15:00+08:00"
    assert "MCP" not in result["source"]
    assert "非商业" in result["notice"]


@pytest.mark.asyncio
async def test_commercial_key_uses_customer_api_and_is_not_exposed():
    def respond(request):
        assert request.url.host == "customer-api.open-meteo.com"
        assert request.url.params["apikey"] == "private-test-key"
        return httpx.Response(200, json=forecast())

    result = await weather_module().WeatherService(
        open_meteo_api_key="private-test-key", transport=httpx.MockTransport(respond)
    ).get()
    assert result["status"] == "ok"
    assert "private-test-key" not in json.dumps(result)
    assert "演示" not in result["source"]


@pytest.mark.asyncio
async def test_concurrent_requests_share_cache_and_expired_data_is_refreshed(monkeypatch):
    weather = weather_module()
    ticks = [0.0]
    monkeypatch.setattr(weather.time, "monotonic", lambda: ticks[0])
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []

    async def respond(request):
        requests.append(request)
        entered.set()
        await release.wait()
        return httpx.Response(200, json=forecast())

    service = weather.WeatherService(demo=True, transport=httpx.MockTransport(respond))
    first = asyncio.create_task(service.get())
    await entered.wait()
    others = [asyncio.create_task(service.get()) for _ in range(4)]
    release.set()
    results = await asyncio.gather(first, *others)
    assert all(result["status"] == "ok" for result in results)
    assert len(requests) == 1
    ticks[0] = 599
    assert (await service.get())["fetched_at"] == results[0]["fetched_at"]
    assert len(requests) == 1
    ticks[0] = 601
    assert (await service.get())["status"] == "ok"
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "null_temperature", "wrong_units", "wrong_location", "missing_time", "null_time", "invalid_units_object"])
async def test_unavailable_upstream_never_supplies_weather_numbers(failure):
    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private endpoint and key", request=request)
        payload = forecast()
        if failure == "null_temperature":
            payload["current"]["temperature_2m"] = None
        elif failure == "wrong_units":
            payload["current_units"]["temperature_2m"] = "°F"
        elif failure == "wrong_location":
            payload["latitude"] = 51.5
        elif failure == "null_time":
            payload["current"]["time"] = None
        elif failure == "invalid_units_object":
            payload["current_units"] = []
        else:
            payload["current"].pop("time")
        return httpx.Response(200, json=payload)

    result = await weather_module().WeatherService(demo=True, transport=httpx.MockTransport(respond)).get()
    assert result["status"] == "unavailable"
    assert "temperature_c" not in result
    assert "private endpoint" not in json.dumps(result)


@pytest.mark.asyncio
async def test_met_respects_expiry_and_conditionally_revalidates(monkeypatch):
    weather = weather_module()
    ticks = [0.0]
    monkeypatch.setattr(weather.time, "monotonic", lambda: ticks[0])
    monkeypatch.setattr(weather, "_now", lambda: datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc))
    requests = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json=met_forecast(), headers={
                "Expires": "Wed, 04 Nov 2026 03:20:00 GMT", "Last-Modified": "Wed, 04 Nov 2026 02:03:00 GMT"})
        assert request.headers["If-Modified-Since"] == "Wed, 04 Nov 2026 02:03:00 GMT"
        return httpx.Response(304, headers={"Expires": "Wed, 04 Nov 2026 03:40:00 GMT"})

    service = weather.WeatherService(transport=httpx.MockTransport(respond))
    assert (await service.get())["temperature_c"] == 17.3
    ticks[0] = 601
    assert (await service.get())["temperature_c"] == 17.3
    assert len(requests) == 1
    ticks[0] = 1202
    assert (await service.get())["temperature_c"] == 17.3
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_met_sleet_and_ambiguous_daylight_remain_explicitly_unknown():
    payload = met_forecast()
    payload["properties"]["timeseries"][0]["data"]["next_1_hours"]["summary"]["symbol_code"] = "sleet"
    service = weather_module().WeatherService(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    result = await service.get()
    assert result["condition"] == "雨夹雪"
    assert result["weather_code"] is None
    assert result["is_day"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,minutes_from_now,expected", [
    ("met", -180, "ok"), ("met", -181, "unavailable"),
    ("met", 60, "ok"), ("met", 61, "unavailable"),
    ("open_meteo", -120, "ok"), ("open_meteo", -121, "unavailable"),
    ("open_meteo", 30, "ok"), ("open_meteo", 31, "unavailable"),
])
async def test_old_or_distant_future_weather_is_not_presented_as_current(provider, minutes_from_now, expected):
    timestamp = datetime(2026, 11, 4, 3, 30, tzinfo=timezone.utc) + timedelta(minutes=minutes_from_now)
    payload = met_forecast() if provider == "met" else forecast()
    if provider == "met":
        payload["properties"]["timeseries"][0]["time"] = timestamp.isoformat()
    else:
        payload["current"]["time"] = timestamp.isoformat()
    service = weather_module().WeatherService(
        demo=provider == "open_meteo",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )
    result = await service.get()
    assert result["status"] == expected
    if expected == "unavailable":
        assert "temperature_c" not in result
        assert "observed_at" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,past_limit_hours", [("met", 3), ("open_meteo", 2)])
async def test_cache_does_not_extend_weather_past_its_freshness_limit(monkeypatch, provider, past_limit_hours):
    weather = weather_module()
    now = [datetime(2026, 11, 4, 3, 30, tzinfo=timezone.utc)]
    ticks = [0.0]
    monkeypatch.setattr(weather, "_now", lambda: now[0])
    monkeypatch.setattr(weather.time, "monotonic", lambda: ticks[0])
    stamp = now[0] - timedelta(hours=past_limit_hours) + timedelta(seconds=30)
    payload = met_forecast() if provider == "met" else forecast()
    if provider == "met":
        payload["properties"]["timeseries"][0]["time"] = stamp.isoformat()
    else:
        payload["current"]["time"] = stamp.isoformat()
    service = weather.WeatherService(
        demo=provider == "open_meteo",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )
    assert (await service.get())["status"] == "ok"
    now[0] += timedelta(seconds=31)
    ticks[0] = 31
    result = await service.get()
    assert result["status"] == "unavailable"
    assert "temperature_c" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("sse", [False, True])
async def test_mcp_initializes_and_calls_weather_forecast_with_array_variables(sse):
    methods = []

    def respond(request):
        assert request.url.host == "weather.internal"
        assert request.headers["Authorization"] == "Bearer private-mcp-key"
        assert "text/event-stream" in request.headers["Accept"]
        if request.method == "DELETE":
            assert request.headers["Mcp-Session-Id"] == "test-session"
            return httpx.Response(204)
        payload = json.loads(request.content)
        methods.append(payload["method"])
        if payload["method"] == "initialize":
            assert payload["params"]["capabilities"] == {}
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "weather-test", "version": "1"}}
        elif payload["method"] == "notifications/initialized":
            assert request.headers["Mcp-Session-Id"] == "test-session"
            return httpx.Response(202)
        else:
            assert request.headers["MCP-Protocol-Version"] == "2025-03-26"
            assert request.headers["Mcp-Session-Id"] == "test-session"
            assert payload["params"]["name"] == "weather_forecast"
            args = payload["params"]["arguments"]
            assert args["latitude"] == 34.65878 and args["longitude"] == 112.3866
            assert args["timezone"] == "Asia/Shanghai"
            assert isinstance(args["current"], list)
            result = {"content": [{"type": "text", "text": json.dumps(forecast())}]}
        envelope = {"jsonrpc": "2.0", "id": payload["id"], "result": result}
        headers = {"Mcp-Session-Id": "test-session"}
        if sse:
            headers["Content-Type"] = "text/event-stream"
            return httpx.Response(200, text="event: message\ndata: " + json.dumps(envelope) + "\n\n", headers=headers)
        return httpx.Response(200, json=envelope, headers=headers)

    result = await weather_module().WeatherService(
        mcp_url="http://weather.internal/mcp", mcp_api_key="private-mcp-key",
        transport=httpx.MockTransport(respond),
    ).get()
    assert result["status"] == "ok"
    assert result["temperature_c"] == 17.3
    assert "MCP" in result["source"]
    assert methods == ["initialize", "notifications/initialized", "tools/call"]
    assert "private-mcp-key" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_result", [False, True])
async def test_mcp_tool_failure_does_not_fall_back_to_demo_or_expose_details(invalid_result):
    def respond(request):
        assert request.url.host == "weather.internal"
        payload = json.loads(request.content)
        if payload["method"] == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "weather-test", "version": "1"}}
        elif payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        else:
            result = [] if invalid_result else {"isError": True, "content": [{"type": "text", "text": "private-host private-key"}]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})

    result = await weather_module().WeatherService(
        mcp_url="http://weather.internal/mcp", demo=True, transport=httpx.MockTransport(respond)
    ).get()
    assert result["status"] == "unavailable"
    assert "temperature_c" not in result
    assert "private-" not in json.dumps(result)


def test_weather_endpoint_uses_existing_identity_boundary_without_case_or_database(monkeypatch):
    controller = importlib.import_module("src.controller.rd_weather_controller")
    monkeypatch.delenv("JTB_WEATHER_MCP_URL", raising=False)
    monkeypatch.delenv("JTB_WEATHER_OPEN_METEO_API_KEY", raising=False)
    monkeypatch.delenv("JTB_WEATHER_DEMO", raising=False)
    app = FastAPI()
    app.state.auth_settings = AuthSettings(enabled=False)
    app.state.rd_weather = weather_module().WeatherService(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=met_forecast()))
    )
    app.include_router(controller.router)
    with TestClient(app) as client:
        response = client.get("/api/rd/assistant/weather")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.headers["Cache-Control"] == "no-store"
        app.state.auth_settings = AuthSettings(enabled=True)
        assert client.get("/api/rd/assistant/weather").status_code == 401


def test_builtin_mcp_exposes_real_cached_weather_and_rejects_unknown_tools():
    controller = importlib.import_module("src.controller.rd_weather_controller")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=met_forecast())

    app = FastAPI()
    app.state.auth_settings = AuthSettings(enabled=False)
    app.state.rd_weather = weather_module().WeatherService(transport=httpx.MockTransport(respond))
    app.include_router(controller.router)
    endpoint = "/api/rd/assistant/weather/mcp"
    with TestClient(app) as client:
        initialized = client.post(endpoint, json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "weather-test", "version": "1"}}})
        assert initialized.json()["result"]["protocolVersion"] == "2025-03-26"
        assert client.post(endpoint, json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
        listed = client.post(endpoint, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()
        assert listed["result"]["tools"][0]["name"] == "get_current_weather"
        called = client.post(endpoint, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "get_current_weather", "arguments": {}}}).json()
        result = json.loads(called["result"]["content"][0]["text"])
        assert result["temperature_c"] == 17.3
        assert result["source"] == "MET Norway · 预报"
        assert client.get("/api/rd/assistant/weather").json() == result
        assert len(requests) == 1
        unknown = client.post(endpoint, json={"jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "write_business_data", "arguments": {}}}).json()
        assert unknown["error"]["code"] == -32602
        invalid = client.post(endpoint, json={"jsonrpc": "2.0", "id": 6, "method": "initialize",
            "params": {"protocolVersion": []}}).json()
        assert invalid["error"]["code"] == -32602
        assert client.get(endpoint).status_code == 405
        app.state.auth_settings = AuthSettings(enabled=True)
        assert client.post(endpoint, json={"jsonrpc": "2.0", "id": 5, "method": "tools/list"}).status_code == 401
