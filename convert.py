#!/usr/bin/env python3
"""
Editing Naples -> IIIF Presentation 3 + W3C Web Annotation (proof of concept on one map).

Reads the annotations from the maps.biblhertz.it interface (the same GET request used by
the /map?name=... page) and writes them as two annotation layers:
  - annotations-legend.json     layer 1: the map and its legend (name, number, legend text,
                                category); one annotation per polygon
  - annotations-gazetteer.json  layer 2: gazetteer links (historical guidebooks, other maps) for
                                the annotations listed in gazetteer.json, on the same polygon
  - manifest.json               IIIF v3 manifest, one canvas, both annotation pages
  - manifest-legend.json        the same manifest with layer 1 only

Typical use (from the script folder):
  python3 convert.py --static --base https://USER.github.io/REPO/   # static hosting (GitHub Pages)
  python3 convert.py --proxy --out DIR                              # local test through serve.py

Useful options:
  --input data.json        use an already saved JSON instead of downloading it
  --width/--height         image size, if neither info.json nor the Manifester answer
"""
import argparse
import copy
import html
import json
import os
import sys
import urllib.parse
import urllib.request

MAPS = "https://maps.biblhertz.it"
IIIF_IMAGE_BASE = "https://img.biblhertz.it/digilib/Scaler/IIIF/3/"

# Colours by groupname, copied from the CSS rules `div.dl-digilib .map-<group> { fill: ... }`
# of the /map?name=lafreri page (2026-11-16): 84 groups, valid for all maps of the site.
# The site applies `fill-opacity: 0.3` and `stroke: none`; on hover a 2px yellow outline
# (in Mirador: `hovered` palette in index.html).
GROUP_COLORS = {
    "acquedotto": "aqua", "altare": "blue", "antico": "sienna", "armario": "slategray",
    "arredo": "slategray", "banco": "darkcyan", "battistero": "magenta", "biblioteca": "darkorange",
    "canale": "aqua", "cappella": "crimson", "casa": "blue", "casale": "darkcyan",
    "castello": "navy", "cattedra": "blue", "chiesa": "red", "chiostro": "coral",
    "cimitero": "slategray", "collegio": "purple", "colonna": "lightblue", "congregazione": "firebrick",
    "conservatorio": "indigo", "contesto_urbano": "yellow", "convento": "firebrick", "coro": "lightblue",
    "cortile": "white", "cripta": "darkorange", "dogana": "steelblue", "economia": "darkcyan",
    "edificio_profano": "blue", "edificio_religioso": "red", "educandato": "indigo",
    "elemento_architettonico": "lightblue", "facciata": "lightblue", "fiume": "aqua", "fontana": "aqua",
    "fornace": "darkcyan", "galleria": "yellow", "generale": "gray", "giardino": "green",
    "insula": "white", "iscrizione": "blue", "largo": "gold", "località": "white",
    "loggia": "indigo", "masseria": "darkcyan", "militare": "lightblue", "monastero": "firebrick",
    "monumento": "slategray", "natura": "darkgreen", "navata": "lightblue", "nicchia": "lightblue",
    "obelisco": "slategray", "oratorio": "mediumvioletred", "organo": "blue", "ospedale": "indigo",
    "ospizio": "indigo", "palazzo": "navy", "pavimento": "lightblue", "piazza": "gold",
    "pilastro": "lightblue", "ponte": "gold", "porta": "lightblue", "pubblico": "steelblue",
    "pulpito": "blue", "quadro": "blue", "quartiere": "white", "rampa": "gold",
    "sacrestia": "darkorange", "salita": "gold", "scultura": "blue", "scuola": "steelblue",
    "seggio": "steelblue", "seminario": "purple", "sepolcro": "slategray", "soffitto": "lightblue",
    "stanza": "lightblue", "strada": "gold", "teatro": "steelblue", "torre": "lightblue",
    "via": "gold", "vico": "gold", "vicolo": "gold", "vigna": "green", "villa": "blue",
}
FILL_OPACITY = 0.3
# Group without a rule: the site uses `.dl-svg-annotationregion { fill: rgba(255, 255, 10, 0.3) }`,
# which with fill-opacity 0.3 gives an effective opacity of 0.09
DEFAULT_COLOR = "#FFFF0A"
DEFAULT_OPACITY = 0.09


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "editing-naples-iiif-test"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def image_service_id(fn, base=IIIF_IMAGE_BASE):
    # "napoli/duperac-lzw-tiled.tif" -> ".../IIIF/3/napoli%21duperac-lzw-tiled"
    ident = fn.rsplit(".", 1)[0].replace("/", "%21")
    return base + ident


