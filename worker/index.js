/**
 * Astro Data Lake — API Worker.
 *
 * Design rule: this Worker never moves a dataset through itself. Catalogue
 * files here run from 70 KB to 200 MB, and a tier-wide pull is >100 requests
 * against a dozen rate-limited upstreams. Streaming that through a Worker
 * would burn CPU time and wall clock for no benefit, so the Worker only ever:
 *
 *   - serves the pre-generated manifest (a static asset read, no computation),
 *   - answers small derived queries over it (filter/lookup on ~110 entries),
 *   - 302-redirects download requests straight to the upstream host.
 *
 * The redirect is the important part: the bytes go source -> client and never
 * source -> Worker -> client, so a 200 MB MPCORB download costs this Worker a
 * single header write.
 */

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "access-control-allow-origin": "*",
  "cache-control": "public, max-age=300",
};

/** Manifest is immutable per deploy, so one fetch per isolate is plenty. */
let manifestCache = null;

async function loadManifest(env) {
  if (manifestCache) return manifestCache;
  const response = await env.ASSETS.fetch(new URL("/manifest.json", "https://assets.local"));
  if (!response.ok) {
    throw new Error(`manifest.json unavailable (${response.status})`);
  }
  manifestCache = await response.json();
  return manifestCache;
}

function json(body, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { ...JSON_HEADERS, ...extraHeaders },
  });
}

function findSource(manifest, key) {
  return manifest.sources.find((source) => source.key === key) || null;
}

/** Compact source view: everything the index page needs, none of the bulk. */
function summarize(source) {
  return {
    key: source.key,
    name: source.name,
    tier: source.tier,
    category: source.category,
    status: source.status,
    fetchable: source.fetchable,
    license: source.license,
    landing_page: source.landing_page,
    target_count: source.target_count,
    approx_bytes: source.approx_bytes ?? null,
    unfetchable_reason: source.unfetchable_reason ?? null,
  };
}

const ROUTES = {
  "/api/health": async (_request, env) => {
    const manifest = await loadManifest(env);
    return json({
      ok: true,
      service: "astro-datalake-worker",
      role: "catalogue + redirects only; dataset bytes never pass through this Worker",
      manifest_generated_at: manifest.generated_at,
      counts: manifest.counts,
    });
  },

  "/api/manifest": async (_request, env) => json(await loadManifest(env)),

  "/api/sources": async (request, env) => {
    const manifest = await loadManifest(env);
    const params = new URL(request.url).searchParams;
    const tier = params.get("tier");
    const category = params.get("category");
    const status = params.get("status");
    const query = (params.get("q") || "").toLowerCase();

    let sources = manifest.sources;
    if (tier) sources = sources.filter((s) => String(s.tier) === tier);
    if (category) sources = sources.filter((s) => s.category.startsWith(category));
    if (status) sources = sources.filter((s) => s.status === status);
    if (query) {
      sources = sources.filter(
        (s) =>
          s.key.toLowerCase().includes(query) ||
          s.name.toLowerCase().includes(query),
      );
    }
    return json({ count: sources.length, sources: sources.map(summarize) });
  },
};

/** /api/sources/<key> — one source with all its targets. */
async function sourceDetail(env, key) {
  const manifest = await loadManifest(env);
  const source = findSource(manifest, key);
  if (!source) return json({ error: `unknown source: ${key}` }, 404);
  return json(source);
}

/**
 * /api/download/<key>[/<filename>] — 302 to the upstream URL.
 *
 * With one target (or an explicit filename) this redirects. With several and
 * no filename it lists them instead of guessing, since "download openngc"
 * means two different files.
 */
async function download(env, key, filename) {
  const manifest = await loadManifest(env);
  const source = findSource(manifest, key);
  if (!source) return json({ error: `unknown source: ${key}` }, 404);

  if (!source.fetchable) {
    return json(
      {
        error: `${key} is not fetchable`,
        reason: source.unfetchable_reason,
        replaced_by: source.replaced_by ?? null,
        landing_page: source.landing_page,
      },
      409,
    );
  }

  const targets = source.targets;
  const target = filename
    ? targets.find((t) => t.filename === filename)
    : targets.length === 1
      ? targets[0]
      : null;

  if (filename && !target) {
    return json(
      { error: `unknown file ${filename} for ${key}`, available: targets.map((t) => t.filename) },
      404,
    );
  }
  if (!target) {
    return json({
      key,
      message: "multiple files — pick one with /api/download/<key>/<filename>",
      files: targets.map((t) => ({
        filename: t.filename,
        url: t.url,
        method: t.method,
        browser_fetchable: t.browser_fetchable,
      })),
    });
  }
  if (!target.browser_fetchable) {
    // POST bodies and auth headers cannot survive a redirect. Hand back the
    // recipe instead of pretending a GET would work.
    return json(
      {
        key,
        filename: target.filename,
        message:
          "this target needs a POST body or an auth header — a redirect cannot carry either",
        method: target.method,
        url: target.url,
        form_data: target.form_data ?? null,
        required_headers: target.required_headers ?? null,
        curl: target.curl,
      },
      409,
    );
  }

  return Response.redirect(target.url, 302);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET, OPTIONS",
          "access-control-allow-headers": "content-type",
        },
      });
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return json({ error: "method not allowed" }, 405);
    }

    try {
      const route = ROUTES[path];
      if (route) return await route(request, env);

      if (path.startsWith("/api/sources/")) {
        return await sourceDetail(env, decodeURIComponent(path.slice("/api/sources/".length)));
      }
      if (path.startsWith("/api/download/")) {
        const rest = path.slice("/api/download/".length).split("/");
        const key = decodeURIComponent(rest.shift() || "");
        const filename = rest.length ? decodeURIComponent(rest.join("/")) : null;
        return await download(env, key, filename);
      }
      if (path.startsWith("/api/")) {
        return json({ error: "not found", path, routes: Object.keys(ROUTES) }, 404);
      }

      // Non-/api paths only reach the Worker if no asset matched.
      return env.ASSETS.fetch(request);
    } catch (error) {
      return json({ error: String(error && error.message ? error.message : error) }, 500);
    }
  },
};
