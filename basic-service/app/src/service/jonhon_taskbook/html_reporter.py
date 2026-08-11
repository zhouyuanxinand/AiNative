# -*- coding: utf-8 -*-
"""
html_reporter.py — 生成 HTML 可视化质量报告
输入: docx路径 + coverage_ledger.json + qa_gate_report.md
输出: 单文件 HTML（无外部依赖，可直接浏览器打开）
"""
from __future__ import annotations
import json, zipfile, re
from pathlib import Path
from lxml import etree
from datetime import datetime

W  = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{W}}}"
_RED_VALS = {"FF0000", "C00000", "E00000", "D00000", "F00000", "B00000"}


def _qa_scan(docx_path: str) -> dict:
    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml")
    root = etree.fromstring(xml)

    red_count = sum(
        1 for c in root.findall(f".//{_W}color")
        if (c.get(f"{_W}val") or "").upper() in _RED_VALS
    )
    hl_count = len(root.findall(f".//{_W}highlight"))
    para_count = len(root.findall(f".//{_W}p"))
    tbl_count  = len(root.findall(f".//{_W}tbl"))
    img_count  = len([e for e in root.iter() if e.tag.endswith("}blip")])

    headings = []
    for p in root.findall(f".//{_W}p"):
        ppr = p.find(f"{_W}pPr")
        if ppr is None:
            continue
        ps = ppr.find(f"{_W}pStyle")
        if ps is None:
            continue
        style = ps.get(f"{_W}val", "")
        is_heading = (
            "Heading" in style or "heading" in style
            or style in {"1", "2", "3", "4", "5"}
            or re.match(r"^\d$", style)
        )
        if is_heading:
            txt = "".join(t.text or "" for t in p.findall(f".//{_W}t")).strip()
            if txt:
                headings.append(txt)

    return {
        "red_count": red_count,
        "hl_count": hl_count,
        "para_count": para_count,
        "tbl_count": tbl_count,
        "img_count": img_count,
        "headings": headings,
        "qa_passed": red_count == 0 and hl_count == 0,
    }