def image_size(fn, service):
    """Size from info.json; if it is empty (Digilib, Nov. 2026) from the Manifester."""
    try:
        ij = get_json(service + "/info.json")
        print(f"Size from info.json: {ij['width']} x {ij['height']}")
        return ij["width"], ij["height"]
    except Exception as ex:
        print(f"info.json not usable ({ex}); trying the Manifester")
    ident = service.rsplit("/", 1)[-1]
    manifest = get_json(f"{MAPS}/digilib/Manifester/IIIF/3/{fn.rsplit('/', 1)[0]}")
    for canvas in manifest["items"]:
        for page in canvas["items"]:
            for anno in page["items"]:
                for s in anno["body"].get("service", []):
                    if s["id"].rsplit("/", 1)[-1] == ident:
                        print(f"Size from the Manifester: {canvas['width']} x {canvas['height']}")
                        return canvas["width"], canvas["height"]
    raise LookupError(f"{ident} is not in the Manifester")


def static_info(service_id, w, h):
    """IIIF Image 3 info.json replacing the empty one from Digilib (see also serve.py)."""
    factors = [1]
    while max(w, h) / factors[-1] > 256:
        factors.append(factors[-1] * 2)
    return {
        "@context": "http://iiif.io/api/image/3/context.json",
        "id": service_id, "type": "ImageService3",
        "protocol": "http://iiif.io/api/image", "profile": "level2",
        "width": w, "height": h,
        "tiles": [{"width": 256, "scaleFactors": factors}],
    }


def svg_path(coords, w, h, group, filled=True):
    # Mirador 3 draws only the <path> elements of the SvgSelector, not <polygon>.
    # Mirador always strokes the outline (black if `stroke` is missing; `stroke='none'` is not
    # accepted): `transparent` hides it as on the site; on hover and on selection Mirador
    # recolours it with the theme palette, `stroke-width` wide.
    # `filled=False` (layer 2): same polygon without fill, otherwise the colour of layer 1
    # would be painted twice.
    if filled:
        color = GROUP_COLORS.get(group)
        fill = (f"fill='{color or DEFAULT_COLOR}' "
                f"fill-opacity='{FILL_OPACITY if color else DEFAULT_OPACITY}'")
    else:
        fill = "fill='none'"
    pts = " L ".join(f"{x * w:.1f} {y * h:.1f}" for x, y in coords)
    return ("<svg xmlns='http://www.w3.org/2000/svg'>"
            f"<path d='M {pts} Z' {fill} stroke='transparent' stroke-width='2'/></svg>")


def xywh(bbox, w, h):
    x, y = bbox["xmin"] * w, bbox["ymin"] * h
    return f"xywh={x:.0f},{y:.0f},{(bbox['xmax'] - bbox['xmin']) * w:.0f},{(bbox['ymax'] - bbox['ymin']) * h:.0f}"


def gazetteer_html(g):
    # Only tags allowed by the Mirador 3 filter (a, b, br, i, img, p, span): no <ul>/<li>
    e = html.escape
    parts = [f"<p><b>Gazetteer:</b> <a href='{e(g['uri'])}'>{e(g['title'])}</a> [{e(g['top_id'])}]</p>"]
    facts = []
    for label, key in (("Location", "location"), ("Category", "category"), ("Dates", "dates"), ("Notes", "notes")):
        if g.get(key):
            facts.append(f"{label}: {e(g[key])}")
    if facts:
        parts.append("<p>" + "<br/>".join(facts) + "</p>")
    if g.get("guides"):
        items = "<br/>".join(
            f"<a href='{e(x['url'])}'>{e(x['ref'])}</a>: «{e(x['quote'])}»" for x in g["guides"]
        )
        parts.append(f"<p><b>Historical guidebooks</b><br/>{items}</p>")
    if g.get("maps"):
        items = "<br/>".join(
            f"<a href='{e(x['url'])}'>{e(x['map'])}</a>"
            + (f": «{e(x['legend'])}»" if x.get("legend") else "")
            for x in g["maps"]
        )
        parts.append(f"<p><b>Other historical maps</b><br/>{items}</p>")
    return "".join(parts)


