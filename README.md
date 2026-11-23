# editing-naples-iiif

Proof of concept: the Du Pérac/Lafréry map of Naples (1566) from
[Editing Naples](https://maps.biblhertz.it/map?name=lafreri) (Bibliotheca Hertziana), published as a
IIIF Presentation 3 manifest with its annotations converted to the W3C Web Annotation Data Model
and shown in Mirador 3.

Live demo: https://biblhertz.github.io/editing-naples-iiif/

## Annotation layers

The annotations are split into two AnnotationPages that target the same polygons.

| Layer | File | Content |
| --- | --- | --- |
| 1. Legend | `annotations-legend.json` | The map and its own legend only: name, legend number, legend text, category tags. One annotation per polygon (74). Motivation `commenting`. |
| 2. Gazetteer | `annotations-gazetteer.json` | How the same place appears in other historical maps and guidebooks, taken from the Editing Naples gazetteer. Motivation `linking`, with a `SpecificResource` body (`purpose: identifying`) pointing to the gazetteer entry. Currently S. Chiara only. |

## Viewer options

| URL parameter | Effect |
| --- | --- |
| `?layer=legend` (default) | Legend layer only (`manifest-legend.json`). |
| `?layer=gazetteer` | Gazetteer layer only (`manifest-gazetteer.json`). |
| `?annotations=0` | Polygons are drawn on hover only, not all at once. |

The two buttons above the viewer switch between the layers, one at a time. Selecting an annotation,
on the map or in the list, zooms to it.

## Files

Published site (GitHub Pages serves the repository root):

- `index.html`: Mirador 3.4.3 (loaded from unpkg) and the layer switch.
- `manifest-legend.json`, `manifest-gazetteer.json`: IIIF manifests, one canvas, with a single
  annotation page each. These are the ones the viewer loads.
- `manifest.json`: the same manifest with both annotation pages, for other IIIF viewers.
- `annotations-legend.json`, `annotations-gazetteer.json`: the annotation pages.
- `iiif/lafreri/info.json`: static IIIF Image API 3 `info.json` for the map image.

The manifests work in any IIIF Presentation 3 viewer.

Conversion:

- `convert.py`: downloads the annotations from Editing Naples and writes the manifests, the
  annotation pages and `info.json`. Python 3, standard library only.
- `gazetteer.json`: gazetteer data for layer 2, keyed by annotation id.
- `sample.json`: three rows of the source data, for offline tests with `--input`.
- `serve.py`: optional local proxy that adds CORS headers to the image server (`convert.py --proxy`).

## Regenerating the files

The JSON files are generated: change `convert.py` or `gazetteer.json`, not the output.

```sh
# published build, written to the repository root
python3 convert.py --static --base https://biblhertz.github.io/editing-naples-iiif/

# local test build in a separate folder
python3 convert.py --static --base http://localhost:8000/ --out /tmp/lafreri
cp index.html /tmp/lafreri/
python3 -m http.server 8000 -d /tmp/lafreri
```

The identifiers in the generated files contain the base URL, so do not commit a local build.

## Annotation format

- Target: the canvas, with an `SvgSelector` (`<path>` in canvas pixels) and a `FragmentSelector`
  (`xywh` bounding box) as fallback.
- Text: `TextualBody` in `text/html`; categories as `TextualBody` with `purpose: tagging`.
- Polygon colours follow the category colours of the Editing Naples site.
- Place names, legend texts and category tags are in Italian, as in the source data.

## Data sources

- Annotations and map metadata: the Editing Naples web application, `https://maps.biblhertz.it`.
- Image: the Bibliotheca Hertziana Digilib server (IIIF Image API 3),
  `https://img.biblhertz.it/digilib/Scaler/IIIF/3/napoli%21duperac-lzw-tiled`.
- Gazetteer: `https://maps.biblhertz.it/top/18` (S. Chiara), transcribed by hand.

## Known limitations

- Mirador 3.4.3 cannot switch individual annotation pages on and off, hence one manifest per layer.
- The link between an annotation and its gazetteer entry is not available in the source data for
  this map, so the gazetteer layer was built by hand for a single place.
- Digilib currently returns an empty `info.json` for this image, so a static copy is served from
  this repository. Image tiles still come from Digilib.
- On hover the Editing Naples site removes the polygon fill, Mirador keeps it.
