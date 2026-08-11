"""受控模板标题树编辑：提示词只产生结构化章节操作，不生成正文。"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable

import yaml
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from .template_scanner import scan_template_tree


ChatJSON = Callable[[str, str], Any]
ALLOWED_OPERATIONS = {
    "rename", "add_before", "add_after", "add_child",
    "move_before", "move_after", "move_child", "delete",
}
PROTECTED_TITLE_WORDS = {"封面", "目录", "变更记录", "批准", "审核", "会签", "签署"}
_QUOTED = re.compile(r"[“\"「『《](.*?)[”\"」』》]")


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _clean_title(value: str) -> str:
    # 用户即使在提示词中写了显示编号，也只保留标题语义；显示编号由模板样式负责。
    return re.sub(r"^\s*\d+(?:\.\d+)*\s*", "", value or "").strip()


def _template_fingerprint(template_path: str) -> str:
    return hashlib.sha256(Path(template_path).read_bytes()).hexdigest()


def _plan_hash(fingerprint: str, operations: list[dict]) -> str:
    payload = json.dumps(
        {"template_fingerprint": fingerprint, "operations": operations},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_template_outline(template_path: str) -> list[dict]:
    """返回无显示编号的标题树；稳定 ID 由标题语义路径产生。"""
    return [
        {
            "id": node["id"],
            "title": node["title"],
            "semantic_path": node["semantic_path"],
            "level": node["level"],
            "parent_id": node["parent_id"],
        }
        for node in scan_template_tree(template_path)
    ]


def _resolve_slot(outline: list[dict], title_or_path: str) -> str:
    query = _norm(_clean_title(title_or_path))
    exact = [
        node for node in outline
        if query in {_norm(node["title"]), _norm(node["semantic_path"])}
    ]
    if len(exact) == 1:
        return exact[0]["id"]
    if not exact:
        fuzzy = [
            node for node in outline
            if query and (query in _norm(node["title"]) or query in _norm(node["semantic_path"]))
        ]
        if len(fuzzy) == 1:
            return fuzzy[0]["id"]
    raise ValueError(f"标题定位不唯一或不存在: {title_or_path}")


def _parse_deterministic(instruction: str, outline: list[dict]) -> list[dict]:
    operations: list[dict] = []
    segments = [
        segment.strip() for segment in re.split(r"[\n；;]+", instruction or "")
        if segment.strip()
    ]
    for segment in segments:
        quoted = [_clean_title(value) for value in _QUOTED.findall(segment)]
        if ("移动" in segment or "移到" in segment or "调整到" in segment) and len(quoted) >= 2:
            action = "move_child" if re.search(r"(下面|下级|子章节|作为.*子)", segment) else (
                "move_before" if re.search(r"(之前|前面|前方)", segment) else "move_after"
            )
            operations.append({
                "operation": action,
                "target_slot": _resolve_slot(outline, quoted[0]),
                "anchor_slot": _resolve_slot(outline, quoted[1]),
                "reason": "用户提示词的章节移动指令",
            })
        elif re.search(r"(改为|修改为|重命名为)", segment) and len(quoted) >= 2:
            operations.append({
                "operation": "rename",
                "target_slot": _resolve_slot(outline, quoted[0]),
                "new_title": quoted[1],
                "reason": "用户提示词的标题重命名指令",
            })
        elif re.search(r"(新增|添加|插入)", segment) and len(quoted) >= 2:
            action = "add_child" if re.search(r"(下面|下级|子章节|作为.*子)", segment) else (
                "add_before" if re.search(r"(之前|前面|前方)", segment) else "add_after"
            )
            operations.append({
                "operation": action,
                "anchor_slot": _resolve_slot(outline, quoted[0]),
                "new_title": quoted[1],
                "reason": "用户提示词的新增章节指令",
            })
        elif "删除" in segment and quoted:
            operations.append({
                "operation": "delete",
                "target_slot": _resolve_slot(outline, quoted[0]),
                "reason": "用户提示词的删除章节指令",
            })
    return operations


def _parse_with_llm(
    instruction: str, outline: list[dict], chat_json_fn: ChatJSON,
) -> list[dict]:
    system = """你是受控 Word 模板章节规划器。你只能把用户指令转换成章节标题树操作，