def target(row, w, h, canvas_id, filled=True):
    return {
        "type": "SpecificResource",
        "source": canvas_id,
        "selector": [
            {"type": "FragmentSelector", "conformsTo": "http://www.w3.org/TR/media-frags/",
             "value": xywh(row["bbox"], w, h)},
            {"type": "SvgSelector", "value": svg_path(
                row["shape"], w, h, row.get("groupname"), filled)},
        ],
    }


def tags(row):
    """Category and tags, without trailing punctuation (the source has `chiesa,`) or duplicates."""
    out = []
    for tag in [row.get("groupname")] + (row.get("tags") or []):
        tag = (tag or "").strip().rstrip(",;.:").strip()
        if tag and tag not in out:
            out.append(tag)
    return out


def legend_annotation(row, w, h, base, canvas_id):
    """Layer 1: only the map and its legend, no gazetteer data."""
    title = row.get("name") or row.get("line") or row.get("label") or ""
    text = f"<p><b>{html.escape(title)}</b>"
    if row.get("nr"):
        text += f" [no. {html.escape(row['nr'])}]"
    text += "</p>"
    if row.get("legend"):
        text += f"<p>Map legend: «{html.escape(row['legend'])}»</p>"

    body = [{"type": "TextualBody", "value": text, "format": "text/html", "purpose": "describing"}]
    body += [{"type": "TextualBody", "value": tag, "purpose": "tagging"} for tag in tags(row)]

    return {
        "id": f"{base}anno/{row['id']}",
        "type": "Annotation",
        "motivation": "commenting",
        "created": row.get("created", "").replace(" ", "T") or None,
        "creator": {"type": "Person", "name": row["user"]} if row.get("user") else None,
        "body": body,
        "target": target(row, w, h, canvas_id),
    }


def gazetteer_annotation(row, g, w, h, base, canvas_id):
    """Layer 2: the same polygon linked to the gazetteer entry (guidebooks, other maps)."""
    return {
        "id": f"{base}anno/{row['id']}/gazetteer",
        "type": "Annotation",
        "motivation": "linking",
        "body": [
            {"type": "TextualBody", "value": gazetteer_html(g), "format": "text/html",
             "purpose": "describing"},
            # machine-readable link to the gazetteer entry
            {"type": "SpecificResource", "source": g["uri"], "purpose": "identifying"},
        ],
        "target": target(row, w, h, canvas_id, filled=False),
    }


