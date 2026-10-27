"""Rebind figure references by verified source identity, never by global numbers.

The same source figure may occur in several destination chapters. Its copies
are equivalent reference targets; use the closest copy. Different source
figures remain ambiguous even when they originally shared an ordinal.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from lxml import etree

from .source_scope import normalize_source_display_text
from .figure_pairing import pair_figure_captions

_CAPTION = re.compile(r"^(\s*图\s*)(\d+)(?=\D|$)(.*)$", re.S)
_REFERENCE = re.compile(r"图\s*(\d+)(?!\d)")
_SOURCE_BOOKMARK = re.compile(r"^_tb_src_([0-9a-f]{20})_\d+$")


def _source_key(source_id):
    return hashlib.sha256(str(source_id).encode("utf-8")).hexdigest()[:20]


def mark_source_element(element, source_id, document):
    """Bind copied paragraphs to source IDs using standard invisible bookmarks."""
    existing = list(document.element.iter(qn("w:bookmarkStart")))
    existing_ids = [int(n.get(qn("w:id"), "0")) for n in existing
                    if n.get(qn("w:id"), "0").isdigit()]
    next_id = max(existing_ids, default=-1) + 1
    names = {n.get(qn("w:name")) for n in existing}
    source_key = _source_key(source_id)
    for paragraph in element.iter(qn("w:p")):
        if not _REFERENCE.search(_text(paragraph)):
            continue
        if any(_SOURCE_BOOKMARK.match(n.get(qn("w:name"), ""))
               for n in paragraph.iter(qn("w:bookmarkStart"))):
            continue
        name = f"_tb_src_{source_key}_{next_id}"
        while name in names:
            next_id += 1
            name = f"_tb_src_{source_key}_{next_id}"
        start, end = etree.Element(qn("w:bookmarkStart")), etree.Element(qn("w:bookmarkEnd"))
        start.set(qn("w:id"), str(next_id))
        start.set(qn("w:name"), name)
        end.set(qn("w:id"), str(next_id))
        paragraph.insert(1 if len(paragraph) and paragraph[0].tag == qn("w:pPr") else 0, start)
        paragraph.append(end)
        names.add(name)
        next_id += 1


def _caption_match(text):
    match = _CAPTION.match(text)
    if match and re.match(r"\s*(?:所示|中的|中所示)", match.group(3)):
        return None
    return match


def _text(element):
    return "".join(node.text or "" for node in element.iter(qn("w:t")))


def _normal(text):
    return normalize_source_display_text(text)


def _skeleton(text):
    return _normal(_REFERENCE.sub("图<reference>", text))


def _paragraphs(document):
    for body_index, block in enumerate(document.element.body):
        for paragraph_index, paragraph in enumerate(block.iter(qn("w:p"))):
            yield body_index, paragraph_index, paragraph


def _caption_images(document):
    paragraphs = list(_paragraphs(document))
    media = {}
    for order, (_, _, paragraph) in enumerate(paragraphs):
        hashes = set()
        for node in paragraph.iter():
            for attribute in (qn("r:embed"), qn("r:id")):
                relation = document.part.rels.get(node.get(attribute))
                if relation is not None and not relation.is_external and relation.reltype.endswith("/image"):
                    hashes.add(hashlib.sha256(relation.target_part.blob).hexdigest())
        if hashes:
            media[order] = hashes
    pairs = pair_figure_captions([_text(p) for _, _, p in paragraphs], set(media),
                                lambda text: text if _caption_match(text) else "")
    result = defaultdict(set)
    for image_order, (_, caption_order, _) in pairs.items():
        body_index, paragraph_index, _ = paragraphs[caption_order]
        result[(body_index, paragraph_index)].update(media[image_order])
    return result


def _paragraph_scopes(document, paragraphs):
    scopes, current = {}, -1
    for order, (_, _, element) in enumerate(paragraphs):
        if element.getparent() is document.element.body:
            properties = [element.find(qn("w:pPr"))]
            style = Paragraph(element, document).style
            while style is not None:
                properties.append(style.element.find(qn("w:pPr")))
                style = style.base_style
            for properties_node in properties:
                outline = properties_node.find(qn("w:outlineLvl")) if properties_node is not None else None
                if outline is not None:
                    if int(outline.get(qn("w:val"), "9")) < 9:
                        current = order
                    break
        scopes[order] = current
    return scopes


def _replace_spans(paragraph, replacements):
    """Change only digit spans, including numbers split across formatted runs."""
    for start, end, replacement in sorted(replacements, reverse=True):
        nodes = list(paragraph.iter(qn("w:t")))
        offset, inserted = 0, False
        for node in nodes:
            value = node.text or ""
            node_end = offset + len(value)
            if offset < end and node_end > start:
                left, right = max(0, start - offset), min(len(value), end - offset)
                node.text = value[:left] + (replacement if not inserted else "") + value[right:]
                inserted = True
            offset = node_end


def load_figure_classification(output_path):
    for suffix in (".effective_requirement_classification.json", ".requirement_classification.json"):
        path = Path(output_path).with_suffix(suffix)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _verified_sources(classification, report):
    documents, images, paragraphs, seen = {}, {}, [], set()
    for block in (classification or {}).get("source_blocks", []):
        path, index = block.get("source_path"), block.get("body_index")
        source_id = str(block.get("id", ""))
        if not _REFERENCE.search(str(block.get("text", ""))):
            continue
        try:
            if not path or type(index) is not int or index < 0:
                raise ValueError("missing source coordinates")
            path = str(Path(path).resolve())
            if path not in documents:
                documents[path] = Document(path)
                images[path] = _caption_images(documents[path])
            element = documents[path].element.body[index]
            actual = _text(element)
            expected_hash = (block.get("element_content_hash") if block.get("is_fragment")
                             else block.get("content_hash"))
            digest = hashlib.sha256(re.sub(r"\s+", "", actual).encode("utf-8")).hexdigest()
            if not expected_hash or digest != expected_hash:
                raise ValueError("source content hash mismatch")
            if block.get("is_fragment") or block.get("parent_source_id"):
                texts = [(0, str(block.get("text", "")))]
                if _normal(texts[0][1]) not in _normal(actual):
                    raise ValueError("source fragment mismatch")
            else:
                texts = [(i, _text(p)) for i, p in enumerate(element.iter(qn("w:p")))]
            for paragraph_index, text in texts:
                if not _REFERENCE.search(text):
                    continue
                key = (path, index, paragraph_index, text, source_id)
                if key in seen:
                    continue
                seen.add(key)
                paragraphs.append({"source_path": path, "source_body_index": index,
                                   "source_paragraph_index": paragraph_index,
                                   "source_id": source_id, "text": text,
                                   "image_hashes": sorted(images[path].get((index, paragraph_index), set()))})
        except (OSError, ValueError, IndexError, KeyError, PackageNotFoundError) as exc:
            report["unverifiable_sources"].append({"source_id": source_id, "reason": str(exc)})
    return paragraphs


def _analyze(document, classification, *, renumber):
    report = {"policy": "verified_source_figure_identity", "captions": [], "references": [],
              "violations": [], "unverifiable_sources": [], "verified_texts": {}}
    sources = _verified_sources(classification, report)
    source_figures, source_signatures, source_references = defaultdict(dict), defaultdict(set), defaultdict(list)
    for source in sources:
        caption = _caption_match(source["text"])
        if caption:
            signature = _normal(caption.group(3))
            identity = (source["source_path"], source["source_body_index"], source["source_paragraph_index"])
            source_figures[(source["source_path"], int(caption.group(2)))][identity] = (source, signature)
            source_signatures[signature].add(identity)
        else:
            source_references[_skeleton(source["text"])].append(source)

    paragraphs = list(_paragraphs(document))
    output_images = _caption_images(document)
    scopes = _paragraph_scopes(document, paragraphs)
    output_figures = defaultdict(list)
    changes = []
    caption_count = 0
    for order, (body_index, paragraph_index, paragraph) in enumerate(paragraphs):
        caption = _caption_match(_text(paragraph))
        if not caption:
            continue
        caption_count += 1
        current = int(caption.group(2))
        target = caption_count if renumber else current
        record = {"output_body_index": body_index, "output_paragraph_index": paragraph_index,
                  "current_number": current, "output_number": target, "order": order,
                  "image_hashes": sorted(output_images.get((body_index, paragraph_index), set()))}
        output_figures[_normal(caption.group(3))].append(record)
        report["captions"].append({k: v for k, v in record.items() if k != "order"})
        if current != target:
            changes.append((paragraph, [(caption.start(2), caption.end(2), str(target))]))

    for order, (body_index, paragraph_index, paragraph) in enumerate(paragraphs):
        text = _text(paragraph)
        matches = list(_REFERENCE.finditer(text))
        if not matches or _caption_match(text):
            continue
        candidates = source_references.get(_skeleton(text), [])
        bound_sources = {_SOURCE_BOOKMARK.match(node.get(qn("w:name"), "")).group(1)
                         for node in paragraph.iter(qn("w:bookmarkStart"))
                         if _SOURCE_BOOKMARK.match(node.get(qn("w:name"), ""))}
        used_unverifiable = [source for source in report["unverifiable_sources"]
                             if _source_key(source["source_id"]) in bound_sources]
        if used_unverifiable:
            for source in used_unverifiable:
                report["violations"].append({"code": "FIGURE_REFERENCE_SOURCE_UNVERIFIABLE",
                                             **source, "output_body_index": body_index,
                                             "output_paragraph_index": paragraph_index,
                                             "output_text": text})
            continue
        if bound_sources:
            candidates = [source for source in candidates if _source_key(source["source_id"]) in bound_sources]
        if not candidates:
            # Template-owned references without classified provenance retain
            # their text. They cannot justify rewriting another source's text.
            continue
        resolved, unresolved = [], []
        for source in candidates:
            targets = []
            for match in _REFERENCE.finditer(source["text"]):
                old_number = int(match.group(1))
                figures = source_figures.get((source["source_path"], old_number), {})
                if len(figures) != 1:
                    unresolved.append({"source_id": source["source_id"], "source_number": old_number,
                                       "reason": "source_figure_not_unique"})
                    break
                identity, (caption_source, signature) = next(iter(figures.items()))
                source_media = caption_source["image_hashes"]
                copies = [item for item in output_figures.get(signature, [])
                          if source_media and item["image_hashes"] == source_media]
                if len(signature) < 2 or not copies:
                    unresolved.append({"source_id": source["source_id"], "source_number": old_number,
                                       "reason": "output_figure_not_identifiable"})
                    break
                source_follows = caption_source["source_body_index"] > source["source_body_index"]
                selected = min(copies, key=lambda item: (
                    scopes[item["order"]] != scopes[order],
                    (item["order"] > order) != source_follows,
                    abs(item["order"] - order), item["order"],
                ))
                targets.append({"source_number": old_number, "output_number": selected["output_number"],
                                "source_caption_body_index": caption_source["source_body_index"],
                                "output_caption_body_index": selected["output_body_index"],
                                "caption_image_hashes": source_media})
            else:
                resolved.append((source, targets))
        choices = {tuple(item["output_number"] for item in targets) for _, targets in resolved}
        coordinates = {"output_body_index": body_index, "output_paragraph_index": paragraph_index}
        if unresolved or len(choices) != 1:
            report["violations"].append({"code": "FIGURE_REFERENCE_AMBIGUOUS", **coordinates,
                                         "source_ids": sorted({s["source_id"] for s in candidates}),
                                         "source_id": candidates[0]["source_id"],
                                         "output_text": text, "unresolved": unresolved})
            continue
        numbers = next(iter(choices))
        replacements = [(m.start(1), m.end(1), str(number)) for m, number in zip(matches, numbers)]
        expected = text
        for start, end, replacement in reversed(replacements):
            expected = expected[:start] + replacement + expected[end:]
        for source, targets in resolved:
            for target in targets:
                report["references"].append({**source, **coordinates, **target,
                                              "expected_text": expected, "output_text": text,
                                              "source_binding": "bookmark" if bound_sources else "unique_source_text"})
            report["verified_texts"].setdefault(source["source_id"], []).append(expected)
        if text != expected:
            report["violations"].append({"code": "FIGURE_REFERENCE_MISMATCH", **coordinates,
                                         "source_id": resolved[0][0]["source_id"],
                                         "output_text": text, "expected_text": expected})
            changes.append((paragraph, replacements))
    return report, changes


def audit_figure_references(output_path, classification=None):
    """Read-only verification plus exact expected source-to-output text mapping."""
    if classification is None:
        classification = load_figure_classification(output_path)
    return _analyze(Document(output_path), classification, renumber=False)[0]


def synchronize_figure_references(output_path, classification=None):
    """Renumber captions and synchronize provable references; return an audit.

    Can be called after deleting duplicate figures. Re-reads source coordinates
    on every pass, so overlapping old/new ordinals cannot cascade on reruns.
    Ambiguous references remain unchanged and are returned as gate violations.
    """
    output_path = Path(output_path)
    if classification is None:
        classification = load_figure_classification(output_path)
    document = Document(output_path)
    before, changes = _analyze(document, classification, renumber=True)
    for paragraph, replacements in changes:
        _replace_spans(paragraph, replacements)
    if changes:
        with tempfile.NamedTemporaryFile(dir=output_path.parent, suffix=".docx", delete=False) as stream:
            temporary = Path(stream.name)
        try:
            with zipfile.ZipFile(output_path) as source, zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target:
                for item in source.infolist():
                    data = source.read(item.filename)
                    if item.filename == "word/document.xml":
                        data = etree.tostring(document.element, xml_declaration=True, encoding="UTF-8", standalone=True)
                    target.writestr(item, data)
            os.replace(temporary, output_path)
        finally:
            temporary.unlink(missing_ok=True)
    report = audit_figure_references(output_path, classification)
    report["figure_captions_renumbered"] = sum(c["current_number"] != c["output_number"] for c in before["captions"])
    report["figure_references_renumbered"] = sum(v["code"] == "FIGURE_REFERENCE_MISMATCH" for v in before["violations"])
    output_path.with_suffix(".figure_reference_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
