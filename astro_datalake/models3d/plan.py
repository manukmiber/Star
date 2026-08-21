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
    usgs_mosaics,
)

# A single texture file above this is skipped and logged rather than pulled.
# Raised from 600 MB once the disk budget allowed it: at 600 MB the Moon kit lost
# its float EXR colour map (943 MB), the 16k sRGB TIFF (909 MB) and the 64 px/deg
# elevation map (1013 MB), which are the versions worth having. Still below the
# full-resolution 2.4 GB TIFF, which is the same 16k map at higher bit depth.
MAX_TEXTURE_BYTES = 1100 * 1024 * 1024

# USGS ships global mosaics up to hundreds of GB. Cap one file, and cap the lot,
# so "every body we lack a texture for" does not turn into "the whole Astropedia".
MAX_USGS_FILE_BYTES = 900 * 1024 * 1024
USGS_TOTAL_BUDGET = 4 * 1024 * 1024 * 1024
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
    # Bodies with no texture anywhere else in this data lake come first (Mercury,
    # Uranus, the outer moons); Mars/Venus/Moon are here for a global map at a
    # resolution the NASA repo's textures do not reach.
    "usgs_planetary_mosaics": usgs_mosaics(
        "usgs_planetary_mosaics",
        queries=["global mosaic", "global map", "basemap"],
        max_bytes=MAX_USGS_FILE_BYTES,
        total_budget=USGS_TOTAL_BUDGET,
        want=[
            "mercury", "venus", "mars", "moon", "lunar", "vesta", "ceres",
            "io_", "europa", "ganymede", "callisto", "titan", "enceladus",
            "dione", "rhea", "tethys", "iapetus", "mimas", "triton", "pluto",
            "charon", "ariel", "umbriel", "titania", "oberon", "miranda",
            "phobos", "deimos",
        ],
    ),
    "solarsystemscope_textures": None,  # captcha-gated, see registry notes
}
