"""Serialize Word property elements in their schema-defined sequence.

Presentation renderers edit lxml elements directly and may append font sizes,
borders or alignment after later properties. Modern Word tolerates many such
sequences, but they are invalid WordprocessingML. At the final package write,
normalize known property order and invalid zero font sizes/character scaling,
and encode newer style flags using Word 2007-compatible bitmasks. Source content,
style references and unrelated extensions are preserved.

The sequences follow the Open XML SDK WordprocessingML schema metadata:
https://github.com/dotnet/Open-XML-SDK/blob/main/data/schemas/
schemas_openxmlformats_org_wordprocessingml_2006_main.json
"""

from __future__ import annotations

import re

from lxml import etree

from .ooxml_style_repair import normalize_template_styles
from .ooxml_word2007 import normalize_word2007_layout

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{W}}}"

# These named attributes were added in Office 2010 in the existing w:
# namespace. mc:Ignorable for w14 cannot make them readable by Word 2007.
# Equivalent legacy values: ECMA-376 Part 4 (2016), 14.4.12 and 14.8.2.4.
# Copied sources may omit w:val or disagree with its older cached value.
_LEGACY_HEX_FLAGS = {
    _W + "tblLook": {
        "firstRow": 0x0020, "lastRow": 0x0040,
        "firstColumn": 0x0080, "lastColumn": 0x0100,
        "noHBand": 0x0200, "noVBand": 0x0400,
    },
    _W + "stylePaneFormatFilter": {
        "allStyles": 0x0001, "customStyles": 0x0002,
        "latentStyles": 0x0004, "stylesInUse": 0x0008,
        "headingStyles": 0x0020, "numberingStyles": 0x0040,
        "tableStyles": 0x0080, "directFormattingOnRuns": 0x0100,
        "directFormattingOnParagraphs": 0x0200,
        "directFormattingOnNumbering": 0x0400,
        "directFormattingOnTables": 0x0800, "clearFormatting": 0x1000,
        "top3HeadingStyles": 0x2000, "visibleStyles": 0x4000,
        "alternateStyleNames": 0x8000,
    },
}
_ON_OFF_VALUES = {"1": True, "true": True, "on": True,
                  "0": False, "false": False, "off": False}


def _normalize_legacy_style_flags(root: etree._Element) -> int:
    """Fold understood named flags into w:val without touching unknown values.

    Explicit flags override the corresponding legacy bits. Unspecified bits and
    foreign attributes survive; invalid values remain available for diagnosis
    rather than being replaced with guessed formatting. This is a targeted
    encoding fix, not a general converter for every newer Office feature.
    """
    changed = 0
    for tag, flags in _LEGACY_HEX_FLAGS.items():
        for element in root.iter(tag):
            supplied = {name: element.get(_W + name)
                        for name in flags if _W + name in element.attrib}
            if not supplied:
                continue
            legacy = element.get(_W + "val", "0000")
            if (not re.fullmatch(r"[0-9a-fA-F]{4}", legacy)
                    or any(value not in _ON_OFF_VALUES for value in supplied.values())):
                continue
            mask = int(legacy, 16)
            for name, value in supplied.items():
                bit = flags[name]
                mask = mask | bit if _ON_OFF_VALUES[value] else mask & ~bit
            element.set(_W + "val", f"{mask:04X}")
            for name in supplied:
                del element.attrib[_W + name]
            changed += 1
    return changed


