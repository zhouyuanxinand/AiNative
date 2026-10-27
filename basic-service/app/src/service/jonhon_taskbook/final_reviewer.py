"""生成后审查：占位符、幻觉、行业串项、Ground Truth 对照。"""
import json
import os
import re
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

from lxml import etree

from .docx_io import get_para_text, get_cell_text

from .document_zone_detector import ZONE_TYPE_LABELS

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

PLACEHOLDER_RE = re.compile(
    r"……|\.\.\.|_{2,}|\bXX\b|xxx|20[Xx]{2}|20xx|适用时保留|没有可写",
    re.I,
)

HALLUCINATION_PATTERNS = [
    (r"80000\s*h", "MTBF=80000h 无来源，正确值应来自产品规范3.6.2"),
    (r"MTTR\s*[≤<]", "MTTR定量要求无来源"),
    (r"故障检测率|故障隔离率|虚警率", "测试性定量指标无来源"),
    (r"电池包|USCAR|IP68|整车主继电器|快充电流", "行业串项：汽车连接器模板残留"),
    (r"中航光电年|20中航光电", "封面占位符错误替换"),
]

CROSS_DOC_CHECKS = [
    {
        "name": "机械寿命用户列保护",
        "pattern": r"机械寿命",
        "must_contain_user": "20",
        "message": "用户要求列应保留≥20次，不能全部被25次覆盖",
    },
]


