# Offline platform fonts

The platform uses two SIL Open Font License 1.1 families. Fonts are served from
the application's own `/fonts/` path; there are no runtime CDN/font-service
requests, user uploads, or user-specific font downloads.

## RD Sans — derived from Source Han Sans CN VF 2.005

- Original publisher: Adobe; original family: **Source Han Sans CN VF / 思源黑体**.
- Pinned upstream commit: `a4f7cf94edfb9d7ffbdfc4841de276358bd7e0f2`.
- Source: https://github.com/adobe-fonts/source-han-sans/tree/release/Variable/WOFF2/TTF/Subset
- Upstream source SHA-256: `f971e3bff46f76b49e1d5510556c2297c618ec4b491a295a4e741cdd38257799`.
- Original and derivative license: [SourceHanSans-OFL.txt](SourceHanSans-OFL.txt).
- Derivative: application-local Unicode shards, internal family and PostScript
  names changed to **RD Sans / RDSans** to respect the reserved name `Source`.
  The original copyright and license records remain in each font.
- Weights: original variable `wght` axis, **250–900**; style: normal.
- Coverage: every one of the upstream CN font's **30,926 mapped Unicode code
  points** remains available. This does not assert that the CN source covers
  every character in Unicode; unsupported characters use the CSS fallback.

The UI shard is a loading priority, **not** a character whitelist. It holds
Latin/symbols, Chinese punctuation, and frequent UI characters. All remaining
source characters are partitioned into non-overlapping 1,024-code-point shards.
CSS `unicode-range` downloads only the relevant local shards. A new product
name or uploaded document can therefore load another shard without rebuilding.
`font-display: swap` keeps text visible during loading.

## RD Mono — IBM Plex Mono

- Original publisher: IBM; original family **IBM Plex Mono**.
- Pinned upstream commit: `71f558992315a12ca1f06a2215d57962a1992162`.
- Source: https://github.com/IBM/plex/tree/master/packages/plex-mono/fonts/complete/woff2
- Original license: [IBMPlex-OFL.txt](IBMPlex-OFL.txt).
- `IBMPlexMono-Regular.woff2` (400) and `IBMPlexMono-Medium.woff2` (500) are
  **unmodified upstream files**. `RD Mono` is only the CSS family alias, not a
  renamed or modified IBM font. The reserved font name `Plex` is retained in the
  unmodified files.

The machine-readable [manifest.json](manifest.json) records URLs, SHA-256,
length, and Unicode coverage of every source and distributed font file.

## Rebuild

Run from the service root, in an isolated build environment (not the application's
Python environment):

```powershell
python -m venv runtime/font-build-venv
runtime/font-build-venv/Scripts/python.exe -m pip install "fonttools[woff]==4.62.1" "brotli==1.2.0"
runtime/font-build-venv/Scripts/python.exe web/scripts/build-fonts.py --workers 3
```

The builder downloads only pinned upstream files into ignored
`runtime/font-sources/`, validates their hashes, retains license texts, writes
the WOFF2 shards, and generates `web/src/fonts.css` plus `manifest.json`. Its
coverage check fails if any mapped source code point is lost. Sources already
present in the cache are still hash checked. Changing an upstream source
requires an explicit version/hash update in the builder.

The default rebuild regenerates every shard. `--resume-pinned-build` is an
explicit recovery option for an interrupted build of these exact pinned source
files; it verifies each existing shard's code points, RD Sans internal family,
and weight axis before reuse. Do not use that option after updating the source
version, name/subsetting rules, or source hashes.

Vite copies `web/public/fonts/` into `web/dist/fonts/` during the normal build;
fonttools is not a production or browser dependency. `PlatformTheme.tsx` imports
`web/src/fonts.css` once so the live application and isolated UI fixtures share
the same font definitions. Use `RD Sans` / `RD Mono` in PlatformTheme; do not add
a second import in `main.tsx`. The application HTML preloads the UI shard using
`as="font"`, `type="font/woff2"`, and `crossorigin`.
