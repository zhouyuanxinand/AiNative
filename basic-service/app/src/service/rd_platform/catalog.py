"""Published capability identities and the first complete research scenario."""
from copy import deepcopy

STAGE_IDS = ("input", "requirements", "selection", "planning", "design", "verification", "delivery", "knowledge")
STAGES = [
    {"id": sid, "title": title, "name": title, "requires_human_decision": True}
    for sid, title in zip(STAGE_IDS, ("资料输入与需求澄清", "需求确认", "选型决策", "直接选用／改型／新研", "方案与零配件设计", "验证及审签", "交付与反馈", "知识治理与再次复用"))
]
CONTEXT_FIELDS = ("product_type", "product_domain", "development_process", "cover_phase", "product_series", "organization_scope")
ACTION_TITLES = {
    "resolve_context": "解析项目上下文", "template_plan": "选择或规划受控模板", "content_completion": "核查内容与补齐义务",
    "generate": "生成研制任务书", "verify": "校验成果", "consistency": "资料一致性检查",
}
ACTIONS = [
    {"id": aid, "version": "1", "title": title, "name": title, "resource_id": aid, "resource_version": 1,
     "execution_mode": "local_real", "provider_id": "local-taskbook", "status": "published", "autonomous": True}
    for aid, title in ACTION_TITLES.items()
]
SCENARIOS = [{"id": "taskbook", "version": "1", "title": "研制任务书生成", "name": "研制任务书生成",
              "status": "published", "initial_stage": "input", "context_fields": list(CONTEXT_FIELDS),
              "description": "上传建项、需求确认及选型决定后采用研发流程与任务书模板，整包提交自动编制任务书。", "stages": list(STAGE_IDS),
              "product_routes": ["direct", "modification", "new"], "composition_routes": ["direct", "adapt", "new"]}]
WORKPACKAGE_DEFINITIONS = [
    {"id": "taskbook", "version": "1", "title": "任务书装配与校验", "name": "任务书装配与校验", "scenario_id": "taskbook", "stages": ["design"], "required": True,
     "required_actions": ["resolve_context", "template_plan", "content_completion", "generate", "verify"], "optional_actions": ["consistency"]},
    {"id": "input_check", "version": "1", "title": "资料一致性检查", "name": "资料一致性检查", "scenario_id": "taskbook", "stages": list(STAGE_IDS), "required": False,
     "required_actions": ["consistency"], "optional_actions": []},
    {"id": "context_resolve", "version": "1", "title": "上下文解析", "name": "上下文解析", "scenario_id": "taskbook", "stages": list(STAGE_IDS), "required": False,
     "required_actions": ["resolve_context"], "optional_actions": ["consistency"]},
    {"id": "quality_check", "version": "1", "title": "已有成果校验", "name": "已有成果校验", "scenario_id": "taskbook", "stages": list(STAGE_IDS), "required": False,
     "required_actions": ["verify"], "optional_actions": ["consistency"]},
]
RESEARCH_WORKFLOW_TEMPLATES = [
    {"id": "taskbook-" + route + "-v1", "version": "1", "title": title, "status": "published",
     "product_route": route, "nodes": ["taskbook", "scheme", "detail", "integration", "verification", "delivery"]}
    for route, title in (("modification", "改型研发流程"), ("new", "全新研发流程"))
]

RULE_VERSIONS = {"case_lifecycle": "2", "taskbook_delegation": "1", "evidence_isolation": "1"}


def get_catalog():
    definitions = [{**item, "nodes": default_nodes(item["id"])} for item in WORKPACKAGE_DEFINITIONS]
    return deepcopy({"stages": STAGES, "scenarios": [item for item in SCENARIOS if item["status"] == "published"],
                     "workpackage_definitions": definitions, "actions": ACTIONS, "research_workflow_templates": RESEARCH_WORKFLOW_TEMPLATES})


def catalog():
    return get_catalog()


def scenario(scenario_id):
    """Only a published registration can initialize a case."""
    return next((deepcopy(item) for item in SCENARIOS if item["id"] == scenario_id and item["status"] == "published"), None)


def definition(definition_id):
    return next((deepcopy(item) for item in WORKPACKAGE_DEFINITIONS if item["id"] == definition_id), None)


def default_nodes(definition_id):
    nodes = []
    for action_id in definition(definition_id)["required_actions"]:
        nodes.append({"id": action_id, "action_id": action_id, "action_version": "1", "depends_on": [nodes[-1]["id"]] if nodes else [],
                      "required": True, "status": "draft", "result": None, "attempt": 0,
                      "started_at": None, "completed_at": None, "ended_at": None})
    return nodes
