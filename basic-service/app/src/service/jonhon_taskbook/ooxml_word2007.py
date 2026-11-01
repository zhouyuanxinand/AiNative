"""Encode understood logical layout properties using Word 2007 vocabulary.

Logical alignment and edges were added in later Word versions in the existing
w namespace, so mc:Ignorable cannot hide them from Word 2007. Resolve paragraph
and table direction before rewriting; unresolved inheritance is left intact.
"""
from __future__ import annotations

from lxml import etree

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_TRUE = {"1", "true", "on"}
_FALSE = {"0", "false", "off"}
_EDGE_PARENTS = {_W + name for name in ("tblBorders", "tcBorders", "tblCellMar", "tcMar")}


def _boolean(node):
    if node is None:
        return False
    value = node.get(_W + "val")
    if value is None or value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return None


def _ancestor(node, tag):
    while node is not None:
        if node.tag == _W + tag:
            return node
        node = node.getparent()
    return None


class _Directions:
    def __init__(self, root, styles_root):
        self.styles = root if root.tag == _W + "styles" else styles_root
        self.by_id = {}
        self.defaults = {}
        if self.styles is not None:
            for style in self.styles.findall(_W + "style"):
                identity = style.get(_W + "styleId")
                self.by_id[identity] = style if identity not in self.by_id else None
                if style.get(_W + "default") in _TRUE:
                    kind = style.get(_W + "type")
                    self.defaults[kind] = identity if kind not in self.defaults else None

    def default_property(self, group, name):
        if self.styles is None or group != "pPr":
            return None, True, None
        properties = self.styles.find(_W + "docDefaults/" + _W + "pPrDefault/" + _W + "pPr")
        node = properties.find(_W + name) if properties is not None else None
        return node, True, properties

    def style_property(self, identity, group, name):
        seen = set()
        while identity:
            if identity in seen or self.by_id.get(identity) is None:
                return None, False, None
            seen.add(identity)
            style = self.by_id[identity]
            properties = style.find(_W + group)
            node = properties.find(_W + name) if properties is not None else None
            if node is not None:
                return node, True, properties
            based_on = style.find(_W + "basedOn")
            if based_on is not None and not based_on.get(_W + "val"):
                return None, False, None
            identity = based_on.get(_W + "val") if based_on is not None else None
        return self.default_property(group, name)

    def property(self, properties, group, name):
        if properties is not None:
            direct = properties.find(_W + name)
            if direct is not None:
                return direct, True, properties
            parent = properties.getparent()
            if parent is not None and parent.tag == _W + "pPrDefault":
                return None, True, None
            if parent is not None and parent.tag == _W + "style":
                based_on = parent.find(_W + "basedOn")
                if based_on is not None and not based_on.get(_W + "val"):
                    return None, False, None
                identity = based_on.get(_W + "val") if based_on is not None else None
                return self.style_property(identity, group, name)
            owner_style = _ancestor(parent, "style")
            if owner_style is not None:
                return self.style_property(owner_style.get(_W + "styleId"), group, name)
            reference = properties.find(_W + ("pStyle" if group == "pPr" else "tblStyle"))
            if reference is not None:
                if not reference.get(_W + "val"):
                    return None, False, None
                return self.style_property(reference.get(_W + "val"), group, name)
        kind = "paragraph" if group == "pPr" else "table"
        if kind in self.defaults:
            identity = self.defaults[kind]
            if identity is None:
                return None, False, None
            return self.style_property(identity, group, name)
        return self.default_property(group, name)

    def paragraph(self, properties):
        node, known, _ = self.property(properties, "pPr", "bidi")
        return _boolean(node) if known else None

    def table(self, node):
        properties = _ancestor(node, "tblPr")
        if properties is None:
            style = _ancestor(node, "style")
            if style is not None:
                properties = style.find(_W + "tblPr")
                flag, known, _ = self.style_property(style.get(_W + "styleId"), "tblPr", "bidiVisual")
                return _boolean(flag) if known else None
            table = _ancestor(node, "tbl")
            if table is not None:
                properties = table.find(_W + "tblPr")
            else:
                # A detached cell fragment cannot establish table direction.
                return None
        flag, known, _ = self.property(properties, "tblPr", "bidiVisual")
        return _boolean(flag) if known else None


def _physical(logical, rtl):
    return "right" if (logical == "end") != rtl else "left"


def normalize_word2007_layout(root, styles_root=None) -> dict[str, int]:
    """Convert proven logical layout while retaining content and extensions.

    ``styles_root`` is the original styles tree for non-style parts. Resolve it
    before normalizing styles.xml so inherited logical alignment remains known.
    Numbering levels use their paragraph properties/styles/docDefaults; a single
    level dynamically shared by opposite-direction paragraphs is not expanded.
    Logical indents inherited across a paragraph-direction reversal are also
    outside this bounded conversion; it does not materialize full indent cascades.
    """
    directions = _Directions(root, styles_root)
    stats = {"ooxml_word2007_alignments_normalized": 0,
             "ooxml_word2007_indents_normalized": 0,
             "ooxml_word2007_edges_normalized": 0,
             "ooxml_word2007_alignments_materialized": 0}
    alignment_changes = []
    # Snapshot inheritance before changing any source style's logical value.
    for properties in list(root.iter(_W + "pPr")):
        rtl = directions.paragraph(properties)
        if rtl is None:
            continue
        alignment, known, origin = directions.property(properties, "pPr", "jc")
        if not known or alignment is None or alignment.get(_W + "val") not in {"start", "end"}:
            continue
        logical = alignment.get(_W + "val")
        value = _physical(logical, rtl)
        if origin is properties:
            alignment_changes.append((alignment, value, False, properties))
        else:
            origin_direction = directions.paragraph(origin)
            if origin_direction is not None and value != _physical(logical, origin_direction):
                alignment_changes.append((alignment, value, True, properties))
    for alignment, value, materialize, properties in alignment_changes:
        if materialize:
            alignment = etree.SubElement(properties, _W + "jc")
            stats["ooxml_word2007_alignments_materialized"] += 1
        else:
            stats["ooxml_word2007_alignments_normalized"] += 1
        alignment.set(_W + "val", value)

    for alignment in root.iter(_W + "lvlJc"):
        value = alignment.get(_W + "val")
        if value not in {"start", "end"}:
            continue
        level = _ancestor(alignment, "lvl")
        if level is None:
            continue
        rtl = directions.paragraph(level.find(_W + "pPr"))
        if rtl is not None:
            alignment.set(_W + "val", _physical(value, rtl))
            stats["ooxml_word2007_alignments_normalized"] += 1

    for indent in root.iter(_W + "ind"):
        properties = indent.getparent()
        if properties is None or properties.tag != _W + "pPr":
            continue
        rtl = directions.paragraph(properties)
        if rtl is None:
            continue
        for logical, suffix in (("start", ""), ("end", ""), ("start", "Chars"), ("end", "Chars")):
            key = _W + logical + suffix
            if key in indent.attrib:
                indent.set(_W + _physical(logical, rtl) + suffix, indent.attrib.pop(key))
                stats["ooxml_word2007_indents_normalized"] += 1

    for container in list(root.iter()):
        if container.tag not in _EDGE_PARENTS:
            continue
        rtl = directions.table(container)
        if rtl is None:
            continue
        for logical in ("start", "end"):
            elements = container.findall(_W + logical)
            if len(elements) != 1:
                continue
            element = elements[0]
            target = _W + _physical(logical, rtl)
            for previous in list(container.findall(target)):
                container.remove(previous)
            element.tag = target
            stats["ooxml_word2007_edges_normalized"] += 1
    return stats
