"""Versioned page identities and authorized read-only navigation context."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .store import RdError


_PLATFORM_ROUTES = (
    ("work", "我的工作", "/work"), ("projects", "项目空间", "/projects"),
    ("research", "研发管理", "/research"),
    ("research.customers", "客户画像", "/research/customers"),
    ("research.products", "产品画像", "/research/products"),
    ("flows", "流程管理", "/flows"), ("knowledge", "知识管理", "/knowledge"),
    ("operations", "运营管理", "/operations"), ("workspace", "资源工作台", "/workspace"),
    ("settings", "系统管理", "/settings"),
)
_CASE_PAGES = (
    ("resume", "继续办理"), ("overview", "当前成果"), ("materials", "资料识别"),
    ("requirements", "需求确认"), ("selection", "选型与启动"), ("preparation", "编制准备"),
    ("execution", "编排与生成"), ("delivery", "交付"), ("reuse", "复用"),
    ("decision", "业务确认"), ("process", "项目流程"), ("evidence", "资料与依据"),
    ("history", "过程记录"),
)
ROUTES = {
    route_id: {"route_id": route_id, "label": label, "scope": "platform",
               "path_template": path, "read_only": True}
    for route_id, label, path in _PLATFORM_ROUTES
}
ROUTES["project"] = {"route_id": "project", "label": "项目", "scope": "project",
                     "path_template": "/projects/{project_id}", "read_only": True}
for _page, _label in _CASE_PAGES:
    _id = "case." + _page
    ROUTES[_id] = {"route_id": _id, "label": _label, "scope": "case", "read_only": True,
                   "path_template": "/projects/{project_id}/flows/{case_id}" +
                   ("" if _page == "resume" else "/" + _page)}

SPA_PATHS = tuple(row["path_template"] for row in ROUTES.values())
_TARGET_ROUTES = {
    "current": "case.overview", "sources": "case.materials", "requirements": "case.requirements",
    "routes": "case.selection", "workpackages": "case.execution", "process": "case.process",
    "artifacts": "case.evidence", "history": "case.history",
}


class PageReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    route_id: str = Field(min_length=1, max_length=80)
    project_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    case_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    workpackage_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("仅支持页面引用版本 1。")
        return value

    @model_validator(mode="after")
    def matching_scope(self):
        route = ROUTES.get(self.route_id)
        if route is None:
            raise ValueError("页面标识不受支持。")
        scope = route["scope"]
        if scope == "platform" and any((self.project_id, self.case_id, self.workpackage_id)):
            raise ValueError("平台目录不能携带项目或流程标识。")
        if scope == "project" and (not self.project_id or self.case_id or self.workpackage_id):
            raise ValueError("项目页面仅接受必需的项目标识。")
        if scope == "case" and (not self.project_id or not self.case_id):
            raise ValueError("流程页面需要项目和流程标识。")
        if self.workpackage_id and self.route_id != "case.execution":
            raise ValueError("工作包标识仅用于编排与生成页面。")
        return self


def normalize_reference(value):
    try:
        reference = value if isinstance(value, PageReference) else PageReference.model_validate(value)
    except ValidationError:
        raise RdError(422, "页面引用无效，请使用导航目录中的页面与对象标识。") from None
    return reference.model_dump(exclude_none=True)


def page_reference(route_id, project_id=None, case_id=None, workpackage_id=None):
    return PageReference(schema_version=1, route_id=route_id, project_id=project_id,
                         case_id=case_id, workpackage_id=workpackage_id).model_dump(exclude_none=True)


def navigation_catalog():
    return {"schema_version": 1, "routes": [dict(row) for row in ROUTES.values()],
            "capabilities": [
                {"id": "navigation.catalog", "read_only": True, "business_write": False},
                {"id": "navigation.context", "read_only": True, "business_write": False},
            ]}


def validate_case_reference(project, case, value):
    """The caller supplies records already authorized by Store.get_project."""
    reference = normalize_reference(value)
    if ROUTES[reference["route_id"]]["scope"] != "case":
        raise RdError(422, "案例助手需要当前流程的页面引用。")
    if reference["project_id"] != project["id"] or reference["case_id"] != case["id"]:
        raise RdError(404, "页面对应流程不存在或无权访问。")
    wid = reference.get("workpackage_id")
    if wid and not any(package["id"] == wid for package in case["workpackages"]):
        raise RdError(404, "页面对应工作包不存在或无权访问。")
    return reference


def navigation_for_target(target, project_id, case_id, current_reference=None):
    route_id = _TARGET_ROUTES[target]
    wid = (current_reference or {}).get("workpackage_id") if route_id == "case.execution" else None
    return {"target": target, "page_ref": page_reference(route_id, project_id, case_id, wid)}


def _active_source_count(case):
    active = [source for source in case["sources"] if source.get("role") == "reference"]
    for role in ("tech", "spec"):
        candidates = [source for source in case["sources"] if source.get("role") == role]
        selected = case.get("source_selection", {}).get(role)
        if selected is None and len(candidates) == 1:
            selected = candidates[0]["id"]
        active.extend(source for source in candidates if source["id"] == selected)
    return len(active)


def navigation_context(store, actor, value):
    reference = normalize_reference(value)
    scope = ROUTES[reference["route_id"]]["scope"]
    context = {}
    targets = [page_reference(route_id) for route_id, _, _ in _PLATFORM_ROUTES]
    if scope != "platform":
        project = store.get_project(actor, reference["project_id"])
        context = {"project_version": project["version"], "counts": {"cases": len(project["cases"])}}
        targets = [page_reference("projects"), page_reference("project", project["id"])]
        if scope == "project":
            targets.extend(page_reference("case.resume", project["id"], case["id"]) for case in project["cases"])
        else:
            case = next((row for row in project["cases"] if row["id"] == reference["case_id"]), None)
            if case is None:
                raise RdError(404, "页面对应流程不存在或无权访问。")
            validate_case_reference(project, case, reference)
            context = {"project_version": project["version"], "input_revision": case.get("input_revision", 1),
                       "stage": case["stage"],
                       "counts": {"sources": len(case["sources"]), "active_sources": _active_source_count(case),
                                  "requirements": len(case["requirements"]), "workpackages": len(case["workpackages"])}}
            targets.extend(page_reference("case." + page, project["id"], case["id"]) for page, _ in _CASE_PAGES)
    return {"schema_version": 1, "page_ref": reference, "context": context,
            "navigation": targets, "read_only": True}