def scan_docx(docx_path: str) -> Dict[str, Any]:
    with zipfile.ZipFile(docx_path) as z:
        root = etree.fromstring(z.read("word/document.xml"))

    issues: List[Dict[str, str]] = []
    ellipsis = xx = 0
    for i, p in enumerate(root.findall(f".//{{{W}}}p")):
        t = get_para_text(p)
        if "……" in t:
            ellipsis += 1
            issues.append({"severity": "HIGH", "type": "placeholder", "para": i, "text": t[:120]})
        if re.search(r"\bXX\b", t) and "xxxx" not in t.lower() and "XXXX" not in t:
            xx += 1
            issues.append({"severity": "HIGH", "type": "placeholder_xx", "para": i, "text": t[:120]})
        for pat, msg in HALLUCINATION_PATTERNS:
            if re.search(pat, t, re.I):
                issues.append({"severity": "BLOCKER", "type": "hallucination", "para": i, "text": t[:120], "message": msg})

    images = len(root.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"))
    return {
        "ellipsis": ellipsis,
        "xx": xx,
        "images": images,
        "issues": issues,
        "issue_count": len(issues),
    }


def compare_to_ground_truth(docx_path: str, gt_path: str) -> List[Dict[str, str]]:
    if not os.path.exists(gt_path):
        return []
    with open(gt_path, "r", encoding="utf-8") as f:
        gt_rows = json.load(f)
    with zipfile.ZipFile(docx_path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    doc_text = "\n".join(get_para_text(p) for p in root.findall(f".//{{{W}}}p"))

    mismatches = []
    for row in gt_rows:
        if row.get("category") != "技术指标":
            continue
        conflict = row.get("conflict", "")
        if not conflict:
            continue
        name = row.get("field_name", "")
        if re.search(r"80000\s*h", doc_text, re.I) and "MTBF" in name:
            mismatches.append({"field": name, "conflict": conflict, "severity": "BLOCKER"})
        if re.search(r"MTTR\s*[≤<=]", doc_text) and "维修性" in name and "幻觉" in conflict:
            mismatches.append({"field": name, "conflict": conflict, "severity": "BLOCKER"})
    return mismatches


def validate_v3_user_column(docx_path: str, gt_path: str = "") -> List[Dict[str, str]]:
    """V3：检查规范补充项是否误入用户要求列。"""
    issues = []
    if not os.path.exists(docx_path):
        return issues
    with zipfile.ZipFile(docx_path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    for table in root.findall(f".//{{{W}}}tbl"):
        rows = table.findall(f"{{{W}}}tr")
        if not rows:
            continue
        header = "".join(get_para_text(rows[0]).split())
        if "用户要求" not in header:
            continue
        spec_only_names = [
            "接触件插入力和分离力", "接触件弹力", "冲击", "加速度", "可焊性", "耐焊接热",
        ]
        for row in rows[1:]:
            cells = row.findall(f"{{{W}}}tc")
            if len(cells) < 2:
                continue
            name = get_para_text(cells[0]).strip()
            user_val = get_para_text(cells[1]).strip()
            if any(n in name for n in spec_only_names):
                if user_val and user_val not in {"/", "无", "用户未明确"}:
                    issues.append({
                        "severity": "BLOCKER",
                        "type": "v3_user_column",
                        "field": name,
                        "message": f"规范补充项「{name}」用户列应为/，当前为：{user_val[:40]}",
                    })
    return issues


def build_review_report(
    docx_path: str,
    pipeline_report: Dict[str, Any],
    identity_result: Dict[str, Any],
    gt_json_path: str = "",
) -> Dict[str, Any]:
    scan = scan_docx(docx_path)
    gt_mismatches = compare_to_ground_truth(docx_path, gt_json_path) if gt_json_path else []
    v3_issues = validate_v3_user_column(docx_path, gt_json_path)

    zone_scan = pipeline_report.get("zone_scan") or {}
    zone_blockers = zone_scan.get("blockers", [])
    zone_high = [
        z for z in zone_scan.get("zones", [])
        if z.get("severity") == "HIGH"
    ]

    blockers = [i for i in scan["issues"] if i["severity"] == "BLOCKER"]
    blockers += identity_result.get("blockers", [])
    blockers += [{"type": "ground_truth", **m} for m in gt_mismatches]
    blockers += v3_issues
    for z in zone_blockers:
        blockers.append({
            "type": "fill_zone",
            "severity": "BLOCKER",
            "message": f"{z.get('zone_type', '')} @ {z.get('location', '')}: "
                       f"{z.get('heading') or z.get('snippet', '')[:60]}",
        })

    high = [i for i in scan["issues"] if i["severity"] == "HIGH"]
    for z in zone_high:
        high.append({
            "type": "fill_zone",
            "severity": "HIGH",
            "message": f"{z.get('zone_type', '')} {z.get('heading', '')[:40]} — {z.get('suggested_action', '')}",
        })
    warnings = identity_result.get("warnings", [])

    passed = len(blockers) == 0 and scan["ellipsis"] == 0 and scan["xx"] == 0

    cover_fill = (pipeline_report.get("cover_basis") or {}).get("cover", {})

    report = {
        "generated_at": datetime.now().isoformat(),
        "docx_path": docx_path,
        "passed": passed,
        "ready_for_delivery": False,
        "summary": {
            "blockers": len(blockers),
            "high": len(high),
            "warnings": len(warnings),
            "placeholders_ellipsis": scan["ellipsis"],
            "placeholders_xx": scan["xx"],
            "images": scan["images"],
            "fill_zones_total": zone_scan.get("zone_count", 0),
            "fill_zones_blockers": zone_scan.get("blocker_count", 0),
            "fill_zones_by_type": zone_scan.get("by_type", {}),
            "cover_filled": cover_fill,
            "fill_stats": {
                k: pipeline_report.get(k)
                for k in ["text_slots", "indicator_table", "interface_42", "schedule_table", "images_inserted"]
            },
        },
        "zone_scan": zone_scan,
        "blockers": blockers,
        "high_issues": high[:40],
        "warnings": warnings,
        "identity": identity_result.get("identities", {}),
    }
    return report


def render_review_html(report: Dict[str, Any]) -> str:
    status = "通过" if report["passed"] else "未通过"
    color = "#16a34a" if report["passed"] else "#dc2626"
    s = report["summary"]
    zone_scan = report.get("zone_scan") or {}
    by_type = s.get("fill_zones_by_type") or zone_scan.get("by_type") or {}

    lines = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<title>研制任务书审查报告</title>",
        "<style>body{font-family:Microsoft YaHei,sans-serif;padding:24px;max-width:960px;margin:auto}",
        "h1{color:#333} h2{color:#555;margin-top:28px} .ok{color:#16a34a} .bad{color:#dc2626} .warn{color:#ca8a04}",
        "table{border-collapse:collapse;width:100%;margin:12px 0}",
        "th,td{border:1px solid #ccc;padding:8px;text-align:left;font-size:13px}",
        "th{background:#f3f4f6}",
        ".tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px}",
        ".tag-blocker{background:#fee2e2;color:#991b1b}",
        ".tag-high{background:#fef3c7;color:#92400e}",
        ".tag-medium{background:#e0e7ff;color:#3730a3}</style></head><body>",
        f"<h1>研制任务书审查报告</h1>",
        f"<p>生成时间：{report['generated_at']}</p>",
        f"<p>总体结论：<b style='color:{color}'>{status}</b> "
        f"（BLOCKER {s['blockers']} / HIGH {s['high']} / 警告 {s['warnings']}）</p>",
        f"<p>占位符 ……={s['placeholders_ellipsis']}，XX={s['placeholders_xx']}，图片={s['images']}</p>",
    ]

    # 封面填充状态
    cover = s.get("cover_filled") or {}
    if cover:
        lines.append("<h2>封面填充</h2><table><tr><th>项</th><th>已填</th></tr>")
        for k, v in cover.items():
            if k == "cover_meta":
                continue
            lines.append(f"<tr><td>{k}</td><td class='ok'>{v}</td></tr>")
        meta = cover.get("cover_meta") or {}
        if meta:
            lines.append("</table><p>元数据：")
            lines.append(f"产品={meta.get('product_name','')}，使用单位={meta.get('customer_unit','')}，"
                         f"研制单位={meta.get('developer_unit','')}</p>")
        else:
            lines.append("</table>")

    # 待填区域地图
    lines.append(
        f"<h2>待填区域地图</h2>"
        f"<p>共扫描 <b>{s.get('fill_zones_total', 0)}</b> 处待填/可疑区域，"
        f"其中 BLOCKER <b class='bad'>{s.get('fill_zones_blockers', 0)}</b> 处</p>"
    )
    if by_type:
        lines.append("<p>")
        for zt, cnt in sorted(by_type.items(), key=lambda x: -x[1]):
            label = ZONE_TYPE_LABELS.get(zt, zt)
            lines.append(f"<span class='tag tag-medium'>{label} {cnt}</span> ")
        lines.append("</p>")

    lines.append(
        "<table><tr><th>严重度</th><th>类型</th><th>位置</th><th>标题/片段</th><th>建议操作</th><th>可自动填</th></tr>"
    )
    for z in zone_scan.get("zones", [])[:35]:
        sev = z.get("severity", "")
        sev_cls = "bad" if sev == "BLOCKER" else ("warn" if sev == "HIGH" else "")
        zt = ZONE_TYPE_LABELS.get(z.get("zone_type", ""), z.get("zone_type", ""))
        lines.append(
            f"<tr><td class='{sev_cls}'>{sev}</td><td>{zt}</td>"
            f"<td>{z.get('location', '')}</td>"
            f"<td>{(z.get('heading') or z.get('snippet', ''))[:80]}</td>"
            f"<td>{z.get('suggested_action', '')[:100]}</td>"
            f"<td>{'是' if z.get('auto_fillable') else '否'}</td></tr>"
        )
    lines.append("</table>")

    lines.append("<h2>BLOCKER</h2><table><tr><th>类型</th><th>说明</th></tr>")
    for b in report.get("blockers", [])[:25]:
        msg = b.get("message") or b.get("text") or str(b)
        lines.append(f"<tr><td>{b.get('type','')}</td><td class='bad'>{msg[:200]}</td></tr>")
    lines.append("</table><h2>填充统计</h2><table><tr><th>项</th><th>值</th></tr>")
    for k, v in s.get("fill_stats", {}).items():
        lines.append(f"<tr><td>{k}</td><td>{v}</td></tr>")
    lines.append("</table></body></html>")
    return "\n".join(lines)


def save_review_outputs(report: Dict[str, Any], base_path: str) -> Dict[str, str]:
    json_path = base_path + "_ReviewReport.json"
    html_path = base_path + "_ReviewReport.html"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_review_html(report))
    return {"json": json_path, "html": html_path}
