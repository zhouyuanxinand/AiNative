# -*- coding: utf-8 -*-
"""研制任务书受控生成 HTTP 接口层。

本模块由原 ``app.py`` 拆分而来，承载全部 31 个 ``/api`` 路由、进程内任务池、
SSE 实时日志、取消、模板候选生命周期与下载接口。业务逻辑（流水线编排、模板
登记、受控规则）仍全部位于 ``jonhon_taskbook`` 包与 ``pipeline`` 模块中，此处
仅做 HTTP 适配与路径基准替换。
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
import urllib.parse
import uuid
import zipfile
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from lxml import etree

from jonhon_taskbook import llm_client
from jonhon_taskbook.asset_lifecycle import ControlledAssetLifecycle
from jonhon_taskbook.build_fingerprint import build_fingerprint
from jonhon_taskbook.runtime_profile import public_runtime_status
from jonhon_taskbook.template_onboarding import (
    load_taxonomy,
    prepare_template_candidate,
)
from jonhon_taskbook.template_registry import (
    list_product_catalog,
    resolve_template_selection,
)

from src.utils.config_loader import AppConfig

router = APIRouter()

# ── 运行时常量与默认值 ──────────────────────────────────────────
_HISTORY_LIMIT = 12
_DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_VALID_JOB_ID = re.compile(r"^[0-9a-f]{10}$")
_MAX_TEMPLATE_EDIT_PLAN_BYTES = 256 * 1024
_MAX_BASELINE_JSON_BYTES = 2 * 1024 * 1024

_DEFAULT_PRODUCT_TYPE = "low_frequency_rectangular"
_DEFAULT_PRODUCT_DOMAIN = "military"
_DEFAULT_DEVELOPMENT_PROCESS = "全新"
_DEFAULT_ORGANIZATION_SCOPE = "non_central_research"


class _JobCancelled(RuntimeError):
    """Internal control signal for cooperative job cancellation."""


# 进程级共享状态；由 ``register(app, config)`` 在应用工厂中初始化。
class _RuntimeState:
    def __init__(self) -> None:
        self.config: AppConfig | None = None
        self.upload_dir: Path = Path()
        self.output_dir: Path = Path()
        self.template_candidate_dir: Path = Path()
        self.template_release_dir: Path = Path()
        self.config_dir: Path = Path()
        self.package_root: Path = Path()
        self.package_resources_dir: Path = Path()
        self.max_upload_bytes: int = 100 * 1024 * 1024
        self.max_concurrent_jobs: int = 2
        self.job_ttl_seconds: int = 24 * 60 * 60
        self.max_job_records: int = 100
        self.runtime_settings: dict = {}
        self.asset_lifecycle: ControlledAssetLifecycle | None = None

        self.jobs: dict[str, dict] = {}
        self.job_slots: threading.BoundedSemaphore = threading.BoundedSemaphore(2)


_STATE = _RuntimeState()


def register(_app, config: AppConfig) -> None:
    """Initialise process-level state from the application config.

    Called once by ``create_app`` after the runtime profile has been loaded.
    Restores any persisted completed jobs so downloads survive restarts.
    """
    _STATE.config = config
    _STATE.upload_dir = config.upload_dir
    _STATE.output_dir = config.output_dir
    _STATE.template_candidate_dir = config.template_candidate_dir
    _STATE.template_release_dir = config.template_release_dir
    _STATE.config_dir = config.config_dir
    _STATE.package_root = config.package_root
    _STATE.package_resources_dir = config.package_resources_dir
    _STATE.max_upload_bytes = config.max_upload_bytes
    _STATE.max_concurrent_jobs = config.max_concurrent_jobs
    _STATE.job_ttl_seconds = config.job_ttl_seconds
    _STATE.max_job_records = config.max_job_records
    _STATE.runtime_settings = config.runtime_settings
    # The semaphore cannot be resized after creation; rebuild it to honour config.
    _STATE.job_slots = threading.BoundedSemaphore(config.max_concurrent_jobs)

    _STATE.upload_dir.mkdir(parents=True, exist_ok=True)
    _STATE.output_dir.mkdir(parents=True, exist_ok=True)
    _STATE.template_candidate_dir.mkdir(parents=True, exist_ok=True)
    _STATE.template_release_dir.mkdir(parents=True, exist_ok=True)

    _STATE.asset_lifecycle = ControlledAssetLifecycle(
        candidate_root=_STATE.template_candidate_dir,
        catalog_path=_STATE.config_dir / "template_catalog.yaml",
        template_root=_STATE.package_resources_dir / "templates",
        mapping_root=_STATE.config_dir,
        profile_root=_STATE.package_root,
        audit_root=_STATE.template_release_dir,
    )
    _restore_completed_jobs()


# ── 默认本地样例路径（仅 ``JTB_ALLOW_LOCAL_PATHS=1`` 时开放） ───
def _default_local_tech() -> str:
    return str(_STATE.upload_dir.parent / "input_docs" / "技术要求_上传.docx")


def _default_local_spec() -> str:
    return str(_STATE.upload_dir.parent / "input_docs" / "产品规范_上传.docx")


# ── 任务状态记录 ─────────────────────────────────────────────────
def _job_record() -> dict:
    now = time.time()
    return {
        "status": "queued",
        "cancel_requested": False,
        "log": [],
        "result": {
            "meta": {
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "runtime_process_id": os.getpid(),
            }
        },
        "error": "",
        "created_ts": now,
        "updated_ts": now,
        "started_ts": None,
        "stage": "排队等待执行",
        "last_log_ts": None,
    }


def _finish_cancelled_job(job: dict) -> None:
    now = time.time()
    job["status"] = "cancelled"
    job["stage"] = "本次任务已安全终止"
    job["updated_ts"] = now
    job["last_log_ts"] = now
    message = "⏹ 本次任务已安全终止；未继续执行后续装配和交付步骤"
    if not job["log"] or job["log"][-1] != message:
        job["log"].append(message)


def _raise_if_cancelled(job: dict) -> None:
    if job.get("cancel_requested"):
        raise _JobCancelled("用户终止本次任务")


def _get_job(jid: str) -> dict | None:
    if not _VALID_JOB_ID.fullmatch(jid or ""):
        return None
    return _STATE.jobs.get(jid)


def _job_artifact(jid: str, kind: str) -> Path | None:
    job = _get_job(jid)
    if not job or job.get("status") not in {"done", "blocked"}:
        return None
    key = "out" if kind == "docx" else "report"
    value = job.get("result", {}).get(key, "")
    path = Path(value) if value else None
    if not path:
        return None
    try:
        path = path.resolve()
        path.relative_to(_STATE.output_dir.resolve())
    except (OSError, ValueError):
        return None
    expected_suffix = ".docx" if kind == "docx" else ".report.html"
    if path.suffixes[-2:] != [".report", ".html"] and kind == "report":
        return None
    if kind == "docx" and path.suffix.lower() != expected_suffix:
        return None
    return path if path.is_file() else None


def _persist_job_manifest(jid: str, result: dict) -> None:
    out = Path(result.get("out", ""))
    if not out or not out.is_file():
        return

    def digest(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    report = Path(result.get("report", ""))
    artifact_hash = digest(out)
    result.setdefault("meta", {})["artifact_sha256"] = artifact_hash
    if report.is_file():
        result["meta"]["report_sha256"] = digest(report)
    sidecars = {}
    for suffix in (
        ".requirement_classification.json",
        ".semantic_plan.json",
        ".semantic_evidence.json",
        ".semantic_review.json",
        ".coverage_ledger.json",
        ".coverage_report.md",
        ".qa_gate_report.md",
        ".configured_qa_gate.json",
        ".delivery_gate.json",
        ".indicator_audit.json",
        ".process_rule_audit.json",
        ".domain_rule_audit.json",
        ".preservation.json",
        ".regression.json",
    ):
        sidecar = out.with_suffix(suffix)
        if sidecar.is_file():
            sidecars[suffix] = digest(sidecar)
    manifest = out.with_suffix(".job.json")
    job_status = "done" if result.get("ok") else "blocked"
    payload = {
        "jid": jid,
        "status": job_status,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "artifact_sha256": artifact_hash,
        "sidecar_sha256": sidecars,
        "result": result,
    }
    manifest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _restore_completed_jobs() -> None:
    for manifest in _STATE.output_dir.glob("*.job.json"):
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            jid = str(payload.get("jid", ""))
            result = payload.get("result") or {}
            if not _VALID_JOB_ID.fullmatch(jid) or not result.get("out"):
                continue
            now = manifest.stat().st_mtime
            restored_status = str(payload.get("status", "done"))
            if restored_status not in {"done", "blocked"}:
                restored_status = "done"
            _STATE.jobs[jid] = {
                "status": restored_status,
                "log": ["已从持久化任务记录恢复；可继续下载文档和报告"],
                "result": result,
                "error": "",
                "created_ts": now,
                "updated_ts": now,
                "started_ts": now,
                "stage": "已完成（重启后恢复）"
                if restored_status == "done"
                else "门禁阻断（重启后恢复）",
                "last_log_ts": now,
            }
        except (OSError, ValueError, TypeError):
            continue


def _cleanup_expired_jobs(now: float | None = None) -> None:
    now = time.time() if now is None else now
    stale = [
        jid
        for jid, job in _STATE.jobs.items()
        if job.get("status") in {"done", "blocked", "error"}
        if now - float(job.get("updated_ts", job.get("created_ts", now)))
        > _STATE.job_ttl_seconds
    ]
    if len(_STATE.jobs) - len(stale) > _STATE.max_job_records:
        survivors = sorted(
            (
                jid
                for jid, job in _STATE.jobs.items()
                if jid not in stale and job.get("status") in {"done", "blocked", "error"}
            ),
            key=lambda item: float(_STATE.jobs[item].get("updated_ts", 0)),
        )
        stale.extend(
            survivors[: max(0, len(_STATE.jobs) - len(stale) - _STATE.max_job_records)]
        )
    for jid in set(stale):
        _STATE.jobs.pop(jid, None)
        job_dir = (_STATE.upload_dir / jid).resolve()
        try:
            job_dir.relative_to(_STATE.upload_dir.resolve())
        except ValueError:
            continue
        if job_dir.is_dir():
            shutil.rmtree(job_dir, ignore_errors=True)


# ── 上传校验 ─────────────────────────────────────────────────────
def _validate_docx_payload(filename: str, data: bytes) -> str | None:
    if not (filename or "").lower().endswith(".docx"):
        return "仅支持 .docx 文件"
    if not data:
        return "文件为空"
    if len(data) > _STATE.max_upload_bytes:
        return f"文件超过 {_STATE.max_upload_bytes // (1024 * 1024)} MB 限制"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                return "文件不是有效的 Word DOCX 文档"
            if any(
                name.startswith(("/", "\\")) or ".." in Path(name).parts
                for name in names
            ):
                return "DOCX 压缩包包含不安全路径"
    except (zipfile.BadZipFile, OSError):
        return "文件不是有效的 Word DOCX 文档"
    return None


async def _read_validated_upload(upload: UploadFile) -> tuple[bytes | None, str | None]:
    data = await upload.read(_STATE.max_upload_bytes + 1)
    error = _validate_docx_payload(upload.filename or "", data)
    return (None, error) if error else (data, None)


async def _read_validated_json_upload(
    upload: UploadFile,
) -> tuple[bytes | None, str | None]:
    data = await upload.read(_MAX_BASELINE_JSON_BYTES + 1)
    if not (upload.filename or "").lower().endswith(".json"):
        return None, "仅支持 .json 文件"
    if not data:
        return None, "文件为空"
    if len(data) > _MAX_BASELINE_JSON_BYTES:
        return None, "JSON 基线超过 2 MB 限制"
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "文件不是有效的 UTF-8 JSON"
    if not isinstance(value, (dict, list)):
        return None, "JSON 基线顶层必须是对象或数组"
    return data, None


def _read_template_edit_plan(raw: str, confirmed: str) -> tuple[dict | None, str | None]:
    if not (raw or "").strip():
        return None, None
    if len(raw.encode("utf-8")) > _MAX_TEMPLATE_EDIT_PLAN_BYTES:
        return None, "章节编辑计划过大"
    if (confirmed or "").lower() != "true":
        return None, "章节编辑计划必须先预览并由用户确认"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None, "章节编辑计划不是有效 JSON"
    if not isinstance(value, dict) or not isinstance(value.get("operations"), list):
        return None, "章节编辑计划结构无效"
    return value, None


def _make_output_path() -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = _STATE.output_dir / f"研制任务书_{stamp}.docx"
    if not base.exists():
        return str(base)
    for i in range(1, 100):
        alt = _STATE.output_dir / f"研制任务书_{stamp}_{i:02d}.docx"
        if not alt.exists():
            return str(alt)
    return str(_STATE.output_dir / f"研制任务书_{stamp}_{uuid.uuid4().hex[:6]}.docx")


def _runtime_llm_config_allowed(request: Request) -> bool:
    if os.getenv("JTB_ALLOW_REMOTE_LLM_CONFIG", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _llm_submission_error(
    use_llm: str,
    model_provider: str = "",
    model_name: str = "",
    model_id: str = "",
) -> str | None:
    if (use_llm or "").lower() != "true":
        return "受控生产流程必须启用 LLM 语义路由；LLM 只做分类与定位，不生成正文"
    has_selection = bool(model_provider or model_name or model_id)
    if has_selection and not (model_provider or "").strip():
        return "模型供应方不能为空"
    if has_selection and not (model_name or "").strip():
        return "请选择模型"
    status = llm_client.get_model_status(model_provider, model_name, model_id)
    if not status.get("configured"):
        selected = (model_name or "").strip()
        if selected:
            return f"模型 {selected} 尚未配置可用凭据，请检查对应环境变量"
        return "LLM 尚未连接：请配置 MODEL_* / AI_* / JTB_LLM_*（或 Azure）后重启服务"
    return None


def _validate_process_inputs(
    development_process: str,
    product_series: str,
    organization_scope: str,
    cover_phase: str,
) -> tuple[str, str, str, str]:
    from jonhon_taskbook.cover_fields import normalize_cover_phase
    from jonhon_taskbook.development_process_policy import (
        normalize_development_process,
    )
    from jonhon_taskbook.template_variant_policy import (
        normalize_organization_scope,
    )

    process = normalize_development_process(development_process)
    series = str(product_series or "").strip()
    if len(series) > 160:
        raise ValueError("产品系列长度不能超过160个字符")
    scope = normalize_organization_scope(organization_scope)
    phase = normalize_cover_phase(cover_phase)
    if not phase:
        raise ValueError("请选择封面研制阶段：F、C、S、D 之一")
    return process, series, scope, phase


# ══════════════════════════════════════════════════════════════════
# 路由
# ══════════════════════════════════════════════════════════════════


@router.get("/api/llm/status")
async def llm_status(
    model_provider: str = "",
    model_name: str = "",
    model_id: str = "",
):
    """只返回脱敏连接状态，不返回 API Key、App-Id 或认证头。"""
    return JSONResponse(
        llm_client.get_model_status(model_provider, model_name, model_id)
    )


@router.get("/api/models")
async def model_catalog():
    """返回可选模型目录；接口结构与自动化输入审查服务保持一致。"""
    try:
        models = await asyncio.to_thread(llm_client.list_available_models)
        return JSONResponse({"success": True, "models": models})
    except (TypeError, ValueError, RuntimeError) as exc:
        return JSONResponse(
            {"success": False, "models": [], "error": str(exc)},
            status_code=500,
        )


@router.post("/api/llm/configure")
async def configure_llm(
    request: Request,
    provider: str = Form("openai_compatible"),
    endpoint: str = Form(...),
    api_key: str = Form(...),
    model: str = Form(...),
    app_id: str = Form(""),
    model_id: str = Form(""),
    tenant_id: str = Form(""),
    app_id_header: str = Form("App-Id"),
    api_key_header: str = Form("Api-Key"),
    tenant_id_header: str = Form("Tenant-Id"),
    api_version: str = Form("2024-12-01-preview"),
    timeout_seconds: float = Form(90.0),
    max_tokens: int = Form(8192),
):
    if not _runtime_llm_config_allowed(request):
        return JSONResponse({"error": "模型运行时配置仅允许从本机提交"}, status_code=403)
    try:
        config = llm_client.make_config(
            provider=provider,
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            app_id=app_id,
            model_id=model_id,
            tenant_id=tenant_id,
            app_id_header=app_id_header,
            api_key_header=api_key_header,
            tenant_id_header=tenant_id_header,
            api_version=api_version,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
        )
        status = await asyncio.to_thread(llm_client.configure_runtime, config)
        return JSONResponse({**status, "message": "连接验证通过；凭据仅保存在当前进程内存"})
    except (TypeError, ValueError, RuntimeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/api/llm/clear")
async def clear_llm(request: Request):
    if not _runtime_llm_config_allowed(request):
        return JSONResponse({"error": "模型运行时配置仅允许从本机提交"}, status_code=403)
    return JSONResponse(llm_client.clear_runtime_config())


@router.post("/api/submit_local")
async def submit_local(
    background_tasks: BackgroundTasks,
    tech: str = Form(None),
    spec: str = Form(None),
    product_type: str = Form(_DEFAULT_PRODUCT_TYPE),
    product_domain: str = Form(_DEFAULT_PRODUCT_DOMAIN),
    development_process: str = Form(_DEFAULT_DEVELOPMENT_PROCESS),
    product_series: str = Form(""),
    organization_scope: str = Form(_DEFAULT_ORGANIZATION_SCOPE),
    cover_phase: str = Form(""),
    use_llm: str = Form("true"),
    model_provider: str = Form(""),
    model_name: str = Form(""),
    model_id: str = Form(""),
    baseline_docx: str = Form(""),
    baseline_json: str = Form(""),
    fail_on_regression: str = Form("false"),
    template_edit_plan: str = Form(""),
    template_edit_confirmed: str = Form("false"),
):
    tech = tech or _default_local_tech()
    spec = spec or _default_local_spec()
    if os.getenv("JTB_ALLOW_LOCAL_PATHS", "0") != "1":
        return JSONResponse(
            {"error": "本地路径接口默认关闭；仅开发环境可设置 JTB_ALLOW_LOCAL_PATHS=1"},
            status_code=403,
        )
    llm_error = _llm_submission_error(use_llm, model_provider, model_name, model_id)
    if llm_error:
        return JSONResponse({"error": llm_error}, status_code=400)
    _cleanup_expired_jobs()
    jid = uuid.uuid4().hex[:10]
    for label, p in [("需求文件", tech), ("产品规范", spec)]:
        if not Path(p).exists():
            return JSONResponse({"error": f"{label} 不存在: {p}"}, status_code=400)
    if baseline_json and not baseline_docx:
        return JSONResponse({"error": "指定 JSON 基线时必须同时指定 DOCX 基线"}, status_code=400)
    for label, p, suffix in (
        ("DOCX 基线", baseline_docx, ".docx"),
        ("JSON 基线", baseline_json, ".json"),
    ):
        if not p:
            continue
        if Path(p).suffix.lower() != suffix or not Path(p).is_file():
            return JSONResponse({"error": f"{label}不存在或格式不正确: {p}"}, status_code=400)
    try:
        development_process, product_series, organization_scope, cover_phase = (
            _validate_process_inputs(
                development_process, product_series, organization_scope, cover_phase
            )
        )
        selection = resolve_template_selection(product_type, product_domain)
    except (ValueError, FileNotFoundError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    edit_plan, edit_error = _read_template_edit_plan(
        template_edit_plan, template_edit_confirmed
    )
    if edit_error:
        return JSONResponse({"error": edit_error}, status_code=400)
    out_path = _make_output_path()
    (_STATE.upload_dir / jid).mkdir(parents=False, exist_ok=False)
    _STATE.jobs[jid] = _job_record()
    background_tasks.add_task(
        _run_job,
        jid,
        tech,
        spec,
        selection,
        out_path,
        use_llm.lower() == "true",
        development_process,
        product_series,
        edit_plan,
        bool(edit_plan),
        baseline_docx or None,
        baseline_json or None,
        fail_on_regression.lower() == "true",
        organization_scope,
        cover_phase,
        model_provider,
        model_name,
        model_id,
    )
    return JSONResponse({"jid": jid})


@router.get("/api/local_defaults")
async def local_defaults():
    if os.getenv("JTB_ALLOW_LOCAL_PATHS", "0") != "1":
        return JSONResponse({"error": "本地路径接口未开启"}, status_code=403)
    items = [
        {"key": "tech", "path": _default_local_tech(), "exists": Path(_default_local_tech()).exists()},
        {"key": "spec", "path": _default_local_spec(), "exists": Path(_default_local_spec()).exists()},
    ]
    return JSONResponse(items)


@router.get("/api/product_catalog")
async def product_catalog():
    return JSONResponse({"product_types": list_product_catalog()})


@router.get("/api/template_outline")
async def template_outline(
    product_type: str = _DEFAULT_PRODUCT_TYPE,
    product_domain: str = _DEFAULT_PRODUCT_DOMAIN,
):
    try:
        selection = resolve_template_selection(product_type, product_domain)
        from jonhon_taskbook.template_outline_editor import get_template_outline

        return JSONResponse(
            {
                "selection": {
                    "product_type": selection.product_type_label,
                    "product_domain": selection.product_domain_label,
                    "template": Path(selection.template_path).name,
                },
                "outline": get_template_outline(selection.template_path),
            }
        )
    except (ValueError, FileNotFoundError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/api/template_edit/preview")
async def preview_template_edit(
    instruction: str = Form(...),
    product_type: str = Form(_DEFAULT_PRODUCT_TYPE),
    product_domain: str = Form(_DEFAULT_PRODUCT_DOMAIN),
    allow_llm: str = Form("true"),
    model_provider: str = Form(""),
    model_name: str = Form(""),
    model_id: str = Form(""),
):
    try:
        selection = resolve_template_selection(product_type, product_domain)
        from jonhon_taskbook.template_outline_editor import build_template_edit_plan

        if allow_llm.lower() == "true":
            with llm_client.model_scope(
                model_provider, model_name, model_id, resolve=False
            ):
                plan = build_template_edit_plan(
                    selection.template_path, instruction, allow_llm=True
                )
        else:
            plan = build_template_edit_plan(
                selection.template_path, instruction, allow_llm=False
            )
        return JSONResponse(plan)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/api/precheck")
async def precheck(
    tech: UploadFile = File(...),
    spec: UploadFile = File(...),
    product_type: str = Form(_DEFAULT_PRODUCT_TYPE),
    product_domain: str = Form(_DEFAULT_PRODUCT_DOMAIN),
    development_process: str = Form(_DEFAULT_DEVELOPMENT_PROCESS),
    product_series: str = Form(""),
    organization_scope: str = Form(_DEFAULT_ORGANIZATION_SCOPE),
    cover_phase: str = Form(""),
    model_provider: str = Form(""),
    model_name: str = Form(""),
    model_id: str = Form(""),
):
    try:
        development_process, product_series, organization_scope, cover_phase = (
            _validate_process_inputs(
                development_process, product_series, organization_scope, cover_phase
            )
        )
        selection = resolve_template_selection(product_type, product_domain)
    except (ValueError, FileNotFoundError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    payloads = {}
    for key, upload in (("tech", tech), ("spec", spec)):
        data, error = await _read_validated_upload(upload)
        if error:
            return JSONResponse({"error": f"{key}: {error}"}, status_code=400)
        payloads[key] = data or b""

    tech_text = _extract_docx_text_from_bytes(payloads["tech"])
    spec_text = _extract_docx_text_from_bytes(payloads["spec"])
    tpl_bytes = Path(selection.template_path).read_bytes()
    tpl_text = _extract_docx_text_from_bytes(tpl_bytes)

    tech_check = _classify_doc_role(tech.filename or "", tech_text, "tech")
    spec_check = _classify_doc_role(spec.filename or "", spec_text, "spec")
    tpl_name = Path(selection.template_path).name
    tpl_check = _classify_doc_role(tpl_name, tpl_text, "tpl")
    consistency = _check_name_consistency(tech.filename or "", spec.filename or "", tpl_name)

    return JSONResponse(
        {
            "files": {
                "tech": {"name": tech.filename, **tech_check},
                "spec": {"name": spec.filename, **spec_check},
                "tpl": {"name": tpl_name, "managed": True, **tpl_check},
            },
            "consistency": consistency,
            "suggestion": {
                "product": selection.product_type_label,
                "profile": "由受控产品类型/领域目录确定，不从文档名称自动猜测",
            },
            "selection": {
                "product_type": selection.product_type_label,
                "product_domain": selection.product_domain_label,
                "template": tpl_name,
                "development_process": development_process,
                "product_series": product_series,
                "organization_scope": organization_scope,
                "cover_phase": cover_phase,
                "model": llm_client.get_model_status(model_provider, model_name, model_id),
            },
        }
    )


@router.post("/api/precheck_local")
async def precheck_local(
    tech: str = Form(None),
    spec: str = Form(None),
    product_type: str = Form(_DEFAULT_PRODUCT_TYPE),
    product_domain: str = Form(_DEFAULT_PRODUCT_DOMAIN),
    development_process: str = Form(_DEFAULT_DEVELOPMENT_PROCESS),
    product_series: str = Form(""),
    organization_scope: str = Form(_DEFAULT_ORGANIZATION_SCOPE),
    cover_phase: str = Form(""),
    model_provider: str = Form(""),
    model_name: str = Form(""),
    model_id: str = Form(""),
):
    tech = tech or _default_local_tech()
    spec = spec or _default_local_spec()
    if os.getenv("JTB_ALLOW_LOCAL_PATHS", "0") != "1":
        return JSONResponse(
            {"error": "本地路径接口默认关闭；仅开发环境可设置 JTB_ALLOW_LOCAL_PATHS=1"},
            status_code=403,
        )
    try:
        development_process, product_series, organization_scope, cover_phase = (
            _validate_process_inputs(
                development_process, product_series, organization_scope, cover_phase
            )
        )
        selection = resolve_template_selection(product_type, product_domain)
    except (ValueError, FileNotFoundError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    tech_path = Path(tech)
    spec_path = Path(spec)
    if not tech_path.is_file():
        return JSONResponse({"error": f"需求文件不存在: {tech}"}, status_code=400)
    if not spec_path.is_file():
        return JSONResponse({"error": f"产品规范不存在: {spec}"}, status_code=400)

    tech_text = _extract_docx_text_from_bytes(tech_path.read_bytes())
    spec_text = _extract_docx_text_from_bytes(spec_path.read_bytes())
    tpl_bytes = Path(selection.template_path).read_bytes()
    tpl_text = _extract_docx_text_from_bytes(tpl_bytes)

    tech_check = _classify_doc_role(tech_path.name, tech_text, "tech")
    spec_check = _classify_doc_role(spec_path.name, spec_text, "spec")
    tpl_name = Path(selection.template_path).name
    tpl_check = _classify_doc_role(tpl_name, tpl_text, "tpl")
    consistency = _check_name_consistency(tech_path.name, spec_path.name, tpl_name)

    return JSONResponse(
        {
            "files": {
                "tech": {"name": tech_path.name, **tech_check},
                "spec": {"name": spec_path.name, **spec_check},
                "tpl": {"name": tpl_name, "managed": True, **tpl_check},
            },
            "consistency": consistency,
            "suggestion": {
                "product": selection.product_type_label,
                "profile": "由受控产品类型/领域目录确定，不从文档名称自动猜测",
            },
            "selection": {
                "product_type": selection.product_type_label,
                "product_domain": selection.product_domain_label,
                "template": tpl_name,
                "development_process": development_process,
                "product_series": product_series,
                "organization_scope": organization_scope,
                "cover_phase": cover_phase,
                "model": llm_client.get_model_status(model_provider, model_name, model_id),
            },
        }
    )


@router.get("/api/history")
async def history(include_legacy: bool = False):
    _cleanup_expired_jobs()
    items = []
    for jid, job in list(_STATE.jobs.items())[::-1]:
        result = job.get("result", {})
        meta = result.get("meta", {})
        current_runtime = _history_runtime_process_id(meta) == os.getpid()
        if not include_legacy and not current_runtime:
            continue
        stats = meta.get("stats", {})
        status = job.get("status", "unknown")
        delivery_status = result.get("delivery_status")
        if not delivery_status:
            if status == "done":
                delivery_status = "approved"
            elif status == "blocked":
                delivery_status = "blocked"
            else:
                delivery_status = status
        items.append(
            {
                "jid": jid,
                "status": status,
                "delivery_status": delivery_status,
                "current_runtime": current_runtime,
                "error": job.get("error", ""),
                "product": meta.get("product_type", ""),
                "product_type_id": meta.get("selected_product_type", ""),
                "product_type_label": meta.get("selected_product_type_label", ""),
                "product_domain_id": meta.get("product_domain", ""),
                "product_domain_label": meta.get("product_domain_label", ""),
                "development_process": meta.get("development_process", ""),
                "product_series": meta.get("product_series", ""),
                "organization_scope": meta.get("organization_scope", ""),
                "cover_phase": meta.get("cover_phase", ""),
                "model_provider": meta.get("llm_model_provider", ""),
                "model_name": meta.get("llm_model", ""),
                "model_id": meta.get("llm_model_id", ""),
                "profile": meta.get("profile", ""),
                "qa_ok": meta.get("qa_ok", None),
                "output_name": meta.get("output_name", ""),
                "saved_path": meta.get("saved_path", ""),
                "image_warning_count": meta.get("image_warning_count", 0),
                "drawing_count": stats.get("drawing_count", 0),
                "media_count": stats.get("media_count", 0),
                "created_at": meta.get("created_at", ""),
            }
        )
        if len(items) >= _HISTORY_LIMIT:
            break
    return JSONResponse(items)


def _history_runtime_process_id(meta: dict) -> int | None:
    value = meta.get("runtime_process_id")
    if value is None:
        value = (meta.get("build_fingerprint") or {}).get("process_id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@router.post("/api/submit")
async def submit(
    background_tasks: BackgroundTasks,
    tech: UploadFile = File(...),
    spec: UploadFile = File(...),
    product_type: str = Form(_DEFAULT_PRODUCT_TYPE),
    product_domain: str = Form(_DEFAULT_PRODUCT_DOMAIN),
    development_process: str = Form(_DEFAULT_DEVELOPMENT_PROCESS),
    product_series: str = Form(""),
    organization_scope: str = Form(_DEFAULT_ORGANIZATION_SCOPE),
    cover_phase: str = Form(""),
    use_llm: str = Form("true"),
    model_provider: str = Form(""),
    model_name: str = Form(""),
    model_id: str = Form(""),
    baseline_docx: UploadFile | None = File(None),
    baseline_json: UploadFile | None = File(None),
    fail_on_regression: str = Form("false"),
    template_edit_plan: str = Form(""),
    template_edit_confirmed: str = Form("false"),
):
    _cleanup_expired_jobs()
    llm_error = _llm_submission_error(use_llm, model_provider, model_name, model_id)
    if llm_error:
        return JSONResponse({"error": llm_error}, status_code=400)
    try:
        development_process, product_series, organization_scope, cover_phase = (
            _validate_process_inputs(
                development_process, product_series, organization_scope, cover_phase
            )
        )
        selection = resolve_template_selection(product_type, product_domain)
    except (ValueError, FileNotFoundError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    edit_plan, edit_error = _read_template_edit_plan(
        template_edit_plan, template_edit_confirmed
    )
    if edit_error:
        return JSONResponse({"error": edit_error}, status_code=400)
    payloads = {}
    for key, upload in (("tech", tech), ("spec", spec)):
        data, error = await _read_validated_upload(upload)
        if error:
            return JSONResponse({"error": f"{key}: {error}"}, status_code=400)
        payloads[key] = data or b""
    if baseline_json is not None and baseline_docx is None:
        return JSONResponse({"error": "指定 JSON 基线时必须同时上传 DOCX 基线"}, status_code=400)
    if baseline_docx is not None:
        data, error = await _read_validated_upload(baseline_docx)
        if error:
            return JSONResponse({"error": f"baseline_docx: {error}"}, status_code=400)
        payloads["baseline_docx"] = data or b""
    if baseline_json is not None:
        data, error = await _read_validated_json_upload(baseline_json)
        if error:
            return JSONResponse({"error": f"baseline_json: {error}"}, status_code=400)
        payloads["baseline_json"] = data or b""

    jid = uuid.uuid4().hex[:10]
    job_dir = _STATE.upload_dir / jid
    job_dir.mkdir(parents=False, exist_ok=False)

    paths = {
        key: str(job_dir / ("baseline.json" if key == "baseline_json" else f"{key}.docx"))
        for key in payloads
    }
    for key, data in payloads.items():
        Path(paths[key]).write_bytes(data)

    out_path = _make_output_path()
    _STATE.jobs[jid] = _job_record()
    _STATE.jobs[jid]["result"]["meta"]["original_filenames"] = {
        "tech": Path(tech.filename or "tech.docx").name,
        "spec": Path(spec.filename or "spec.docx").name,
    }
    background_tasks.add_task(
        _run_job,
        jid,
        paths["tech"],
        paths["spec"],
        selection,
        out_path,
        use_llm.lower() == "true",
        development_process,
        product_series,
        edit_plan,
        bool(edit_plan),
        paths.get("baseline_docx"),
        paths.get("baseline_json"),
        fail_on_regression.lower() == "true",
        organization_scope,
        cover_phase,
        model_provider,
        model_name,
        model_id,
    )
    return JSONResponse({"jid": jid})


def _sse(data: dict, event_id: int | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}retry: 3000\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/api/stream/{jid}")
async def stream(jid: str, request: Request):
    async def gen() -> AsyncGenerator[str, None]:
        try:
            last_event_id = max(0, int(request.headers.get("last-event-id", "0") or 0))
        except ValueError:
            last_event_id = 0
        sent = last_event_id
        heartbeat_interval = 1.0
        while True:
            job = _get_job(jid)
            if job is None:
                yield _sse({"type": "error", "msg": "任务不存在"}, 1)
                return
            logs = job["log"]
            sent = min(sent, len(logs))
            while sent < len(logs):
                sent += 1
                yield _sse({"type": "log", "msg": logs[sent - 1]}, sent)
            terminal_event_id = len(logs) + 1
            if job["status"] in {"done", "blocked", "cancelled"}:
                if last_event_id < terminal_event_id:
                    yield _sse(
                        {"type": job["status"], "jid": jid, "result": job["result"]},
                        terminal_event_id,
                    )
                return
            if job["status"] == "error":
                if last_event_id < terminal_event_id:
                    yield _sse({"type": "error", "msg": job["error"]}, terminal_event_id)
                return
            started = job.get("started_ts") or job.get("created_ts") or time.time()
            yield _sse(
                {
                    "type": "heartbeat",
                    "status": job.get("status", "queued"),
                    "stage": job.get("stage", "处理中"),
                    "elapsed": round(max(0.0, time.time() - started), 1),
                    "log_count": sent,
                }
            )
            await asyncio.sleep(heartbeat_interval)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/status/{jid}")
async def status(jid: str, after: int | None = None):
    _cleanup_expired_jobs()
    job = _get_job(jid) or {}
    logs = job.get("log", [])
    offset = (
        max(0, len(logs) - 20) if after is None else min(max(0, after), len(logs))
    )
    snap = (
        job["result"]
        if job.get("status") in {"done", "blocked"}
        else job.get("error", {})
    )
    return JSONResponse(
        {
            "status": job.get("status", "unknown"),
            "log": logs[offset:],
            "log_offset": offset,
            "log_count": len(logs),
            "result": snap,
            "error": job.get("error", ""),
        }
    )


@router.post("/api/cancel/{jid}")
async def cancel_job(jid: str):
    _cleanup_expired_jobs()
    job = _get_job(jid)
    if job is None:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    if job.get("status") in {"done", "blocked", "error", "cancelled"}:
        return JSONResponse(
            {"jid": jid, "status": job.get("status"), "accepted": False, "message": "任务已经结束"}
        )
    job["cancel_requested"] = True
    job["status"] = "cancelling"
    job["stage"] = "正在安全终止；将在当前外部模型请求结束后停止"
    job["updated_ts"] = time.time()
    message = "⏳ 已收到停止请求；当前外部模型请求返回后将立即终止"
    if not job["log"] or job["log"][-1] != message:
        job["log"].append(message)
        job["last_log_ts"] = job["updated_ts"]
    return JSONResponse(
        {"jid": jid, "status": "cancelling", "accepted": True, "message": job["stage"]}
    )


@router.get("/api/download/{jid}")
async def download(jid: str):
    path = _job_artifact(jid, "docx")
    if not path:
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    filename_ascii = path.name.encode("ascii", errors="ignore").decode() or "taskbook.docx"
    filename_utf8 = urllib.parse.quote(path.name)
    return FileResponse(
        str(path),
        media_type=_DOCX_CONTENT_TYPE,
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename_ascii}\"; filename*=UTF-8''{filename_utf8}",
            "Content-Type": _DOCX_CONTENT_TYPE,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/api/report/{jid}")
async def report(jid: str):
    rpt = _job_artifact(jid, "report")
    if not rpt:
        return JSONResponse({"error": "报告不存在"}, status_code=404)
    return FileResponse(
        str(rpt),
        media_type="text/html",
        headers={
            "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/api/report/{jid}/download")
async def download_report(jid: str):
    rpt = _job_artifact(jid, "report")
    if not rpt:
        return JSONResponse({"error": "报告不存在"}, status_code=404)
    filename_ascii = rpt.name.encode("ascii", errors="ignore").decode() or "quality-report.html"
    filename_utf8 = urllib.parse.quote(rpt.name)
    return FileResponse(
        str(rpt),
        media_type="text/html",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename_ascii}\"; filename*=UTF-8''{filename_utf8}",
            "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/api/health")
async def health():
    problems = []
    catalog = list_product_catalog()
    enabled_entries = 0
    for product in catalog:
        if product.get("enabled") is False:
            continue
        for domain in product.get("domains", []):
            enabled_entries += 1
            try:
                resolve_template_selection(product["value"], domain["value"])
            except (ValueError, FileNotFoundError) as exc:
                problems.append(str(exc))
    llm = llm_client.get_status()
    try:
        from jonhon_taskbook.semantic_retrieval import retrieval_status

        retrieval = retrieval_status()
    except Exception:
        retrieval = {"configured": False, "embedding_model": "", "rerank_model": ""}
    return JSONResponse(
        {
            "ok": not problems,
            "ready_for_generation": not problems and bool(llm.get("configured")),
            "catalog_entries": enabled_entries,
            "catalog_total_types": len(catalog),
            "catalog_enabled_types": sum(
                item.get("enabled") is not False for item in catalog
            ),
            "problems": problems,
            "llm": llm,
            "retrieval": retrieval,
            "runtime": public_runtime_status(_STATE.runtime_settings),
            "build_fingerprint": build_fingerprint(include_process=True),
        },
        status_code=200 if not problems else 503,
    )


@router.get("/api/templates")
async def list_templates():
    items = []
    for product in list_product_catalog():
        if product.get("enabled") is False:
            continue
        for domain in product.get("domains", []):
            selected = resolve_template_selection(product["value"], domain["value"])
            items.append(
                {
                    "product_type": product["label"],
                    "product_domain": domain["label"],
                    "template": Path(selected.template_path).name,
                }
            )
    return JSONResponse(items)


@router.get("/api/rules/summary")
async def rules_summary():
    taxonomy = load_taxonomy()
    catalog = list_product_catalog()
    categories = taxonomy.get("categories", [])
    semantic_roles = taxonomy.get("semantic_roles", [])
    return JSONResponse(
        {
            "schema_version": "1.0",
            "mode": "read_only",
            "chapter_numbers_are_identity": False,
            "source_body_generation": False,
            "semantic_categories": len(categories) + len(semantic_roles),
            "product_catalog": {
                "total_types": len(catalog),
                "enabled_types": sum(
                    item.get("enabled") is not False for item in catalog
                ),
            },
            "controlled_assets": [
                "需求语义分类",
                "产品与模板目录",
                "指标清单",
                "故障模式数据库",
                "研发流程章节策略",
            ],
            "template_onboarding": {"mode": "candidate_review", "auto_publish": False},
        }
    )


@router.get("/api/capabilities")
async def capabilities():
    return JSONResponse(
        {
            "schema_version": "1.0",
            "source_inputs": {
                "docx": {"status": "supported", "structure_preserved": True},
                "pdf_text": {
                    "status": "not_supported_yet",
                    "reason": "尚未接入带版面坐标和表格结构验证的 PDF 解析链路",
                },
                "pdf_scanned": {
                    "status": "not_supported_yet",
                    "reason": "需要 OCR、版面分析、低置信度人工复核和原图证据链",
                },
                "image_scan": {
                    "status": "not_supported_yet",
                    "reason": "需要 OCR、版面分析和人工复核",
                },
            },
            "template_onboarding": {
                "format": "docx",
                "automatic_scan": True,
                "automatic_publish": False,
                "required_stages": [
                    "candidate",
                    "machine_validation",
                    "sample_regression",
                    "full_page_visual_review",
                    "human_approval",
                    "publish",
                ],
                "rollback_supported": True,
            },
            "new_products": {
                "automatic_name_guessing": False,
                "catalog_onboarding_required": True,
                "required_assets": ["template", "semantic_mapping", "product_profile"],
            },
            "technical_specifications": {
                "per_run_evidence_input": True,
                "arbitrary_layout_guaranteed": False,
                "model_generates_technical_body": False,
            },
        }
    )


def _safe_management_field(value: str, field_name: str, max_length: int = 120) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name}不能为空")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name}长度超过限制")
    if any(ord(ch) < 32 for ch in normalized):
        raise ValueError(f"{field_name}包含无效字符")
    return normalized


@router.post("/api/templates/onboard")
async def onboard_template_candidate(
    template: UploadFile = File(...),
    product_type: str = Form(...),
    product_label: str = Form(...),
    domain: str = Form(...),
    domain_label: str = Form(...),
    version: str = Form(...),
    biz_id: str = Form(""),
    user_id: str = Form(""),
):
    payload, error = await _read_validated_upload(template)
    if error:
        return JSONResponse({"error": error}, status_code=400)

    try:
        fields = {
            "product_type": _safe_management_field(product_type, "product_type", 80),
            "product_label": _safe_management_field(product_label, "product_label", 120),
            "domain": _safe_management_field(domain, "domain", 80),
            "domain_label": _safe_management_field(domain_label, "domain_label", 120),
            "version": _safe_management_field(version, "version", 40),
        }
        audit_biz = _safe_management_field(biz_id or "anonymous", "biz_id", 120)
        audit_user = _safe_management_field(user_id or "anonymous", "user_id", 120)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    candidate_id = uuid.uuid4().hex[:12]
    root = _STATE.template_candidate_dir
    root.mkdir(parents=True, exist_ok=True)
    incoming = root / f".incoming-{candidate_id}.docx"
    candidate_dir = root / candidate_id
    incoming.write_bytes(payload or b"")
    print(
        json.dumps(
            {
                "event": "template_candidate_created",
                "candidate_id": candidate_id,
                "biz_id": audit_biz,
                "user_id": audit_user,
            },
            ensure_ascii=False,
        )
    )
    try:
        report = await asyncio.to_thread(
            prepare_template_candidate,
            str(incoming),
            str(candidate_dir),
            **fields,
        )
    except Exception as exc:
        shutil.rmtree(candidate_dir, ignore_errors=True)
        return JSONResponse({"error": f"模板候选校验失败：{str(exc)[:240]}"}, status_code=400)
    finally:
        incoming.unlink(missing_ok=True)

    validation = report.get("mapping_validation", {})
    return JSONResponse(
        {
            "ok": True,
            "candidate_id": candidate_id,
            "review_status": report.get("review_status", "pending_human_approval"),
            "machine_validation_passed": bool(report.get("machine_validation_passed")),
            "publish_ready": False,
            "active_catalog_mutated": False,
            "review_required": True,
            "slot_count": int(validation.get("slot_count", 0)),
            "unresolved_count": int(validation.get("problem_count", 0)),
            "files": list((report.get("files") or {}).values()),
        }
    )


def _lifecycle_error(exc: Exception) -> JSONResponse:
    status = 404 if isinstance(exc, FileNotFoundError) else 409
    if isinstance(exc, (ValueError, FileExistsError)):
        status = 400
    return JSONResponse({"error": str(exc)[:300]}, status_code=status)


@router.get("/api/templates/candidates")
async def list_template_candidates():
    try:
        return JSONResponse(_STATE.asset_lifecycle.list_candidates())
    except Exception as exc:
        return _lifecycle_error(exc)


@router.get("/api/templates/candidates/{candidate_id}")
async def get_template_candidate(candidate_id: str):
    try:
        return JSONResponse(_STATE.asset_lifecycle.describe(candidate_id))
    except Exception as exc:
        return _lifecycle_error(exc)


@router.post("/api/templates/candidates/{candidate_id}/review")
async def review_template_candidate(
    candidate_id: str,
    approved: bool = Form(...),
    reviewer: str = Form(...),
    reason: str = Form(...),
    regression_passed: bool = Form(False),
    visual_review_passed: bool = Form(False),
    biz_id: str = Form(""),
    user_id: str = Form(""),
):
    try:
        reviewer = _safe_management_field(reviewer, "reviewer", 120)
        reason = _safe_management_field(reason, "reason", 500)
        result = _STATE.asset_lifecycle.review(
            candidate_id,
            approved=approved,
            reviewer=reviewer,
            reason=reason,
            regression_passed=regression_passed,
            visual_review_passed=visual_review_passed,
        )
        print(
            json.dumps(
                {
                    "event": "template_candidate_reviewed",
                    "candidate_id": candidate_id,
                    "status": result.get("status"),
                    "biz_id": (biz_id or "anonymous")[:120],
                    "user_id": (user_id or "anonymous")[:120],
                },
                ensure_ascii=False,
            )
        )
        return JSONResponse(result)
    except Exception as exc:
        return _lifecycle_error(exc)


@router.post("/api/templates/candidates/{candidate_id}/publish")
async def publish_template_candidate(candidate_id: str, publisher: str = Form(...)):
    try:
        return JSONResponse(_STATE.asset_lifecycle.publish(candidate_id, publisher=publisher))
    except Exception as exc:
        return _lifecycle_error(exc)


@router.post("/api/templates/candidates/{candidate_id}/rollback")
async def rollback_template_candidate(
    candidate_id: str, actor: str = Form(...), reason: str = Form(...)
):
    try:
        return JSONResponse(_STATE.asset_lifecycle.rollback(candidate_id, actor=actor, reason=reason))
    except Exception as exc:
        return _lifecycle_error(exc)


# ── 辅助函数与后台任务 ───────────────────────────────────────────
def _extract_docx_text_from_bytes(data: bytes, max_chars: int = 4000) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml")
        root = etree.fromstring(xml)
        texts, total = [], 0
        for t in root.findall(
            ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
        ):
            txt = t.text or ""
            texts.append(txt)
            total += len(txt)
            if total >= max_chars:
                break
        return "".join(texts)
    except Exception:
        return ""


def _classify_doc_role(filename: str, text: str, expected: str) -> dict:
    name = (filename or "").lower()
    text_l = (text or "").lower()
    rules = {
        "tech": ["技术要求", "技术指标", "性能要求", "研制要求"],
        "spec": ["产品规范", "规范", "试验方法", "检验规则"],
        "tpl": ["研制任务书", "模板", "任务书", "编制"],
    }
    hits = sum(1 for kw in rules[expected] if kw.lower() in name or kw.lower() in text_l)
    score = min(100, hits * 25 + (10 if filename.lower().endswith(".docx") else 0))
    return {
        "expected": expected,
        "score": score,
        "ok": hits > 0,
        "message": "匹配良好" if hits > 1 else ("基本可用" if hits == 1 else "疑似不是该类型文件"),
    }


def _check_name_consistency(tech_name: str, spec_name: str, tpl_name: str) -> dict:
    return {
        "ok": True,
        "message": "不根据文件名猜测产品；产品一致性由受控类型/领域选择和内容预检共同确认",
        "tokens": [],
    }


def _copy_result_to_downloads(src_path: str) -> str:
    downloads_dir = Path.home() / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    src = Path(src_path)
    dest = downloads_dir / src.name
    if dest.exists():
        stem, suffix = src.stem, src.suffix
        stamp = time.strftime("%Y%m%d_%H%M%S")
        dest = downloads_dir / f"{stem}_{stamp}{suffix}"
    shutil.copy2(src, dest)
    return str(dest)


def _run_job(
    jid: str,
    tech: str,
    spec: str,
    selection,
    out: str,
    use_llm: bool,
    development_process: str = "全新",
    product_series: str = "",
    template_edit_plan: dict | None = None,
    template_edit_confirmed: bool = False,
    baseline_docx: str | None = None,
    baseline_json: str | None = None,
    fail_on_regression: bool = False,
    organization_scope: str = "non_central_research",
    cover_phase: str = "",
    model_provider: str = "",
    model_name: str = "",
    model_id: str = "",
):
    job = _STATE.jobs[jid]

    def cb(msg: str):
        _raise_if_cancelled(job)
        job["log"].append(str(msg))
        job["updated_ts"] = time.time()
        job["last_log_ts"] = job["updated_ts"]
        job["stage"] = str(msg).strip() or job.get("stage", "处理中")

    if job.get("cancel_requested"):
        _finish_cancelled_job(job)
        return

    with _STATE.job_slots:
        if job.get("cancel_requested"):
            _finish_cancelled_job(job)
            return
        job["status"] = "running"
        job["started_ts"] = time.time()
        job["updated_ts"] = job["started_ts"]
        job["stage"] = "正在执行受控工作流"
        initial_meta = dict(job.get("result", {}).get("meta", {}))
        try:
            template_path = selection.template_path
            category_mapping_path = selection.category_mapping_path
            if template_edit_plan:
                from jonhon_taskbook.template_outline_editor import (
                    apply_template_edit_plan,
                    write_category_mapping_overlay,
                )

                job_dir = _STATE.upload_dir / jid
                job_dir.mkdir(parents=True, exist_ok=True)
                template_path = str(job_dir / "template_edited.docx")
                category_mapping_path = str(job_dir / "category_mapping_edited.yaml")
                cb("🧩 应用已确认的模板章节计划（任务副本）…")
                edit_result = apply_template_edit_plan(
                    selection.template_path,
                    template_path,
                    template_edit_plan,
                    confirmed=template_edit_confirmed,
                )
                write_category_mapping_overlay(
                    selection.category_mapping_path,
                    category_mapping_path,
                    template_edit_plan,
                )
                plan_path = job_dir / "template_edit_plan.json"
                plan_path.write_text(
                    json.dumps(template_edit_plan, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                initial_meta.update(
                    {
                        "template_edited": True,
                        "template_edit_plan": str(plan_path),
                        "template_edit_operation_count": len(edit_result["applied"]),
                    }
                )
                cb(f"   章节操作: {len(edit_result['applied'])} 项；内置模板未修改")
            from src.pipeline_cli import run_pipeline

            with llm_client.model_scope(model_provider, model_name, model_id) as active_model:
                effective_provider = model_provider or active_model.provider
                initial_meta.update(
                    {
                        "llm_model_provider": effective_provider,
                        "llm_model": active_model.model,
                        "llm_model_id": active_model.model_id,
                    }
                )
                cb(f"🤖 本次任务模型：{active_model.model}")
                result = run_pipeline(
                    tech_path=tech,
                    spec_path=spec,
                    tpl_path=template_path,
                    out_path=out,
                    profile_path=selection.profile_path,
                    use_llm=use_llm,
                    baseline_docx=baseline_docx,
                    baseline_json=baseline_json,
                    fail_on_regression=fail_on_regression,
                    category_mapping_path=category_mapping_path,
                    preserve_unfilled_template=selection.preserve_unfilled_template,
                    selected_product_type=selection.product_type,
                    selected_product_type_label=selection.product_type_label,
                    selected_product_domain=selection.product_domain,
                    development_process=development_process,
                    product_series=product_series,
                    organization_scope=organization_scope,
                    cover_phase=cover_phase,
                    cb=cb,
                )
            _raise_if_cancelled(job)
            result.setdefault("meta", {}).update(
                {key: value for key, value in initial_meta.items() if key not in result["meta"]}
            )
            result["meta"].setdefault(
                "inputs",
                {
                    "tech": Path(tech).name,
                    "spec": Path(spec).name,
                    "tpl": Path(selection.template_path).name,
                },
            )
            result["meta"].update(
                {
                    "selected_product_type": selection.product_type,
                    "selected_product_type_label": selection.product_type_label,
                    "product_domain": selection.product_domain,
                    "product_domain_label": selection.product_domain_label,
                    "development_process": development_process,
                    "product_series": product_series,
                    "organization_scope": organization_scope,
                    "cover_phase": cover_phase,
                    "managed_template": True,
                    "category_mapping": Path(selection.category_mapping_path).name,
                    "preserve_unfilled_template": selection.preserve_unfilled_template,
                }
            )
            result["meta"].setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))
            if result.get("ok") and result.get("out") and Path(result["out"]).exists():
                try:
                    saved_path = _copy_result_to_downloads(result["out"])
                    result["meta"]["saved_path"] = saved_path
                    cb(f"📥 已复制到下载目录: {saved_path}")
                except Exception as copy_error:
                    result.setdefault("warnings", []).append(f"自动复制到下载目录失败: {copy_error}")
            job["result"] = result
            has_review_artifact = bool(
                result.get("out") and Path(result["out"]).is_file()
            )
            if result.get("ok"):
                job["status"] = "done"
            elif result.get("delivery_status") == "blocked" and has_review_artifact:
                job["status"] = "blocked"
            else:
                job["status"] = "error"
            if job["status"] != "done":
                job["error"] = result.get("error", "未知错误")
            if job["status"] in {"done", "blocked"}:
                try:
                    _persist_job_manifest(jid, result)
                except OSError as manifest_error:
                    result.setdefault("warnings", []).append(
                        f"任务持久化记录写入失败: {manifest_error}"
                    )
        except _JobCancelled:
            _finish_cancelled_job(job)
        except Exception as exc:
            job["status"] = "error"
            job["error"] = str(exc)
            cb(f"❌ {exc}")
        finally:
            job["updated_ts"] = time.time()
