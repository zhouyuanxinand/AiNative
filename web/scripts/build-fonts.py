"""Build the offline OFL font distribution. Run with fonttools[woff]==4.62.1.

Source downloads are pinned and hash checked. UI characters are only a loading
priority: all other characters from the original CN font remain in other shards.
No request or business document data is used or sent anywhere.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from urllib.request import Request, urlopen

from fontTools import subset
from fontTools.ttLib import TTFont

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parent
FONT_DIR = WEB / "public" / "fonts"
ADOBE_REV = "a4f7cf94edfb9d7ffbdfc4841de276358bd7e0f2"
IBM_REV = "71f558992315a12ca1f06a2215d57962a1992162"
SOURCES = {
    "SourceHanSansCN-VF.ttf.woff2": (
        f"https://raw.githubusercontent.com/adobe-fonts/source-han-sans/{ADOBE_REV}/Variable/WOFF2/TTF/Subset/SourceHanSansCN-VF.ttf.woff2",
        "f971e3bff46f76b49e1d5510556c2297c618ec4b491a295a4e741cdd38257799"),
    "SourceHanSans-OFL.txt": (
        f"https://raw.githubusercontent.com/adobe-fonts/source-han-sans/{ADOBE_REV}/LICENSE.txt",
        "fcac737e761ec63dbfbdce11030a1780161920d80315edba9c8beff1c2bac5a2"),
    "IBMPlexMono-Regular.woff2": (
        f"https://raw.githubusercontent.com/IBM/plex/{IBM_REV}/packages/plex-mono/fonts/complete/woff2/IBMPlexMono-Regular.woff2",
        "ba204497f16b6d334cee9d1e963a831b73e3a56e1d6300a8489d18df7214b350"),
    "IBMPlexMono-Medium.woff2": (
        f"https://raw.githubusercontent.com/IBM/plex/{IBM_REV}/packages/plex-mono/fonts/complete/woff2/IBMPlexMono-Medium.woff2",
        "33faf307fa6031fb4062276d7320a6d632de890cbb347576fd80cfa01077bc25"),
    "IBMPlex-OFL.txt": (
        f"https://raw.githubusercontent.com/IBM/plex/{IBM_REV}/LICENSE.txt",
        "7e6b2818edbd8f6a01ae80641cc8f16a51080d08fb4e532be3a0b6f74adb07da"),
}


def ranges(points: set[int]) -> str:
    ordered = sorted(points)
    groups: list[str] = []
    start = end = ordered[0]
    for point in ordered[1:]:
        if point == end + 1:
            end = point
        else:
            groups.append(f"U+{start:X}" if start == end else f"U+{start:X}-{end:X}")
            start = end = point
    groups.append(f"U+{start:X}" if start == end else f"U+{start:X}-{end:X}")
    return ",".join(groups)


def rename(font: TTFont) -> None:
    # The OFL reserves 'Source'; derived subsets must not use that family name.
    names = {1: "RD Sans", 2: "Regular", 3: "RD Sans 2.005 local subset",
             4: "RD Sans", 6: "RDSans-Regular", 16: "RD Sans", 17: "Regular",
             25: "RDSans"}
    table = font["name"]
    for record in table.names:
        if record.nameID in names:
            record.string = names[record.nameID].encode(record.getEncoding())
    for name_id, value in names.items():
        table.setName(value, name_id, 3, 1, 0x409)
    # Named variation instances retain their weight labels, with a new PS prefix.
    for instance in font["fvar"].instances:
        if instance.postscriptNameID != 0xFFFF:
            weight = int(instance.coordinates["wght"])
            table.setName(f"RDSans-{weight}", instance.postscriptNameID, 3, 1, 0x409)


def build_shard(payload: tuple[str, str, set[int], bool]) -> dict:
    source, key, points, resume = payload
    name = f"rd-sans-{key}.woff2"
    target = FONT_DIR / name
    valid_existing = False
    # Resume is explicit and only for an interrupted build with these pinned
    # sources. Normal rebuilds never reuse output merely because a name exists.
    if resume and target.exists():
        try:
            cached = TTFont(target, recalcTimestamp=False)
            valid_existing = (set(cached.getBestCmap()) == points
                              and cached["name"].getDebugName(1) == "RD Sans"
                              and [(axis.axisTag, axis.minValue, axis.maxValue) for axis in cached["fvar"].axes] == [("wght", 250.0, 900.0)])
            cached.close()
        except Exception:
            valid_existing = False
    if not valid_existing:
        font = TTFont(source, recalcTimestamp=False)
        options = subset.Options()
        options.name_IDs = ["*"]
        options.name_languages = ["*"]
        options.name_legacy = True
        options.layout_features = ["*"]
        options.recalc_timestamp = False
        worker = subset.Subsetter(options=options)
        worker.populate(unicodes=points)
        worker.subset(font)
        rename(font)
        font.flavor = "woff2"
        font.save(target)
        if set(font.getBestCmap()) != points:
            raise RuntimeError(f"Incomplete font shard {name}")
        font.close()
    asset = target.read_bytes()
    print(f"{'verified' if valid_existing else 'built'} {name}: {len(points)} codepoints, {len(asset)} bytes", flush=True)
    return {"file": name, "sha256": sha256(asset).hexdigest(), "bytes": len(asset), "codepoints": len(points), "unicodeRange": ranges(points)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=ROOT / "runtime" / "font-sources")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume-pinned-build", action="store_true", help="Reuse verified shards only while resuming this exact pinned source build")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    source_manifest = []
    for name, (url, expected) in SOURCES.items():
        path = args.cache / name
        if not path.exists():
            with urlopen(Request(url, headers={"User-Agent": "RD-platform-font-build"}), timeout=60) as response:
                path.write_bytes(response.read())
        raw = path.read_bytes()
        digest = sha256(raw).hexdigest()
        if not expected or digest != expected:
            raise RuntimeError(f"Unverified source {name}: {digest}")
        source_manifest.append({"file": name, "url": url, "sha256": digest, "bytes": len(raw)})
        if name.endswith("OFL.txt"):
            (FONT_DIR / name).write_bytes(raw)

    raw = (args.cache / "SourceHanSansCN-VF.ttf.woff2").read_bytes()
    original = TTFont(BytesIO(raw), recalcTimestamp=False)
    cmap = set(original.getBestCmap())
    # Decode WOFF2 once. Workers consume an ordinary TTF rather than repeatedly
    # decoding the 7.7 MB upstream WOFF2 before each independent subset.
    decoded = args.cache / "rd-source-decoded.ttf"
    original.flavor = None
    original.save(decoded)
    original.close()
    # Freeze the priority selection in the generated manifest for review/rebuild.
    # The remaining source cmap is exhaustively partitioned, not discarded.
    characters: Counter[int] = Counter()
    for path in sorted((WEB / "src").rglob("*")):
        if path.suffix in {".ts", ".tsx"}:
            characters.update(ord(char) for char in path.read_text("utf-8") if 0x3400 <= ord(char) <= 0x9FFF)
    priority = {point for point in cmap if point < 0x3000}
    priority |= {point for point, _count in characters.most_common(1000)} & cmap
    # Chinese punctuation must be ready with navigation and form labels.
    priority |= set(range(0x3000, 0x3040)) & cmap
    remaining = sorted(cmap - priority)
    partitions = [("ui", priority)] + [(f"cjk-{index // 1024:02d}", set(remaining[index:index + 1024])) for index in range(0, len(remaining), 1024)]
    css = ["/* Offline OFL fonts. Rebuild: python web/scripts/build-fonts.py. */"]
    assets = []
    union: set[int] = set()
    payloads = [(str(decoded), key, points, args.resume_pinned_build) for key, points in partitions]
    with ProcessPoolExecutor(max_workers=max(1, min(3, args.workers))) as pool:
        for (_key, points), asset in zip(partitions, pool.map(build_shard, payloads)):
            if union & points:
                raise RuntimeError(f"Overlapping font shard {asset['file']}")
            union |= points
            css.append("@font-face{font-family:'RD Sans';font-style:normal;font-weight:250 900;font-display:swap;src:url('/fonts/" + asset["file"] + "') format('woff2');unicode-range:" + asset["unicodeRange"] + ";}")
            assets.append(asset)
    if union != cmap:
        raise RuntimeError("Source cmap coverage was reduced")
    for source, weight in [("IBMPlexMono-Regular.woff2", 400), ("IBMPlexMono-Medium.woff2", 500)]:
        data = (args.cache / source).read_bytes()
        (FONT_DIR / source).write_bytes(data)
        css.append(f"@font-face{{font-family:'RD Mono';font-style:normal;font-weight:{weight};font-display:swap;src:url('/fonts/{source}') format('woff2');}}")
        assets.append({"file": source, "sha256": sha256(data).hexdigest(), "bytes": len(data), "unmodified": True})
    (WEB / "src" / "fonts.css").write_text("\n".join(css) + "\n", "utf-8")
    manifest = {"fontFamily": "RD Sans", "upstream": "Source Han Sans CN VF 2.005", "upstreamCodepoints": len(cmap), "coveredCodepoints": len(union), "fonttools": "4.62.1", "brotli": "1.2.0", "sources": source_manifest, "assets": assets}
    (FONT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"codepoints": len(union), "assets": len(assets), "bytes": sum(asset["bytes"] for asset in assets), "priorityBytes": assets[0]["bytes"]}), flush=True)


if __name__ == "__main__":
    main()
