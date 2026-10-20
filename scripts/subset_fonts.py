"""Subset the two UI typefaces to Latin + Indian rupee + marks, as WOFF (bundled so the app works offline).

Carlito (OFL, metric-compatible with Calibri) and TeX Gyre Schola (GUST Font License, a Century Schoolbook revival).
"""
from pathlib import Path

from fontTools import subset

SRC = {
    "carlito-regular": "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf",
    "carlito-bold": "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf",
    "carlito-italic": "/usr/share/fonts/truetype/crosextra/Carlito-Italic.ttf",
    "schola-regular": "/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyreschola-regular.otf",
    "schola-bold": "/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyreschola-bold.otf",
    "schola-italic": "/usr/share/texmf/fonts/opentype/public/tex-gyre/texgyreschola-italic.otf",
}
UNICODES = "U+0020-007E,U+00A0-00FF,U+2010-2027,U+2030-203A,U+20B9,U+2190-2193,U+2212,U+2713,U+2717,U+00D7,U+2026,U+2022"
OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "fonts"
OUT.mkdir(parents=True, exist_ok=True)
for name, path in SRC.items():
    opts = subset.Options()
    opts.flavor = "woff"
    opts.layout_features = ["kern", "liga", "lnum", "tnum", "onum", "case"]
    opts.name_IDs = ["*"]
    font = subset.load_font(path, opts)
    s = subset.Subsetter(opts)
    s.populate(unicodes=subset.parse_unicodes(UNICODES))
    s.subset(font)
    target = OUT / f"{name}.woff"
    subset.save_font(font, str(target), opts)
    print(name, target.stat().st_size // 1024, "KB")
