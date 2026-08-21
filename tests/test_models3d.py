import json

from astro_datalake.build import models_3d as build_models
from astro_datalake.models3d import sbn
from astro_datalake.models3d.fetchers import asset_links
from astro_datalake.sources.registry import SOURCES

DATASETS_JS = """
app.factory('Datasets', function() {
    return {
        'Hudson_radar': {
            name: 'Radar Shape Models (Hudson)',
            link: 'https://sbn.psi.edu/pds/resource/rshape.html',
            basepath: 'https://sbnarchive.psi.edu/pds3/radar/data/'
        }
    }
});
"""

DATA_JS = """
app.factory('Comets', function () {
        return [{
                name: '9P/Tempel 1',
                type: 'comet',
                datasets: [{
                    name: 'Tempel 1 Shape Model',
                    link: 'https://example.invalid/dataset.html',
                    files: {
                        data: {
                            primary: {downloadLink: 'https://example.invalid/tempel1.wrl', fileFormat: 'WRL'},
                            derived: [{downloadLink: 'shape-models/files/tempel1.obj', fileFormat: 'OBJ'}]
                        },
                        previews: {
                            default: {path: 'shape-models/previews/tempel1.png', fileFormat: 'PNG'},
                            ios: null
                        }
                    }
                }]
            }
        ]
    })
    .factory('Asteroids', function (Datasets) {
        const Hudson = Datasets['Hudson_radar'];

        return [{
                name: '216 Kleopatra',
                type: 'asteroid',
                datasets: [{
                    name: Hudson.name,
                    link: Hudson.link,
                    files: {
                        data: {
                            primary: {downloadLink: Hudson.basepath + '216kleopatra.tab', fileFormat: 'TAB'},
                            derived: null
                        },
                        previews: {
                            default: null,
                            ios: {path: 'Hudson.basepath' + '216kleopatra.tab.usdz', fileformat: 'USDZ'}
                        }
                    }
                }]
            }
        ]
    });
"""


def test_parse_catalog_resolves_dataset_consts():
    objects = sbn.parse_catalog(DATA_JS, DATASETS_JS)
    by_name = {o["name"]: o for o in objects}
    assert set(by_name) == {"9P/Tempel 1", "216 Kleopatra"}
    assert by_name["216 Kleopatra"]["type"] == "asteroid"
    primary = by_name["216 Kleopatra"]["datasets"][0]["files"]["data"]["primary"]
    assert primary["downloadLink"] == "https://sbnarchive.psi.edu/pds3/radar/data/216kleopatra.tab"


def test_catalog_file_urls_roles_and_base():
    objects = {o["name"]: o for o in sbn.parse_catalog(DATA_JS, DATASETS_JS)}
    files = sbn.catalog_file_urls(objects["9P/Tempel 1"], "https://sbn.psi.edu/pds/")
    by_role = {f["role"]: f for f in files}
    assert by_role["primary"]["url"] == "https://example.invalid/tempel1.wrl"
    # relative links resolve against /pds/, not against the page's own directory
    assert by_role["derived"]["url"] == "https://sbn.psi.edu/pds/shape-models/files/tempel1.obj"
    assert by_role["preview_default"]["format"] == "PNG"


def test_catalog_file_urls_flags_upstream_typo():
    objects = {o["name"]: o for o in sbn.parse_catalog(DATA_JS, DATASETS_JS)}
    files = sbn.catalog_file_urls(objects["216 Kleopatra"], "https://sbn.psi.edu/pds/")
    broken = [f for f in files if f.get("broken_upstream")]
    assert len(broken) == 1
    assert broken[0]["url"] is None


def test_dataset_dir_hints_and_fallback_urls():
    """A dead link is retried in the folder its dataset siblings actually use."""
    data_js = DATA_JS.replace(
        "{downloadLink: Hudson.basepath + '216kleopatra.tab', fileFormat: 'TAB'}",
        "{downloadLink: 'shape-models/files/RADAR/216kleopatra.tab', fileFormat: 'TAB'}",
    )
    objects = sbn.parse_catalog(data_js, DATASETS_JS)
    hints = sbn.dataset_dir_hints(objects)
    assert hints["Radar Shape Models (Hudson)"] == ["RADAR"]

    kleopatra = next(o for o in objects if o["name"] == "216 Kleopatra")
    files = sbn.catalog_file_urls(kleopatra, "https://sbn.psi.edu/pds/", hints)
    ios = next(f for f in files if f["role"] == "preview_ios")
    # the upstream typo leaves no usable url, but the filename still points somewhere
    assert ios["url"] is None
    assert ios["fallback_urls"][0] == (
        "https://sbn.psi.edu/pds/shape-models/files/RADAR/216kleopatra.tab.usdz"
    )


