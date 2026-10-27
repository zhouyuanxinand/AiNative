"""Serialize Word property elements in their schema-defined sequence.

Presentation renderers edit lxml elements directly and may append font sizes,
borders or alignment after later properties. Modern Word tolerates many such
sequences, but they are invalid WordprocessingML. At the final package write,
normalize known property order and invalid zero font sizes/character scaling.
Other values, source content, style references and extensions are preserved.

The sequences follow the Open XML SDK WordprocessingML schema metadata:
https://github.com/dotnet/Open-XML-SDK/blob/main/data/schemas/
schemas_openxmlformats_org_wordprocessingml_2006_main.json
"""

from __future__ import annotations

from lxml import etree


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{W}}}"

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


def normalize_properties(root: etree._Element) -> dict[str, int]:
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
    }
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


def normalize_properties_xml(data: bytes) -> tuple[bytes, dict[str, int]]:
    """Normalize one XML part without reserializing an unchanged part."""
    root = etree.fromstring(data)
    stats = normalize_properties(root)
    if not any(stats.values()):
        return data, stats
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True,
    ), stats
