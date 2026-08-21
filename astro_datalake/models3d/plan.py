"""Which stream fetcher serves which registry key.

Mirrors `downloaders.DOWNLOAD_PLAN`, but for binary asset trees. A key mapped
to None is registered-but-not-pulled on purpose; the reason lives in that
source's `notes` in sources/registry.py.
"""

from __future__ import annotations

from .fetchers import (
    StreamFetcher,
    archive_file,
    git_repo,
    nasa_science_3d,
    page_textures,
    sbn_shape_models,
    svs_pages,
)

# A single texture file above this is skipped and logged rather than pulled:
# SVS ships 100k x 50k Moon maps (tens of GB) next to the 4k/8k ones that are
# actually usable as a texture map.
MAX_TEXTURE_BYTES = 600 * 1024 * 1024
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024 * 1024

STREAM_PLAN: dict[str, StreamFetcher | None] = {
    "nasa_3d_resources": git_repo(
        "nasa_3d_resources", "https://github.com/nasa/NASA-3D-Resources.git"
    ),
    "nasa_science_3d": nasa_science_3d(),
    "pds_sbn_shape_models": sbn_shape_models(),
    "damit_shape_models": archive_file(
        "damit_shape_models",
        "https://damit.cuni.cz/projects/damit/exports/complete/latest",
        "damit-complete-export.tar.gz",
        max_bytes=MAX_ARCHIVE_BYTES,
    ),
    "nasa_svs_texture_kits": svs_pages(
        "nasa_svs_texture_kits",
        [4720],  # CGI Moon Kit — LROC color + LOLA displacement maps
        max_bytes=MAX_TEXTURE_BYTES,
    ),
    # The Blue Marble collection page is only an index; the image files live on the
    # feature pages it links to, served from assets.science.nasa.gov (the old
    # eoimages.gsfc.nasa.gov paths are no longer linked). Pages listed explicitly so
    # the crawl can't wander into unrelated Earth Observatory articles.
    "nasa_blue_marble_textures": page_textures(
        "nasa_blue_marble_textures",
        {
            "blue_marble_next_generation":
                "https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/",
            "blue_marble_1km_true_color":
                "https://science.nasa.gov/earth/earth-observatory/"
                "the-blue-marble-true-color-global-imagery-at-1km-resolution/",
            "the_blue_marble":
                "https://science.nasa.gov/earth/earth-observatory/the-blue-marble-2181/",
            "twin_blue_marbles":
                "https://science.nasa.gov/earth/earth-observatory/twin-blue-marbles-8108/",
            "history_of_the_blue_marble":
                "https://science.nasa.gov/earth/earth-observatory/history-of-the-blue-marble/",
        },
        max_bytes=MAX_TEXTURE_BYTES,
        host_filter="assets.science.nasa.gov",
        path_filter="bluemarble",
    ),
    "usgs_planetary_mosaics": None,  # Tier 3, see registry notes
    "solarsystemscope_textures": None,  # captcha-gated, see registry notes
}