def clean(obj):
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items() if v not in (None, "")}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="lafreri", help="short name of the map (e.g. lafreri)")
    ap.add_argument("--fn", default="napoli/duperac-lzw-tiled.tif", help="image file in Digilib")
    ap.add_argument("--input", help="already saved JSON of the search call")
    ap.add_argument("--gazetteer", default="gazetteer.json")
    ap.add_argument("--base", default="http://localhost:8000/", help="address the files will be served from")
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--proxy", action="store_true",
                      help="route the images through serve.py (works around the CORS block)")
    mode.add_argument("--static", action="store_true",
                      help="for static hosting (GitHub Pages): writes iiif/<map>/info.json next to "
                           "the manifest; the tiles come directly from Digilib")
    ap.add_argument("--out", default=".", help="folder the files are written to")
    a = ap.parse_args()
    if not a.base.endswith("/"):
        a.base += "/"

    if a.input:
        with open(a.input, encoding="utf-8") as f:
            data = json.load(f)
    else:
        url = f"{MAPS}/map/search?" + urllib.parse.urlencode({"fn": a.fn, "za": "1x1@0,0"})
        print("Downloading", url)
        data = get_json(url)

    info = data["mapinfo"]
    fn = info.get("fn") or a.fn
    service = image_service_id(fn)          # to read the image size

    w, h = a.width, a.height
    if not (w and h):
        try:
            w, h = image_size(fn, service)
        except Exception as ex:
            sys.exit(f"Image size not available ({ex}). Run again with --width and --height.")

    digilib_service = service
    if a.proxy:
        service = image_service_id(fn, f"{a.base}iiif/")
    elif a.static:
        # Digilib's info.json is empty: we publish our own, whose id points to Digilib,
        # so the viewer requests the tiles (plain images, no CORS) directly from Digilib
        service = f"{a.base}iiif/{a.map}"
    canvas_id = f"{a.base}canvas/1"
    gaz = {}
    try:
        with open(a.gazetteer, encoding="utf-8") as f:
            gaz = json.load(f)
    except FileNotFoundError:
        pass

    rows = [r for r in data["rows"] if r.get("state", 1) == 1 and r.get("shape")]
    layers = [
        ("annotations-legend.json", "Map legend",
         [legend_annotation(r, w, h, a.base, canvas_id) for r in rows]),
        ("annotations-gazetteer.json", "Gazetteer: other maps and guidebooks",
         [gazetteer_annotation(r, gaz[str(r["id"])], w, h, a.base, canvas_id)
          for r in rows if str(r["id"]) in gaz]),
    ]
    pages = {
        name: {
            "@context": "http://iiif.io/api/presentation/3/context.json",
            "id": a.base + name,
            "type": "AnnotationPage",
            "label": {"en": [label]},
            "items": items,
        }
        for name, label, items in layers
    }
    page_refs = [{"id": p["id"], "type": "AnnotationPage", "label": p["label"]}
                 for p in pages.values()]

    meta = [
        ("Title", info.get("name")), ("Author", info.get("creator")),
        ("Engraver", info.get("engraver")), ("Publisher", info.get("editor")),
        ("Date", info.get("date")), ("Technique", info.get("tec")),
        ("Type", info.get("type")),
        ("Dimensions (mm)", f"{info['h']} x {info['w']}" if info.get("h") and info.get("w") else None),
        ("Location", ", ".join(x for x in (info.get("o_place"), info.get("o_name"), info.get("inv")) if x)),
        ("Annotations by", info.get("markup")),
        ("DOI", f"https://doi.org/{info['doi']}" if info.get("doi") else None),
    ]
    manifest = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": f"{a.base}manifest.json",
        "type": "Manifest",
        "label": {"en": [f"{info.get('line', '')} {info.get('date', '')}".strip()]},
        "metadata": [{"label": {"en": [k]}, "value": {"none": [v]}} for k, v in meta if v],
        "requiredStatement": {"label": {"en": ["Source"]},
                              "value": {"en": ["Bibliotheca Hertziana, Editing Naples"]}},
        "homepage": [{"id": f"{MAPS}/map?name={a.map}", "type": "Text", "format": "text/html",
                      "label": {"en": ["Editing Naples application"]}}],
        "items": [{
            "id": canvas_id, "type": "Canvas", "width": w, "height": h,
            "label": {"none": [fn]},
            "items": [{
                "id": f"{a.base}page/1", "type": "AnnotationPage",
                "items": [{
                    "id": f"{a.base}page/1/image", "type": "Annotation", "motivation": "painting",
                    "target": canvas_id,
                    "body": {"id": f"{digilib_service if a.static else service}/full/max/0/default.jpg",
                             "type": "Image",
                             "format": "image/jpeg", "width": w, "height": h,
                             "service": [{"id": service, "type": "ImageService3", "profile": "level2"}]},
                }],
            }],
            # Gazetteer first: Mirador lists the pages in this order and, between two identical
            # polygons, a click on the map selects the annotation of the first page
            "annotations": page_refs[::-1],
        }],
    }
    if info.get("doi"):
        manifest["seeAlso"] = [{"id": f"https://doi.org/{info['doi']}", "type": "Dataset",
                                "label": {"none": ["DOI"]}}]

    # Mirador 3.4.3 cannot switch a single AnnotationPage on and off (the overlay draws all the
    # pages of the canvas): showing layer 1 alone needs a second manifest
    legend = copy.deepcopy(manifest)
    legend["id"] = f"{a.base}manifest-legend.json"
    legend["label"] = {"en": [manifest["label"]["en"][0] + " (legend only)"]}
    legend["items"][0]["annotations"] = page_refs[:1]

    os.makedirs(a.out, exist_ok=True)
    for name, obj in {"manifest.json": manifest, "manifest-legend.json": legend, **pages}.items():
        with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
            json.dump(clean(obj), f, ensure_ascii=False, indent=2)
    if a.static:
        info_dir = os.path.join(a.out, "iiif", a.map)
        os.makedirs(info_dir, exist_ok=True)
        with open(os.path.join(info_dir, "info.json"), "w", encoding="utf-8") as f:
            json.dump(static_info(digilib_service, w, h), f, indent=2)
        print(f"Static info.json in {info_dir}; tiles from {digilib_service}")

    linked = [r["id"] for r in rows if str(r["id"]) in gaz]
    no_top = sum(1 for r in rows if not r.get("ref_top"))
    print(f"Layer 1 (legend): {len(rows)} annotations; layer 2 (gazetteer): {linked}")
    print(f"Rows without ref_top (link to the gazetteer) in the database: {no_top}/{len(rows)}")


if __name__ == "__main__":
    main()
