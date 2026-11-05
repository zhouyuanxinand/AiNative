"""Same-site service settings, shared behavior with the mail/intelligence platforms."""
import asyncio
import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from jonhon_taskbook import llm_client
from jonhon_taskbook.model_probe import run_probe, validate_probe_payload
from jonhon_taskbook.service_credentials import ActiveCredentialError, get_credential_store, validate_credentials

router = APIRouter(prefix="/api/settings/credentials", tags=["service-credentials"])
_NO_CACHE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _response(data, status=200):
    return JSONResponse(data, status_code=status, headers=_NO_CACHE)


def _allowed(request: Request) -> bool:
    return request.headers.get("X-Credential-Settings") == "1" and request.headers.get("Sec-Fetch-Site") != "cross-site"


@router.get('/default-model')
async def get_default_model(request: Request):
    if not _allowed(request):
        return _response({'error': '请从平台的凭证设置入口访问。'}, 403)
    try:
        return _response(await asyncio.to_thread(llm_client.get_default_model_setting))
    except (OSError, sqlite3.Error, ValueError):
        return _response({'error': '默认模型读取失败，请重试。'}, 503)


@router.put('/default-model')
async def put_default_model(request: Request):
    if not _allowed(request):
        return _response({'error': '请从平台的凭证设置入口访问。'}, 403)
    try:
        data = await asyncio.to_thread(llm_client.save_default_model_setting, await request.json())
        return _response(data)
    except llm_client.ModelCatalogUnavailable as error:
        return _response({'error': str(error)}, error.status_code)
    except (ValueError, TypeError):
        return _response({'error': '模型未保存，请从当前环境的可用模型目录重新选择完整模型。'}, 400)
    except (OSError, sqlite3.Error):
        return _response({'error': '默认模型未保存，请检查数据目录后重试。'}, 503)


async def _test_credentials(request: Request, *, catalog: bool):
    if not _allowed(request):
        return _response({"error": "请从平台的凭证设置入口访问。"}, 403)
    try:
        payload = validate_probe_payload(await request.json(), catalog=catalog)
    except (ValueError, TypeError):
        return _response({"error": "测试参数格式不正确：请完整填写有效凭证，并选择要测试的模型。"}, 400)
    return _response(await run_probe(payload, catalog=catalog))


@router.post("/test/models")
async def get_test_models(request: Request):
    return await _test_credentials(request, catalog=True)


@router.post("/test")
async def test_credentials(request: Request):
    return await _test_credentials(request, catalog=False)


@router.get("")
async def get_credentials(request: Request):
    if not _allowed(request):
        return _response({"error": "请从平台的凭证设置入口访问。"}, 403)
    try:
        data = await asyncio.to_thread(get_credential_store().view, llm_client.get_service_credential_defaults())
        return _response(data)
    except (OSError, sqlite3.Error, ValueError):
        return _response({"error": "凭证读取失败，请检查服务端数据目录后重试。"}, 503)


@router.put("")
async def put_credentials(request: Request):
    if not _allowed(request):
        return _response({"error": "请从平台的凭证设置入口访问。"}, 403)
    try:
        payload = validate_credentials(await request.json())
        llm_client.validate_service_credentials(payload)
    except (ValueError, TypeError):
        return _response({"error": "凭证格式不正确：请完整填写各组字段，地址须为 HTTP(S)，或恢复部署默认。"}, 400)
    try:
        data = await asyncio.to_thread(get_credential_store().save, payload, llm_client.get_service_credential_defaults())
    except (OSError, sqlite3.Error, ValueError):
        return _response({"error": "凭证未保存，请检查服务端数据目录的写入权限后重试。"}, 503)
    llm_client.clear_runtime_config()
    return _response(data)


@router.post("/history/{history_id}/activate")
async def activate_credentials(history_id: str, request: Request):
    if not _allowed(request):
        return _response({"error": "请从平台的凭证设置入口访问。"}, 403)
    try:
        data = await asyncio.to_thread(
            get_credential_store().activate, history_id, llm_client.get_service_credential_defaults(),
            llm_client.validate_service_credentials,
        )
    except KeyError:
        return _response({"error": "历史凭证不存在或已删除，请刷新后重试。"}, 404)
    except (OSError, sqlite3.Error, ValueError):
        return _response({"error": "凭证未切换，请检查服务端数据目录后重试。"}, 503)
    llm_client.clear_runtime_config()
    return _response(data)


@router.delete("/history/{history_id}")
async def delete_credential_history(history_id: str, request: Request):
    if not _allowed(request):
        return _response({"error": "请从平台的凭证设置入口访问。"}, 403)
    try:
        data = await asyncio.to_thread(
            get_credential_store().delete, history_id, llm_client.get_service_credential_defaults(),
        )
    except KeyError:
        return _response({"error": "历史凭证不存在或已删除，请刷新后重试。"}, 404)
    except ActiveCredentialError:
        return _response({"error": "当前使用的凭证不能删除，请先切换到其他凭证。"}, 409)
    except (OSError, sqlite3.Error, ValueError):
        return _response({"error": "历史凭证未删除，请检查服务端数据目录后重试。"}, 503)
    return _response(data)