def _load_ledger(ledger_path: str) -> dict | None:
    p = Path(ledger_path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_image_warnings(docx_path: str) -> list[str]:
    p = Path(docx_path).with_suffix(Path(docx_path).suffix + ".image_warnings.json")
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return [str(x) for x in data] if isinstance(data, list) else []
    except Exception:
        return []


def _load_qa_gate_report(docx_path: str | Path) -> dict:
    """读取 qa_gate_report.md，解析为结构化字典。"""
    docx = Path(docx_path)
    rpt = docx.with_suffix(".qa_gate_report.md")
    if not rpt.exists():
        rpt = docx.parent / "qa_gate_report.md"
    if not rpt.exists():
        return {"passed": None, "categories": {}, "warnings": []}
    lines = rpt.read_text(encoding="utf-8").splitlines()
    passed: bool | None = None
    categories: dict[str, list[str]] = {}
    gate_warnings: list[str] = []
    cur_cat: str | None = None
    for line in lines:
        if "\u2705 \u901a\u8fc7" in line:   # ✅ 通过
            passed = True
        elif "\u274c \u672a\u901a\u8fc7" in line:  # ❌ 未通过
            passed = False
        elif line.startswith("## \u8b66\u544a"):   # ## 警告
            cur_cat = "__warn__"
        elif line.startswith("## "):
            cur_cat = line[3:].strip()
            categories[cur_cat] = []
        elif line.startswith("- ") and cur_cat:
            item = line[2:].strip()
            if cur_cat == "__warn__":
                gate_warnings.append(item)
            else:
                categories.setdefault(cur_cat, []).append(item)
    return {"passed": passed, "categories": categories, "warnings": gate_warnings}


def _render_gate_panel(gate: dict) -> str:
    if gate["passed"] is None:
        return ""
    if gate["passed"]:
        return (
            '<div class="section gate-ok">'
            '<h2>🔍 QA 门禁结果</h2>'
            '<div style="color:#52c41a;font-weight:600;font-size:14px">✅ 全部门禁通过</div>'
            "</div>"
        )
    total = sum(len(v) for v in gate["categories"].values())
    rows = ""
    cat_colors = {
        "模板/污染": "#cf1322",
        "图题/图片": "#d46b08",
        "表格结构":  "#531dab",
        "关键内容":  "#0958d9",
        "格式/变更": "#874d00",
    }
    for cat, items in gate["categories"].items():
        color = cat_colors.get(cat, "#595959")
        badge = (
            f'<span style="display:inline-block;padding:1px 8px;border-radius:10px;'
            f'font-size:11px;font-weight:600;background:#fff1f0;color:{color};'
            f'border:1px solid {color};margin-right:6px">{cat}</span>'
        )
        for item in items:
            rows += f'<tr><td style="padding:6px 10px">{badge}</td><td style="padding:6px 10px;font-size:13px">{item}</td></tr>\n'
    warn_rows = "".join(
        f'<li style="font-size:13px;color:#595959;padding:2px 0">⚠ {w}</li>'
        for w in gate["warnings"]
    )
    warn_section = (
        f'<div style="margin-top:14px"><strong style="font-size:13px">警告（{len(gate["warnings"])} 项）</strong>'
        f'<ul style="padding-left:18px;margin-top:6px">{warn_rows}</ul></div>'
    ) if gate["warnings"] else ""
    return (
        '<div class="section gate-fail">'
        f'<h2>🔍 QA 门禁结果 &nbsp;<span style="font-size:13px;color:#ff4d4f;font-weight:400">❌ 未通过（{total} 项阻断）</span></h2>'
        '<table style="width:100%;border-collapse:collapse">'
        f'<tbody>{rows}</tbody></table>'
        f"{warn_section}"
        "</div>"
    )


def generate_report(docx_path: str, output_path: str | None = None) -> str:
    docx_path = Path(docx_path)
    if output_path is None:
        output_path = docx_path.with_suffix(".report.html")

    qa = _qa_scan(str(docx_path))
    gate = _load_qa_gate_report(str(docx_path))
    ledger_path = docx_path.with_suffix(".coverage_ledger.json")
    if not ledger_path.exists():
        ledger_path = docx_path.parent / "coverage_ledger.json"
    ledger = _load_ledger(str(ledger_path))
    image_warnings = _load_image_warnings(str(docx_path))

    coverage_rows = ""
    if ledger and "blocks" in ledger:
        for b in ledger["blocks"][:60]:
            covered = b.get("covered", False)
            btype   = b.get("block_type", b.get("type", ""))
            chapter = b.get("source_section", b.get("chapter", ""))
            assigned = b.get("assigned_section", "")
            preview  = b.get("summary", b.get("preview", str(b.get("raw_text", ""))[:60]))[:80]
            conf     = b.get("confidence", "")
            conf_str = f" ({int(conf * 100)}%)" if isinstance(conf, float) else ""
            icon     = "✅" if covered else "⚠️"
            row_cls  = "ok" if covered else "warn"
            coverage_rows += (
                f'<tr class="{row_cls}">'
                f"<td>{icon}</td>"
                f'<td style="font-size:12px">{chapter}</td>'
                f'<td><span style="background:#f0f0f0;padding:1px 6px;border-radius:4px;font-size:11px">{btype}</span></td>'
                f'<td style="font-size:12px;color:#555">{preview}</td>'
                f'<td style="font-size:11px;color:#aaa">{assigned}{conf_str}</td>'
                f"</tr>\n"
            )
        total_b    = len(ledger["blocks"])
        covered_n  = sum(1 for b in ledger["blocks"] if b.get("covered"))
        coverage_rows = (
            f'<tr style="background:#fafafa"><td colspan="5" style="padding:6px 10px;'
            f'font-size:12px;color:#888">共 {total_b} 条，已覆盖 {covered_n} 条'
            f'（{int(covered_n / total_b * 100) if total_b else 0}%）</td></tr>\n'
        ) + coverage_rows
    else:
        coverage_rows = '<tr><td colspan="5" style="color:#aaa;padding:12px">覆盖账本未生成</td></tr>'

    heading_list = "".join(
        f'<li style="padding:2px 0;font-size:13px">{h}</li>'
        for h in qa["headings"][:25]
    )

    # 顶部状态卡片优先用 gate 报告，若不可用则退化到 qa_scan
    if gate["passed"] is True:
        qa_color, qa_label = "#52c41a", "✅ 通过"
    elif gate["passed"] is False:
        total_issues = sum(len(v) for v in gate["categories"].values())
        qa_color  = "#ff4d4f"
        qa_label  = f"❌ {total_issues} 项"
    else:
        qa_color = "#52c41a" if qa["qa_passed"] else "#ff4d4f"
        qa_label = "✅ 通过" if qa["qa_passed"] else "❌ 未通过"

    red_warn = f'<div class="warn-box">⚠️ 残余红字: {qa["red_count"]} 处</div>' if qa["red_count"] else ""
    hl_warn  = f'<div class="warn-box">⚠️ 残余高亮: {qa["hl_count"]} 处</div>' if qa["hl_count"] else ""

    image_warning_rows = "".join(
        f'<li style="padding:4px 0;font-size:13px">🖼 {w}</li>'
        for w in image_warnings[:30]
    )
    image_warning_section = (
        '<div class="section">'
        '<h2>🖼 图片决策明细</h2>'
        f'<div style="font-size:13px;color:#666;margin-bottom:10px">共 {len(image_warnings)} 条图片筛选提示，以下展示前 30 条。</div>'
        f'<ul>{image_warning_rows}</ul>'
        "</div>"
    ) if image_warnings else ""

    gate_panel = _render_gate_panel(gate)
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")
    fname = docx_path.name

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>质量报告 — {fname}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:#f5f7fa;color:#222;padding:24px}}
.wrap{{max-width:980px;margin:0 auto}}
h1{{font-size:20px;font-weight:700;margin-bottom:4px}}
.meta{{color:#888;font-size:13px;margin-bottom:24px}}
.grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:20px}}
.card{{background:#fff;border-radius:10px;padding:18px 14px;text-align:center;
       box-shadow:0 1px 6px rgba(0,0,0,.07)}}
.card .num{{font-size:28px;font-weight:700;margin-bottom:4px}}
.card .lbl{{font-size:12px;color:#888}}
.card.qa .num{{color:{qa_color}}}
.section{{background:#fff;border-radius:10px;padding:20px;
          box-shadow:0 1px 6px rgba(0,0,0,.07);margin-bottom:16px}}
.section h2{{font-size:15px;font-weight:600;margin-bottom:14px;
             padding-bottom:8px;border-bottom:1px solid #f0f0f0}}
.gate-ok{{border-left:4px solid #52c41a}}
.gate-fail{{border-left:4px solid #ff4d4f}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:7px 10px;background:#fafafa;color:#666;
    font-weight:500;border-bottom:1px solid #eee}}
td{{padding:7px 10px;border-bottom:1px solid #f5f5f5}}
tr.ok td:first-child{{color:#52c41a}}
tr.warn td:first-child{{color:#faad14}}
.warn-box{{background:#fff2f0;border:1px solid #ffccc7;border-radius:6px;
           padding:8px 14px;margin-bottom:8px;font-size:13px}}
ul{{padding-left:18px;line-height:1.7}}
</style>
</head>
<body>
<div class="wrap">
  <h1>📄 研制任务书质量报告</h1>
  <div class="meta">文件: {fname} &nbsp;|&nbsp; 生成时间: {now}</div>

  <div class="grid">
    <div class="card qa">
      <div class="num">{qa_label}</div>
      <div class="lbl">QA门禁</div>
    </div>
    <div class="card">
      <div class="num" style="color:#1890ff">{qa["para_count"]}</div>
      <div class="lbl">段落数</div>
    </div>
    <div class="card">
      <div class="num" style="color:#722ed1">{qa["tbl_count"]}</div>
      <div class="lbl">表格数</div>
    </div>
    <div class="card">
      <div class="num" style="color:#fa8c16">{qa["img_count"]}</div>
      <div class="lbl">图片数</div>
    </div>
    <div class="card">
      <div class="num" style="color:#13c2c2">{len(qa["headings"])}</div>
      <div class="lbl">章节数</div>
    </div>
  </div>

  {'<div class="section">' + red_warn + hl_warn + '</div>' if red_warn or hl_warn else ''}

  {gate_panel}

  <div class="section">
    <h2>📋 章节结构</h2>
    <ul>{heading_list}</ul>
  </div>

  {image_warning_section}

  <div class="section">
    <h2>📊 输入覆盖账本（前60条）</h2>
    <table>
      <thead><tr><th>状态</th><th>来源章节</th><th>类型</th><th>内容预览</th><th>归属章节</th></tr></thead>
      <tbody>{coverage_rows}</tbody>
    </table>
  </div>
</div>
</body>
</html>"""

    Path(output_path).write_text(html, encoding="utf-8")
    return str(output_path)


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("用法: python html_reporter.py <输出文档.docx>")
    else:
        out = generate_report(path)
        print(f"报告已生成: {out}")