不得生成、改写或补充任何任务书正文。不得使用章节号或标题顺序定位，只能引用给定的
slot ID。仅返回 JSON：{"operations":[{"operation":"rename|add_before|add_after|
add_child|move_before|move_after|move_child|delete","target_slot":"已有节点ID",
"anchor_slot":"已有节点ID","new_title":"无编号标题","reason":"简短原因"}]}。
rename/delete/move 需要 target_slot；add/move 需要 anchor_slot；只有 rename/add 允许 new_title。
不要输出 preserve、正文、段落、表格内容或未列出的字段。"""
    raw = chat_json_fn(
        system,
        json.dumps({"instruction": instruction, "outline": outline}, ensure_ascii=False),
    )
    operations = raw.get("operations", []) if isinstance(raw, dict) else []
    return operations if isinstance(operations, list) else []


def _validate_operations(outline: list[dict], operations: list[dict]) -> list[dict]:
    by_id = {node["id"]: node for node in outline}
    validated: list[dict] = []
    for raw in operations:
        if not isinstance(raw, dict):
            raise ValueError("章节编辑操作必须是对象")
        operation = str(raw.get("operation", "")).strip()
        if operation not in ALLOWED_OPERATIONS:
            raise ValueError(f"不允许的章节操作: {operation}")
        item = {"operation": operation}
        target_slot = str(raw.get("target_slot", "")).strip()
        anchor_slot = str(raw.get("anchor_slot", "")).strip()
        if operation in {"rename", "delete", "move_before", "move_after", "move_child"}:
            if target_slot not in by_id:
                raise ValueError(f"目标章节不存在: {target_slot}")
            if operation != "rename" and any(
                word in by_id[target_slot]["title"] for word in PROTECTED_TITLE_WORDS
            ):
                raise ValueError(f"受保护章节禁止移动或删除: {by_id[target_slot]['title']}")
            item["target_slot"] = target_slot
        if operation in {"add_before", "add_after", "add_child", "move_before", "move_after", "move_child"}:
            if anchor_slot not in by_id:
                raise ValueError(f"锚点章节不存在: {anchor_slot}")
            item["anchor_slot"] = anchor_slot
        if operation in {"rename", "add_before", "add_after", "add_child"}:
            new_title = _clean_title(str(raw.get("new_title", "")))
            if not new_title or len(new_title) > 80:
                raise ValueError("新增/修改后的标题必须为 1~80 个字符")
            item["new_title"] = new_title
        item["reason"] = str(raw.get("reason", ""))[:160]
        validated.append(item)
    if not validated:
        raise ValueError("未识别出可执行的章节编辑指令；请用引号标出标题，或启用 LLM")
    return validated


def build_template_edit_plan(
    template_path: str,
    instruction: str,
    chat_json_fn: ChatJSON | None = None,
    allow_llm: bool = True,
) -> dict:
    """把客户提示词转换成可预览、可签名校验的标题树操作计划。"""
    if not (instruction or "").strip():
        raise ValueError("章节编辑提示词为空")
    outline = get_template_outline(template_path)
    if allow_llm:
        if chat_json_fn is None:
            from .llm_client import chat_json as chat_json_fn
        operations = _parse_with_llm(instruction, outline, chat_json_fn)
        parser = "llm"
    else:
        # 仅供无模型的单元测试/离线诊断；生产网页始终启用 LLM，避免把
        # 用户自然语言固化为不断膨胀的关键词和 if/else 业务规则。
        operations = _parse_deterministic(instruction, outline)
        parser = "deterministic-offline"
    operations = _validate_operations(outline, operations)
    fingerprint = _template_fingerprint(template_path)
    return {
        "schema_version": "1.0",
        "policy": {
            "chapter_numbers_are_identity": False,
            "llm_may_generate_body_text": False,
            "applies_to_job_copy_only": True,
            "requires_user_confirmation": True,
        },
        "parser": parser,
        "instruction": instruction.strip(),
        "template_fingerprint": fingerprint,
        "outline_before": outline,
        "operations": operations,
        "plan_hash": _plan_hash(fingerprint, operations),
    }


def _paragraph_level(paragraph) -> int:
    style_name = paragraph.style.name if paragraph.style else ""
    match = re.search(r"(?:Heading|heading)\s*([1-9])", style_name)
    if match:
        return int(match.group(1))
    # 自定义标题样式可能没有 Heading 命名，但 Word 仍会写 outlineLvl。
    # 读取结构层级即可支持模板改名/重排，不依赖显示章节号。
    ppr = paragraph._p.find(qn("w:pPr"))
    outline = ppr.find(qn("w:outlineLvl")) if ppr is not None else None
    raw = outline.get(qn("w:val")) if outline is not None else None
    return int(raw) + 1 if raw is not None and str(raw).isdigit() else 0


def _replace_heading_text(paragraph, title: str) -> None:
    text_nodes = paragraph._p.findall(f".//{qn('w:t')}")
    if text_nodes:
        text_nodes[0].text = title
        for node in text_nodes[1:]:
            node.text = ""
        return
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = title
    run.append(text)
    paragraph._p.append(run)


def _new_heading_from(source_paragraph, title: str):
    element = copy.deepcopy(source_paragraph._p)
    ppr = element.find(qn("w:pPr"))
    for child in list(element):
        if child is not ppr:
            element.remove(child)
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = title
    run.append(text)
    element.append(run)
    return element


def _section_nodes(body, heading_element, level_by_element: dict[int, int]) -> list:
    nodes = [heading_element]
    current = heading_element.getnext()
    level = level_by_element.get(id(heading_element), 1)
    while current is not None:
        current_level = level_by_element.get(id(current), 0)
        if current_level and current_level <= level:
            break
        nodes.append(current)
        current = current.getnext()
    return nodes


def apply_template_edit_plan(
    template_path: str,
    output_path: str,
    plan: dict,
    *,
    confirmed: bool = False,
) -> dict:
    """在任务级模板副本上执行已预览计划；绝不修改受控原模板。"""
    if not confirmed:
        raise ValueError("章节编辑计划尚未由用户确认")
    fingerprint = _template_fingerprint(template_path)
    operations = plan.get("operations", []) if isinstance(plan, dict) else []
    if fingerprint != plan.get("template_fingerprint"):
        raise ValueError("模板已变化，原章节编辑预览已失效，请重新预览")
    if _plan_hash(fingerprint, operations) != plan.get("plan_hash"):
        raise ValueError("章节编辑计划校验失败")
    outline = get_template_outline(template_path)
    operations = _validate_operations(outline, operations)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template_path, output_path)
    document = Document(output_path)
    live_tree = scan_template_tree(output_path)
    paragraph_by_id = {
        node["id"]: document.paragraphs[node["paragraph_index"]]
        for node in live_tree
        if node["paragraph_index"] < len(document.paragraphs)
    }
    level_by_element = {
        id(paragraph_by_id[node["id"]]._p): node["level"]
        for node in live_tree if node["id"] in paragraph_by_id
    }
    body = document.element.body
    applied: list[dict] = []

    def paragraph_for_level(level: int, fallback):
        return next((p for p in document.paragraphs if _paragraph_level(p) == level), fallback)

    for operation in operations:
        action = operation["operation"]
        target = paragraph_by_id.get(operation.get("target_slot", ""))
        anchor = paragraph_by_id.get(operation.get("anchor_slot", ""))
        if action == "rename":
            _replace_heading_text(target, operation["new_title"])
        elif action == "delete":
            for element in _section_nodes(body, target._p, level_by_element):
                if element.getparent() is not None:
                    element.getparent().remove(element)
        elif action.startswith("add_"):
            anchor_level = level_by_element.get(id(anchor._p), _paragraph_level(anchor) or 1)
            new_level = min(9, anchor_level + 1) if action == "add_child" else anchor_level
            source = paragraph_for_level(new_level, anchor)
            new_heading = _new_heading_from(source, operation["new_title"])
            if action == "add_before":
                anchor._p.addprevious(new_heading)
            else:
                anchor_section = _section_nodes(body, anchor._p, level_by_element)
                anchor_section[-1].addnext(new_heading)
            level_by_element[id(new_heading)] = new_level
        elif action.startswith("move_"):
            nodes = _section_nodes(body, target._p, level_by_element)
            if anchor._p in nodes:
                raise ValueError("不能把章节移动到自身子树")
            if action == "move_child":
                target_level = level_by_element.get(id(target._p), _paragraph_level(target) or 1)
                anchor_level = level_by_element.get(id(anchor._p), _paragraph_level(anchor) or 1)
                level_delta = min(9, anchor_level + 1) - target_level
                for element in nodes:
                    old_level = level_by_element.get(id(element), 0)
                    if not old_level:
                        continue
                    new_level = max(1, min(9, old_level + level_delta))
                    moved_paragraph = Paragraph(element, document._body)
                    style_source = paragraph_for_level(new_level, moved_paragraph)
                    if _paragraph_level(style_source) != new_level:
                        raise ValueError(f"模板缺少 Heading {new_level} 样式，无法安全移动为子章节")
                    moved_paragraph.style = style_source.style
                    level_by_element[id(element)] = new_level
            for element in nodes:
                element.getparent().remove(element)
            if action == "move_before":
                insert_before = anchor._p
                for element in nodes:
                    insert_before.addprevious(element)
            else:
                anchor_section = _section_nodes(body, anchor._p, level_by_element)
                cursor = anchor_section[-1]
                for element in nodes:
                    cursor.addnext(element)
                    cursor = element
        applied.append(operation)

    document.save(output_path)
    return {
        "passed": True,
        "output_path": str(Path(output_path).resolve()),
        "applied": applied,
        "outline_after": get_template_outline(output_path),
        "policy": plan.get("policy", {}),
    }


def write_category_mapping_overlay(
    base_mapping_path: str,
    output_path: str,
    plan: dict,
) -> str:
    """把标题重命名同步到任务级语义映射副本，仍不绑定章节号。"""
    data = yaml.safe_load(Path(base_mapping_path).read_text(encoding="utf-8")) or {}
    outline = {node["id"]: node for node in plan.get("outline_before", [])}
    renamed = {}
    for operation in plan.get("operations", []):
        if operation.get("operation") != "rename":
            continue
        old = outline.get(operation.get("target_slot", ""), {}).get("title", "")
        new = _clean_title(operation.get("new_title", ""))
        if old and new:
            renamed[_norm(old)] = new

    def replace_title(value: str) -> str:
        return renamed.get(_norm(value), value)

    for group_name in ("semantic_roles", "categories"):
        for rule in (data.get(group_name) or {}).values():
            if not isinstance(rule, dict):
                continue
            headings = rule.get("target_heading_keywords")
            if isinstance(headings, str):
                rule["target_heading_keywords"] = replace_title(headings)
            elif isinstance(headings, list):
                rule["target_heading_keywords"] = [replace_title(str(item)) for item in headings]
            for key in ("target_heading", "target_parent_heading"):
                if rule.get(key):
                    rule[key] = replace_title(str(rule[key]))
    Path(output_path).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return output_path