def test_fallback_urls_without_hints_uses_written_parent_then_bare_name():
    urls = sbn.fallback_urls("https://sbn.psi.edu/pds/RADAR/1998ky26.tab.usdz")
    assert urls == [
        "https://sbn.psi.edu/pds/shape-models/files/RADAR/1998ky26.tab.usdz",
        "https://sbn.psi.edu/pds/shape-models/files/1998ky26.tab.usdz",
    ]


def test_asset_links_filters_by_extension_and_resolves_relative():
    html = """
    <a href="/dam/hubble/Main%20body.stl?emrc=1">body</a>
    <a href="notes.pdf">pdf</a>
    <img src="preview.png">
    """
    links = asset_links(html, "https://science.nasa.gov/3d-resources/hubble/", {".stl", ".pdf"})
    assert "https://science.nasa.gov/dam/hubble/Main%20body.stl?emrc=1" in links
    assert "https://science.nasa.gov/3d-resources/hubble/notes.pdf" in links
    assert not any(link.endswith(".png") for link in links)


def test_normalize_name_strips_variant_suffixes():
    assert build_models.normalize_name("Hubble Space Telescope (A)") == ("Hubble Space Telescope", "A")
    assert build_models.normalize_name("Cassiopeia A Supernova (B) (2023)")[0] == "Cassiopeia A Supernova"
    assert build_models.normalize_name("Rosetta") == ("Rosetta", None)


def test_object_key_merges_across_sources():
    # NASA calls it "Asteroid 433 Eros", PDS SBN calls it "433 Eros"
    assert build_models.object_key("Asteroid 433 Eros", "asteroids") == build_models.object_key("433 Eros", "asteroids")
    assert build_models.object_key("67P/Churyumov–Gerasimenko", "comets") == "67p_churyumov_gerasimenko"


def test_classify_categories():
    cases = {
        "James Webb Space Telescope": "spacecraft",
        "Hubble Space Telescope (A)": "spacecraft",
        "Double Asteroid Redirection Test (DART)": "spacecraft",
        "Laser Interferometer Space Antenna (LISA)": "spacecraft",
        "Asteroid 433 Eros": "asteroids",
        "67P/Churyumov–Gerasimenko": "comets",
        "Crab Nebula": "deep_sky",
        "Tycho Star Map": "sky_maps",
        "Moon - Tycho": "surface_features",
        "Vesta - Rheasilvia": "surface_features",
        "Jupiter - Io (A)": "moons",
        "Earth (A)": "planets",
        "Earth Observing-1 (EO-1)": "spacecraft",
        "Hurricane Katrina": "earth_science",
        "Deep Space Network 70-meter": "ground_and_equipment",
        "BP Tauri": "stars",
    }
    for name, expected in cases.items():
        assert build_models.classify(name)[0] == expected, name


def test_file_role():
    from pathlib import Path

    assert build_models.file_role(Path("a.glb")) == "mesh"
    assert build_models.file_role(Path("a.tif")) == "texture"
    assert build_models.file_role(Path("a.7z")) == "archive"
    assert build_models.file_role(Path("a.pdf")) == "doc"


def test_build_writes_leaf_with_metadata(tmp_path):
    raw = tmp_path / "raw"
    repo = raw / "nasa_3d_resources" / "2026-08-21" / "NASA-3D-Resources"
    model_dir = repo / "3D Models" / "Hubble Space Telescope (A)"
    model_dir.mkdir(parents=True)
    (model_dir / "Hubble Space Telescope (A).glb").write_bytes(b"glTF-fake")
    (model_dir / "Hubble Space Telescope (A).png").write_bytes(b"png-fake")

    out = tmp_path / "models_3d"
    report = build_models.build(raw, out)

    leaf = out / "spacecraft" / "hubble_space_telescope"
    payload = json.loads((leaf / "model_3d.json").read_text())
    assert report.object_count == 1
    assert payload["display_name"] == "Hubble Space Telescope"
    assert payload["has_mesh"] and payload["has_texture"]
    assert {f["variant"] for f in payload["files"]} == {"A"}
    assert payload["sources"][0]["key"] == "nasa_3d_resources"

    # house convention: metadata.json + README carrying the shared attribution block
    from astro_datalake.build.common import ATTRIBUTION_BEGIN

    metadata = json.loads((leaf / "metadata.json").read_text())
    assert metadata["source"] == "nasa_3d_resources"
    assert metadata["license"]
    assert metadata["classification_method"] == "fallback:spacecraft"
    assert ATTRIBUTION_BEGIN in (leaf / "README.md").read_text()
    assert json.loads((out / "index.json").read_text())["counts"] == {"spacecraft": 1}