_PROPERTY_SEQUENCES = {
    "rPr": (
        "ins del moveFrom moveTo rStyle rFonts b bCs i iCs caps smallCaps strike "
        "dstrike outline shadow emboss imprint noProof snapToGrid vanish "
        "webHidden color spacing w kern position sz szCs highlight u effect "
        "bdr shd fitText vertAlign rtl cs em lang eastAsianLayout specVanish "
        "oMath rPrChange"
    ),
    "pPr": (
        "pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr "
        "suppressLineNumbers pBdr shd tabs suppressAutoHyphens kinsoku wordWrap "
        "overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd "
        "snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap "
        "jc textDirection textAlignment textboxTightWrap outlineLvl divId "
        "cnfStyle rPr sectPr pPrChange"
    ),
    "tblPr": (
        "tblStyle tblpPr tblOverlap bidiVisual tblW jc tblCellSpacing tblInd "
        "tblBorders shd tblLayout tblCellMar tblLook tblCaption tblDescription "
        "tblPrChange"
    ),
    "trPr": (
        "cnfStyle divId gridBefore gridAfter wBefore wAfter trHeight hidden "
        "cantSplit tblHeader tblCellSpacing jc ins del trPrChange"
    ),
    "tcPr": (
        "cnfStyle tcW gridSpan hMerge vMerge tcBorders shd noWrap tcMar "
        "textDirection tcFitText vAlign hideMark cellIns cellDel cellMerge "
        "tcPrChange"
    ),
    "pBdr": "top left bottom right between bar",
    "tblBorders": "top left start bottom right end insideH insideV",
    "tcBorders": "top left start bottom right end insideH insideV tl2br tr2bl",
    "tblCellMar": "top left start bottom right end",
    "tcMar": "top left start bottom right end",
    "lvl": (
        "start numFmt lvlRestart pStyle isLgl suff lvlText lvlPicBulletId "
        "legacy lvlJc pPr rPr"
    ),
}
_PROPERTY_ORDER = {
    _W + parent: {_W + child: index for index, child in enumerate(sequence.split())}
    for parent, sequence in _PROPERTY_SEQUENCES.items()
}


def normalize_property_order(root: etree._Element) -> int:
    """Order known property siblings in place, returning changed containers.

    Unknown extensions and XML comments retain their positions. Stable sorting
    retains the order of repeated property children and does not discard or
    combine them; this function does not invent a policy for conflicting values.
    """
    changed = 0
    # Reordering a parent changes the traversal links used by lxml iterators.
    # Snapshot them so nested tcBorders/rPr nodes cannot be skipped.
    for parent in list(root.iter()):
        order = _PROPERTY_ORDER.get(parent.tag)
        if order is None:
            continue
        children = list(parent)
        slots = [index for index, child in enumerate(children) if child.tag in order]
        current = [children[index] for index in slots]
        ordered = sorted(current, key=lambda child: order[child.tag])
        if current == ordered:
            continue
        for index, child in zip(slots, ordered):
            children[index] = child
        parent[:] = children
        changed += 1
    return changed


def normalize_properties(root: etree._Element, *, styles_root=None) -> dict[str, int]:
    """Correct invalid zero run formatting and order the resulting properties.

    A zero character scale is invalid and collapses text: use normal 100%
    width. A zero font size uses the same run's valid size for the other script,
    or inherits from its style if neither script specifies a usable size.
    Only literal zero values are changed; no text or nonzero values are removed.
    """
    stats = {
        "ooxml_property_sequences_normalized": 0,
        "ooxml_zero_character_scales_normalized": 0,
        "ooxml_zero_font_sizes_normalized": 0,
        "ooxml_word2007_flag_sets_normalized": _normalize_legacy_style_flags(root),
    }
    stats.update(normalize_template_styles(root))
    stats.update(normalize_word2007_layout(root, styles_root))
    for properties in list(root.iter(_W + "rPr")):
        for scale in properties.findall(_W + "w"):
            if scale.get(_W + "val") == "0":
                scale.set(_W + "val", "100")
                stats["ooxml_zero_character_scales_normalized"] += 1

        usable_sizes = {}
        for tag in ("sz", "szCs"):
            node = properties.find(_W + tag)
            value = node.get(_W + "val", "") if node is not None else ""
            if value.isdigit() and 2 <= int(value) <= 1638:
                usable_sizes[tag] = value
        for tag, other_tag in (("sz", "szCs"), ("szCs", "sz")):
            for size in properties.findall(_W + tag):
                if size.get(_W + "val") != "0":
                    continue
                if other_tag in usable_sizes:
                    size.set(_W + "val", usable_sizes[other_tag])
                else:
                    properties.remove(size)
                stats["ooxml_zero_font_sizes_normalized"] += 1

    stats["ooxml_property_sequences_normalized"] = normalize_property_order(root)
    return stats


def normalize_properties_xml(data: bytes, *, styles_root=None) -> tuple[bytes, dict[str, int]]:
    """Normalize one XML part without reserializing an unchanged part."""
    root = etree.fromstring(data)
    stats = normalize_properties(root, styles_root=styles_root)
    if not any(stats.values()):
        return data, stats
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True,
    ), stats
