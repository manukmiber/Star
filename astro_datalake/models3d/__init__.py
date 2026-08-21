"""Fase 8: 3D models (mesh) + textures.

Unlike every other source in this project, these are binary asset trees —
meshes, textures, printable STL sets — not tables. They are pulled with the
stream fetchers in `fetchers.py` (which write straight to disk and checksum
as they go, instead of buffering whole responses in memory like
`downloaders.DOWNLOAD_PLAN`), and organized into `data/models_3d/` by
`astro_datalake.build.models_3d`.
"""

from .plan import STREAM_PLAN

__all__ = ["STREAM_PLAN"]
