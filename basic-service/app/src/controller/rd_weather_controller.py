"""Read-only weather REST and stateless Streamable HTTP MCP endpoints."""
import json

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from src.controller.rd_controller import RdRoute
from src.service.rd_platform.weather import WeatherService

router = APIRouter(prefix="/api/rd/assistant/weather", tags=["assistant-weather"], route_class=RdRoute)
_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}
_TOOL = {
    "name": "get_current_weather",
    "description": "读取洛阳市涧西区的最新可用天气预报及来源时间；不修改业务数据。",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
}


def _weather(request):
    service = getattr(request.app.state, "rd_weather", None)
    if service is None:
        service = WeatherService.from_env()
        request.app.state.rd_weather = service
    return service


@router.get("")
async def weather(request: Request):
    return await _weather(request).get()


@router.post("/mcp")
async def weather_mcp(request: Request):
    def error(code, message, request_id=None, status=200):
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}, status_code=status)

    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        return error(-32700, "Parse error", status=400)
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str):
        return error(-32600, "Invalid Request", status=400)
    request_id = payload.get("id")
    if isinstance(request_id, bool) or (request_id is not None and not isinstance(request_id, (str, int))):
        return error(-32600, "Invalid Request", status=400)
    version = request.headers.get("MCP-Protocol-Version")
    if version and version not in _VERSIONS:
        return error(-32600, "Unsupported protocol version", request_id, 400)
    method, params = payload["method"], payload.get("params", {})
    if not isinstance(params, dict):
        return error(-32602, "Invalid params", request_id)
    if "id" not in payload:
        return Response(status_code=202)
    if method == "initialize":
        requested = params.get("protocolVersion")
        if not isinstance(requested, str):
            return error(-32602, "Invalid protocol version", request_id)
        result = {"protocolVersion": requested if requested in _VERSIONS else "2025-03-26",
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "jianxi-weather", "version": "1.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [_TOOL]}
    elif method == "tools/call":
        if params.get("name") != "get_current_weather" or params.get("arguments", {}) != {}:
            return error(-32602, "Unknown tool or invalid arguments", request_id)
        current = await _weather(request).get()
        result = {"content": [{"type": "text", "text": json.dumps(current, ensure_ascii=False)}],
                  "isError": current["status"] != "ok"}
    else:
        return error(-32601, "Method not found", request_id)
    return {"jsonrpc": "2.0", "id": request_id, "result": result}
