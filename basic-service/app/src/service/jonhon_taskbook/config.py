import os

# BASE_DIR 指向 jonhon_taskbook 包的父目录（src/service/），
# 即 config/、prompts/ 业务规则目录的同级根，与各模块 parents[1] 保持一致。
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DOCS_DIR = os.path.join(BASE_DIR, "input_docs")


def _configured_path(env_name: str) -> str:
    """Return an optional runtime path without binding production to a sample."""
    value = os.getenv(env_name, "").strip()
    if not value:
        return ""
    return value if os.path.isabs(value) else os.path.join(BASE_DIR, value)


TEMPLATE_SOURCE = _configured_path("JTB_TEMPLATE_SOURCE")
FORMAT_BENCHMARK = None
TECH_REQ_FILE = _configured_path("JTB_TECH_REQUIREMENT")
PRODUCT_SPEC_FILE = _configured_path("JTB_PRODUCT_SPEC")
REFERENCE_TASKBOOK = _configured_path("JTB_REFERENCE_TASKBOOK")
RULE_PACK_PATH = _configured_path("JTB_RULE_PACK") or os.path.join(
    BASE_DIR, "rule_pack.json"
)

# 旧 V3 工具的可选输入；生产流水线的受控真源位于 config/ 与 prompts/。
V3_ROUTING_EXCEL = _configured_path("JTB_LEGACY_ROUTING_EXCEL")
# ============ 统一输出目录配置 ============
# 所有输出集中到 最终输出/ 目录，避免文件分散
OUTPUT_ROOT = os.path.join(BASE_DIR, "最终输出")
OUTPUT_DIR = os.path.join(OUTPUT_ROOT, "已验收文档")
REJECTED_DIR = os.path.join(OUTPUT_ROOT, "待改进文档")
REPORTS_DIR = os.path.join(OUTPUT_ROOT, "分析报告")
LINEAGE_DIR = os.path.join(OUTPUT_ROOT, "血缘追踪")
REVIEWS_DIR = os.path.join(OUTPUT_ROOT, "审查报告")

# 确保目录存在
for d in [OUTPUT_DIR, REJECTED_DIR, REPORTS_DIR, LINEAGE_DIR, REVIEWS_DIR]:
    os.makedirs(d, exist_ok=True)

# 向后兼容（可选）
CACHE_COMPARE = os.path.join(OUTPUT_ROOT, "CompareReport.json")

# 比对模式: strict = 仅技术要求入口; spec_supplement = 规范独有项进候选
COMPARE_MODE = "v3"
SPEC_SUPPLEMENT_MODE = False

# 兼容旧工具的无样例默认值。生产路径由产品目录/profile 显式传入。
PROJECT_FLAGS = {
    "product_type": "",
    "product_name": "",
    "is_military": False,
    "is_aviation": False,
    "has_ess": False,
}

# 可选：LLM 填空空章节（需 Azure 环境变量）
ENABLE_LLM_ZONE_FILL = os.getenv("ENABLE_LLM_ZONE_FILL", "0") in ("1", "true", "yes")

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
