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
WORKPACKAGE_DEFINITIONS.append({**deepcopy(WORKPACKAGE_DEFINITIONS[0]), "version": "2", "stages": ["planning"],
                               "business_node_id": "taskbook_planning", "policy_version": "v2"})
SELECTION_WORKFLOW_TEMPLATES = [{"id": "taskbook-selection-v2", "version": "2", "title": "需求确认与选型办理", "status": "published",
                               "policy_version": "v2", "nodes": ["input", "confirm_requirements", "comparison", "selection_decision", "rd_start"]}]
PROJECT_WORKFLOW_TEMPLATES = [{"id": "taskbook-generation", "version": "1", "title": "研制任务书生成流程", "status": "published",
                               "policy_version": "v2", "nodes": ["input", "confirm_requirements", "comparison", "selection_decision", "rd_start", "taskbook"]}]
RESEARCH_WORKFLOW_TEMPLATES = [
    {"id": "taskbook-" + route + "-v1", "version": "1", "title": title, "status": "published",
     "product_route": route, "nodes": ["taskbook", "scheme", "detail", "integration", "verification", "delivery"]}
    for route, title in (("modification", "改型研发流程"), ("new", "全新研发流程"))
]

RULE_VERSIONS = {"case_lifecycle": "2", "taskbook_delegation": "1", "evidence_isolation": "1"}


def builtin_teams():
    """Published local teams wrap the unchanged six Skill identities."""
    values = []
    for rid, title, aids in (("taskbook-authoring-team", "任务书编制专家团", WORKPACKAGE_DEFINITIONS[0]["required_actions"]),
                             ("consistency-team", "资料一致性专家团", ["consistency"]),
                             ("context-team", "上下文解析专家团", ["resolve_context"]),
                             ("quality-team", "成果校验专家团", ["verify"])):
        nodes = [{"id": aid, "resource_id": aid, "resource_version": 1} for aid in aids]
        edges = [{"id": "e-" + a + "-" + b, "source": a, "target": b} for a, b in zip(aids, aids[1:])]
        values.append({"id": rid, "version": 1, "kind": "team", "name": title,
            "description": "固定本地Skill图，由现有Worker串行执行；不替代业务审签。",
            "configuration": {"members": [{"resource_id": aid, "resource_version": 1} for aid in aids],
                "inputs": ["固定来源与业务决定"], "outputs": ["节点结果与受控成果"],
                "execution_graph": {"nodes": nodes, "edges": edges}},
            "execution_mode": "local_real", "status": "published", "executable": True})
    return values


def get_catalog():
    definitions = [{**item, "nodes": default_nodes(item["id"], item["version"])} for item in WORKPACKAGE_DEFINITIONS]
    return deepcopy({"stages": STAGES, "scenarios": [item for item in SCENARIOS if item["status"] == "published"],
                     "workpackage_definitions": definitions, "actions": ACTIONS, "research_workflow_templates": RESEARCH_WORKFLOW_TEMPLATES,
                     "selection_workflow_templates": SELECTION_WORKFLOW_TEMPLATES,
                     "project_workflow_templates": PROJECT_WORKFLOW_TEMPLATES})


def catalog():
    return get_catalog()


def scenario(scenario_id):
    """Only a published registration can initialize a case."""
    return next((deepcopy(item) for item in SCENARIOS if item["id"] == scenario_id and item["status"] == "published"), None)


def definition(definition_id, version="1"):
    return next((deepcopy(item) for item in WORKPACKAGE_DEFINITIONS if item["id"] == definition_id and item["version"] == version), None)


def default_nodes(definition_id, version="1"):
    nodes = []
    for action_id in definition(definition_id, version)["required_actions"]:
        nodes.append({"id": action_id, "action_id": action_id, "action_version": "1", "depends_on": [nodes[-1]["id"]] if nodes else [],
                      "required": True, "status": "draft", "result": None, "attempt": 0,
                      "started_at": None, "completed_at": None, "ended_at": None})
    return nodes
