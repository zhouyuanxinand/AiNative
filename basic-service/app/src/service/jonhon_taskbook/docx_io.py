import os
import shutil
import zipfile
from typing import Dict, List, Optional, Tuple

from lxml import etree

from .renderer.table_style_engine import (
    DEFAULT_FONT, DEFAULT_SIZE_HALF_POINTS, set_run_typography,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MANUAL_FILL_MARKER = "【人工填写】"
MANUAL_FILL_COLOR = "FF0000"


def get_para_text(para) -> str:
    return "".join(t.text or "" for t in para.findall(f".//{{{W}}}t"))


def get_cell_text(cell) -> str:
    return "".join(t.text or "" for t in cell.findall(f".//{{{W}}}t")).strip()


def xml_esc(text: str) -> str:
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def set_para_text(para, text: str) -> None:
    for child in list(para):
        para.remove(child)
    r = etree.SubElement(para, f"{{{W}}}r")
    t = etree.SubElement(r, f"{{{W}}}t")
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text


def fill_cell(cell, text: str) -> None:
    for child in list(cell):
        cell.remove(child)
    p = etree.SubElement(cell, f"{{{W}}}p")
    r = etree.SubElement(p, f"{{{W}}}r")
    t = etree.SubElement(r, f"{{{W}}}t")
    t.text = xml_esc(text)


def fill_cell_with_manual_marker(
    cell,
    text: str = "",
    *,
    marker: str = MANUAL_FILL_MARKER,
) -> None:
    """Fill a cell and append one controlled, red manual-entry marker.

    The caller must make the business decision that manual input is required.
    This renderer deliberately does not infer that decision from an empty value,
    a slash, a signature area, or a template placeholder.
    """
    for child in list(cell):
        cell.remove(child)
    paragraph = etree.SubElement(cell, f"{{{W}}}p")

    value = str(text or "").strip()
    if value:
        value_run = etree.SubElement(paragraph, f"{{{W}}}r")
        value_text = etree.SubElement(value_run, f"{{{W}}}t")
        value_text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        value_text.text = value
        etree.SubElement(value_run, f"{{{W}}}br")

    marker_run = etree.SubElement(paragraph, f"{{{W}}}r")
    marker_props = etree.SubElement(marker_run, f"{{{W}}}rPr")
    set_run_typography(marker_run, DEFAULT_FONT, DEFAULT_SIZE_HALF_POINTS)
    color = etree.SubElement(marker_props, f"{{{W}}}color")
    color.set(f"{{{W}}}val", MANUAL_FILL_COLOR)
    for key in ("i", "iCs"):
        italic = etree.SubElement(marker_props, f"{{{W}}}{key}")
        italic.set(f"{{{W}}}val", "0")
    marker_text = etree.SubElement(marker_run, f"{{{W}}}t")
    marker_text.text = marker


def clear_cell_content(cell) -> None:
    for child in list(cell):
        cell.remove(child)
    p = etree.SubElement(cell, f"{{{W}}}p")
    r = etree.SubElement(p, f"{{{W}}}r")
    t = etree.SubElement(r, f"{{{W}}}t")
    t.text = ""


def load_document_xml(docx_path: str) -> etree._Element:
    with zipfile.ZipFile(docx_path, "r") as z:
        return etree.fromstring(z.read("word/document.xml"))


def save_document_xml(
    output_path: str,
    root: etree._Element,
    template_path: str,
    merge_img_from: str = None,
) -> None:
    """保存 document.xml；merge_img_from 时合并源文档 media 并重映射 rId。"""
    rmap: Dict[str, str] = {}
    NSMAP = {
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }

    if merge_img_from and os.path.exists(merge_img_from):
        with zipfile.ZipFile(template_path, "r") as zt:
            template_rels = {}
            if "word/_rels/document.xml.rels" in zt.namelist():
                tr = etree.fromstring(zt.read("word/_rels/document.xml.rels"))
                rels_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
                for rel in tr.findall(f"{{{rels_ns}}}Relationship"):
                    template_rels[rel.get("Id", "")] = rel.get("Target", "")

        next_rid = 1
        for rid in template_rels:
            if rid.startswith("rId"):
                try:
                    next_rid = max(next_rid, int(rid[3:]) + 1)
                except ValueError:
                    pass

        for blip in root.findall(".//a:blip", NSMAP):
            embed = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed", "")
            if not embed or embed in template_rels:
                continue
            if embed not in rmap:
                rmap[embed] = f"rId{next_rid}"
                next_rid += 1
            blip.set("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed", rmap[embed])

    new_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    temp_path = output_path + ".tmp"
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass

    merged_rels_xml = None
    if merge_img_from and os.path.exists(merge_img_from) and rmap:
        rels_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        with zipfile.ZipFile(template_path, "r") as zt:
            if "word/_rels/document.xml.rels" in zt.namelist():
                rels_root = etree.fromstring(zt.read("word/_rels/document.xml.rels"))
            else:
                rels_root = etree.Element(f"{{{rels_ns}}}Relationships")
        with zipfile.ZipFile(merge_img_from, "r") as zs:
            src_rels_full = {}
            if "word/_rels/document.xml.rels" in zs.namelist():
                sr = etree.fromstring(zs.read("word/_rels/document.xml.rels"))
                for rel in sr.findall(f"{{{rels_ns}}}Relationship"):
                    src_rels_full[rel.get("Id", "")] = (rel.get("Type", ""), rel.get("Target", ""))
        for old_rid, new_rid in rmap.items():
            if old_rid in src_rels_full:
                rtype, target = src_rels_full[old_rid]
                new_rel = etree.SubElement(rels_root, f"{{{rels_ns}}}Relationship")
                new_rel.set("Id", new_rid)
                new_rel.set("Type", rtype)
                new_rel.set("Target", target)
        merged_rels_xml = etree.tostring(rels_root, xml_declaration=True, encoding="UTF-8", standalone=True)

    source_path = output_path if os.path.exists(output_path) else template_path
    
    with zipfile.ZipFile(source_path, "r") as zin:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            existing_media = set()
            for item in zin.infolist():
                if item.filename == "word/document.xml":
                    zout.writestr(item, new_xml)
                elif item.filename == "word/_rels/document.xml.rels" and merged_rels_xml:
                    zout.writestr(item, merged_rels_xml)
                else:
                    if item.filename.startswith("word/media/"):
                        existing_media.add(os.path.basename(item.filename))
                    zout.writestr(item, zin.read(item.filename))

            if merge_img_from and os.path.exists(merge_img_from):
                with zipfile.ZipFile(merge_img_from, "r") as zsrc:
                    for item in zsrc.infolist():
                        if not item.filename.startswith("word/media/"):
                            continue
                        base = os.path.basename(item.filename)
                        dest = item.filename
                        if base in existing_media:
                            n, e = os.path.splitext(base)
                            counter = 1
                            new_base = f"{n}_src{e}"
                            while new_base in existing_media:
                                new_base = f"{n}_src{counter}{e}"
                                counter += 1
                            dest = f"word/media/{new_base}"
                            existing_media.add(new_base)
                        else:
                            existing_media.add(base)
                        zout.writestr(zipfile.ZipInfo(dest), zsrc.read(item.filename))

    if os.path.exists(output_path):
        os.remove(output_path)
    os.rename(temp_path, output_path)


def prepare_output(template_path: str, output_path: str) -> etree._Element:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    shutil.copy2(template_path, output_path)
    return load_document_xml(output_path)


def find_section_range_by_keywords(
    root,
    start_keywords: List[str],
    end_keywords: List[str],
) -> Optional[Tuple[int, int, list]]:
    paras = list(root.findall(f".//{{{W}}}p"))
    start = end = -1
    for i, p in enumerate(paras):
        text = get_para_text(p).strip()
        if start == -1 and any(k in text for k in start_keywords):
            start = i
            continue
        if start != -1 and any(k in text for k in end_keywords):
            end = i
            break
    if start == -1:
        return None
    if end == -1:
        end = len(paras)
    return start, end, paras


def delete_paragraph_range(paras, start: int, end: int) -> int:
    deleted = 0
    for i in range(start, end):
        p = paras[i]
        parent = p.getparent()
        if parent is not None:
            parent.remove(p)
            deleted += 1
    return deleted
