/* Renders manifest.json as a browsable download index. All data comes from the
   static manifest, so the Worker is not called just to draw this page. */

const $ = (id) => document.getElementById(id);
const state = { manifest: null };

const human = (bytes) => {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i += 1; }
  return `${value.toFixed(value < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
};

const el = (tag, props = {}, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  for (const child of children.flat()) {
    if (child != null) node.append(child);
  }
  return node;
};

/* ---------- rendering ---------- */

function renderStats(manifest) {
  const { counts } = manifest;
  const totalBytes = manifest.sources.reduce((sum, s) => sum + (s.approx_bytes || 0), 0);
  const stats = [
    [counts.sources, "sources"],
    [counts.targets, "download links"],
    [counts.fetchable_sources, "fetchable now"],
    [counts.by_tier.tier1 || 0, "tier 1"],
    [counts.by_tier.tier2 || 0, "tier 2"],
    [counts.by_tier.tier3 || 0, "tier 3"],
    [human(totalBytes) || "—", "known volume"],
  ];
  $("stats").replaceChildren(
    ...stats.map(([value, label]) =>
      el("div", { className: "stat" },
        el("b", { textContent: String(value) }),
        el("span", { textContent: label })),
    ),
  );
  $("generated").textContent =
    `Manifest generated ${manifest.generated_at} · manifest version ${manifest.manifest_version}`;
}

function targetRow(target) {
  const cell = el("td", { className: "link" },
    target.browser_fetchable
      ? el("a", { href: target.url, textContent: target.url, rel: "noreferrer" })
      : el("span", { textContent: target.url }));
  if (!target.browser_fetchable) {
    // A POST body or an auth header cannot be expressed as a clickable link,
    // so show the command that does work instead of a link that would 401/400.
    cell.append(el("div", { className: "curl", textContent: target.curl }));
  }
  return el("tr", {},
    el("td", { className: "file", textContent: target.filename }),
    el("td", { textContent: target.method }),
    el("td", { textContent: human(target.approx_bytes) || "—" }),
    cell);
}

function sourceCard(source) {
  const tags = [
    el("span", { className: `tag t${source.tier}`, textContent: `tier ${source.tier}` }),
    el("span", { className: `tag ${source.status}`, textContent: source.status }),
  ];
  if (source.approx_bytes) {
    tags.push(el("span", { className: "tag", textContent: human(source.approx_bytes) }));
  }

  const summary = el("summary", {},
    el("span", { className: "name", textContent: source.name }),
    el("span", { className: "key", textContent: source.key }),
    el("span", { className: "spacer" }),
    ...tags);

  const body = el("div", { className: "body" });
  if (source.unfetchable_reason) {
    body.append(el("p", { className: "notes",
      textContent: `Not fetchable: ${source.unfetchable_reason}` }));
  }
  if (source.targets.length) {
    body.append(el("table", {},
      el("thead", {}, el("tr", {},
        el("th", { textContent: "File" }),
        el("th", { textContent: "Method" }),
        el("th", { textContent: "Size" }),
        el("th", { textContent: "Link" }))),
      el("tbody", {}, ...source.targets.map(targetRow))));
  }

  const meta = [];
  if (source.license) meta.push(`License: ${source.license}`);
  if (source.credential_env) meta.push(`Credentials: ${source.credential_env.join(", ")}`);
  if (meta.length) body.append(el("p", { className: "notes", textContent: meta.join(" · ") }));
  if (source.landing_page) {
    body.append(el("p", { className: "notes" },
      el("a", { href: source.landing_page, textContent: "Source homepage", rel: "noreferrer" })));
  }
  if (source.notes) body.append(el("p", { className: "notes", textContent: source.notes }));

  return el("details", { className: "source" }, summary, body);
}

function applyFilters() {
  const query = $("q").value.trim().toLowerCase();
  const tier = $("tier").value;
  const status = $("status").value;

  const matches = state.manifest.sources.filter((source) => {
    if (tier && String(source.tier) !== tier) return false;
    if (status && source.status !== status) return false;
    if (!query) return true;
    return source.key.toLowerCase().includes(query)
      || source.name.toLowerCase().includes(query)
      || source.category.toLowerCase().includes(query);
  });

  const container = $("sources");
  if (!matches.length) {
    container.replaceChildren(
      el("p", { className: "notes", textContent: "No source matches that filter." }));
    return;
  }

  const groups = new Map();
  for (const source of matches) {
    const top = source.category.split("/")[0];
    if (!groups.has(top)) groups.set(top, []);
    groups.get(top).push(source);
  }

  const blocks = [];
  for (const [group, sources] of groups) {
    blocks.push(el("h2", { textContent: `${group} (${sources.length})` }));
    blocks.push(...sources.map(sourceCard));
  }
  container.replaceChildren(...blocks);
}

/* ---------- boot ---------- */

async function main() {
  try {
    const response = await fetch("/manifest.json");
    state.manifest = await response.json();
  } catch (error) {
    $("sources").replaceChildren(
      el("p", { className: "notes", textContent: `Could not load manifest.json: ${error.message}` }));
    return;
  }

  renderStats(state.manifest);
  applyFilters();

  $("q").addEventListener("input", applyFilters);
  $("tier").addEventListener("change", applyFilters);
  $("status").addEventListener("change", applyFilters);
  $("expand").addEventListener("click", () => {
    const cards = document.querySelectorAll("details.source");
    const shouldOpen = ![...cards].every((card) => card.open);
    cards.forEach((card) => { card.open = shouldOpen; });
    $("expand").textContent = shouldOpen ? "Collapse all" : "Expand all";
  });
}

main();
