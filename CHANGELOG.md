# Changelog

Format: newest entry first. Every dead/changed endpoint discovered during
probing (Fase 1) or later gets logged here with the date, what was tried,
and what replaced it (if anything).

## 2026-08-20 — Fase 0: Scaffold

- Initial project scaffold: CLI (`astro pull|build|verify|status`), config,
  rate-limited/retrying HTTP client, checksum-based raw cache, folder-naming
  helpers, and the master source registry (`astro_datalake/sources/registry.py`)
  covering all sources listed in the task brief (sections A–H).
- No network calls made yet. Endpoint liveness has **not** been verified —
  that's Fase 1, next.
- Tier assignments in the registry are a best-effort mapping of the brief's
  Tier 1/2/3 lists onto concrete endpoints; a few sources not explicitly
  named in those lists (USGS Gazetteer, IAU star names, Gaia DR3 NSS,
  OpenNGC/Messier) carry a `notes` field explaining the assumption made and
  are flagged for reconsideration in the Fase 5 report.