def test_every_models_3d_source_has_a_plan_entry():
    from astro_datalake.models3d import STREAM_PLAN

    keys = {k for k, spec in SOURCES.items() if spec.category.startswith("models_3d")}
    assert keys <= set(STREAM_PLAN)
    # a source with no fetcher must say why in its registry notes
    for key in keys:
        if STREAM_PLAN[key] is None:
            assert SOURCES[key].notes.strip()


def test_extract_bundle_unpacks_and_is_idempotent(tmp_path):
    py7zr = __import__("py7zr")
    archive = tmp_path / "Model (A).7z"
    texture = tmp_path / "diffuse.jpg"
    texture.write_bytes(b"jpeg-fake")
    with py7zr.SevenZipFile(archive, "w") as bundle:
        bundle.write(texture, "textures/diffuse.jpg")

    target = tmp_path / "out"
    first = build_models.extract_bundle(archive, target)
    assert [p.name for p in first] == ["diffuse.jpg"]
    assert (target / "textures" / "diffuse.jpg").read_bytes() == b"jpeg-fake"

    # second call must not re-extract (marker records the archive checksum)
    marker = target / ".extracted_from.json"
    stamp = marker.stat().st_mtime_ns
    second = build_models.extract_bundle(archive, target)
    assert [p.name for p in second] == ["diffuse.jpg"]
    assert marker.stat().st_mtime_ns == stamp


def test_build_extracts_bundled_textures(tmp_path):
    py7zr = __import__("py7zr")
    raw = tmp_path / "raw"
    model_dir = raw / "nasa_3d_resources" / "2026-08-21" / "NASA-3D-Resources" / "3D Models" / "Rosetta"
    model_dir.mkdir(parents=True)
    (model_dir / "Rosetta.glb").write_bytes(b"glTF-fake")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "body.tif").write_bytes(b"tiff-fake")
    with py7zr.SevenZipFile(model_dir / "Rosetta.7z", "w") as bundle:
        bundle.write(scratch / "body.tif", "body.tif")

    out = tmp_path / "models_3d"
    build_models.build(raw, out)

    payload = json.loads((out / "spacecraft" / "rosetta" / "model_3d.json").read_text())
    bundled = [f for f in payload["files"] if f.get("from_archive")]
    assert [f["file"] for f in bundled] == ["Rosetta_extracted/body.tif"]
    assert bundled[0]["role"] == "texture"
    assert (out / "spacecraft" / "rosetta" / "Rosetta_extracted" / "body.tif").exists()


def test_build_drops_objects_without_files(tmp_path):
    raw = tmp_path / "raw"
    item_dir = raw / "nasa_science_3d" / "2026-08-21" / "items" / "europa_clipper"
    item_dir.mkdir(parents=True)
    (item_dir / "item.json").write_text(json.dumps({
        "title": "Europa Clipper &#8211; scale model", "permalink": "https://science.nasa.gov/x/",
        "excerpt": "<p>A <b>paper</b> model.</p>",
    }))
    (item_dir / "page.html").write_text("<html></html>")

    out = tmp_path / "models_3d"
    report = build_models.build(raw, out)

    assert report.object_count == 0
    assert not any(out.rglob("model_3d.json"))


def test_master_index_ignores_schema_files(tmp_path):
    from astro_datalake.build import catalog

    (tmp_path / "models_3d" / "spacecraft" / "rosetta").mkdir(parents=True)
    (tmp_path / "models_3d" / "spacecraft" / "rosetta" / "model_3d.json").write_text("{}")
    (tmp_path / "_catalog" / "schema").mkdir(parents=True)
    (tmp_path / "_catalog" / "schema" / "model_3d.json").write_text("{}")

    index = catalog.build_master_index(tmp_path)
    assert index["model_3d"] == ["models_3d/spacecraft/rosetta"]


def test_build_prunes_stale_leaves(tmp_path):
    raw = tmp_path / "raw"
    model_dir = raw / "nasa_3d_resources" / "2026-08-21" / "NASA-3D-Resources" / "3D Models" / "Rosetta"
    model_dir.mkdir(parents=True)
    (model_dir / "Rosetta.glb").write_bytes(b"glTF-fake")

    out = tmp_path / "models_3d"
    stale = out / "spacecraft" / "rosetta_8211_old_slug"
    stale.mkdir(parents=True)
    (stale / "model_3d.json").write_text("{}")

    build_models.build(raw, out)

    assert not stale.exists()
    assert (out / "spacecraft" / "rosetta" / "model_3d.json").exists()
