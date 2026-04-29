#!/usr/bin/env node
const http = require("http");
const fs = require("fs");
const path = require("path");

const PROXY_URL = (() => {
  try {
    const envPath = path.join(__dirname, "..", ".env");
    const lines = fs.readFileSync(envPath, "utf8").split("\n");
    for (const line of lines) {
      const m = line.match(/^PLANET_PROXY_URL=(.*)$/);
      if (m) return m[1].trim();
    }
  } catch {}
  return process.env.PLANET_PROXY_URL || "http://10.200.0.1:9201";
})();

const parsed = new URL(PROXY_URL);
const PROXY_HOST = parsed.hostname;
const PROXY_PORT = parseInt(parsed.port || "9201", 10);

function proxyRequest(method, routePath, body) {
  return new Promise((resolve, reject) => {
    const opts = {
      hostname: PROXY_HOST,
      port: PROXY_PORT,
      path: routePath,
      method,
      headers: {},
    };
    if (body) {
      const data = JSON.stringify(body);
      opts.headers["Content-Type"] = "application/json";
      opts.headers["Content-Length"] = Buffer.byteLength(data);
    }
    const req = http.request(opts, (res) => {
      let buf = "";
      res.on("data", (d) => (buf += d));
      res.on("end", () => {
        if (res.statusCode >= 400) {
          reject(new Error(`HTTP ${res.statusCode}: ${buf.substring(0, 500)}`));
        } else {
          try { resolve(JSON.parse(buf)); }
          catch { resolve(buf); }
        }
      });
    });
    req.on("error", (e) => {
      reject(new Error(`Planet proxy (${PROXY_URL}) unreachable: ${e.message}`));
    });
    req.setTimeout(30000, () => {
      req.destroy();
      reject(new Error(`Planet proxy (${PROXY_URL}) timeout`));
    });
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

function proxyRequestBinary(method, routePath) {
  return new Promise((resolve, reject) => {
    const opts = {
      hostname: PROXY_HOST,
      port: PROXY_PORT,
      path: routePath,
      method,
    };
    const req = http.request(opts, (res) => {
      const chunks = [];
      res.on("data", (d) => chunks.push(d));
      res.on("end", () => {
        const buf = Buffer.concat(chunks);
        if (res.statusCode >= 400) {
          reject(new Error(`HTTP ${res.statusCode}: ${buf.toString("utf8").substring(0, 500)}`));
        } else {
          resolve(buf);
        }
      });
    });
    req.on("error", (e) => {
      reject(new Error(`Planet proxy (${PROXY_URL}) unreachable: ${e.message}`));
    });
    req.setTimeout(30000, () => {
      req.destroy();
      reject(new Error(`Planet proxy (${PROXY_URL}) timeout`));
    });
    req.end();
  });
}

function cleanupThumbnails() {
  try {
    const files = fs.readdirSync("/tmp").filter((f) => f.startsWith("planet-thumb-") && f.endsWith(".png"));
    for (const f of files) fs.unlinkSync(path.join("/tmp", f));
  } catch {}
}

async function thumbnail(itemType, itemId, width) {
  const w = parseInt(width || "512", 10);
  const routePath = `/tiles/data/v1/item-types/${itemType}/items/${itemId}/thumb?width=${w}`;
  const buf = await proxyRequestBinary("GET", routePath);
  cleanupThumbnails();
  const outPath = `/tmp/planet-thumb-${itemId}.png`;
  fs.writeFileSync(outPath, buf);
  return { path: outPath, size: buf.length, item_id: itemId, width: w };
}

function bboxToPolygon(bbox) {
  const [west, south, east, north] = bbox.split(",").map(Number);
  return {
    type: "Polygon",
    coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
  };
}

function parseGeometry(opts) {
  if (opts.geometry) {
    try { return JSON.parse(opts.geometry); }
    catch (e) { throw new Error("Invalid GeoJSON geometry: " + e.message); }
  }
  if (opts.bbox) return bboxToPolygon(opts.bbox);
  return null;
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

function formatItem(item) {
  const p = item.properties || {};
  return {
    id: item.id,
    type: item._permissions ? undefined : item.type,
    acquired: p.acquired,
    published: p.published,
    cloud_cover: p.cloud_cover,
    visible_percent: p.visible_percent,
    gsd: p.gsd,
    satellite_id: p.satellite_id,
    quality_category: p.quality_category,
    pixel_resolution: p.pixel_resolution,
    item_type: p.item_type,
    thumbnail: item._links?.thumbnail,
  };
}

async function itemTypes() {
  const resp = await proxyRequest("GET", "/api/data/v1/item-types");
  return (resp.item_types || []).map((t) => ({
    id: t.id,
    display_name: t.display_name,
    display_description: t.display_description,
  }));
}

async function search(opts) {
  const filters = [];

  if (opts.startDate || opts.endDate) {
    const config = {};
    if (opts.startDate) config.gte = opts.startDate;
    if (opts.endDate) config.lte = opts.endDate;
    filters.push({ type: "DateRangeFilter", field_name: "acquired", config });
  }

  if (opts.maxCloud !== undefined) {
    filters.push({
      type: "RangeFilter",
      field_name: "cloud_cover",
      config: { lte: parseFloat(opts.maxCloud) },
    });
  }

  if (opts.geometry) {
    try {
      const geo = JSON.parse(opts.geometry);
      filters.push({ type: "GeometryFilter", field_name: "geometry", config: geo });
    } catch (e) {
      throw new Error("Invalid GeoJSON geometry: " + e.message);
    }
  }

  if (opts.bbox) {
    const [west, south, east, north] = opts.bbox.split(",").map(Number);
    filters.push({
      type: "GeometryFilter",
      field_name: "geometry",
      config: {
        type: "Polygon",
        coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
      },
    });
  }

  if (opts.downloadable) {
    filters.push({ type: "PermissionFilter", config: ["assets:download"] });
  }

  const body = {
    item_types: [opts.itemType || "PSScene"],
    filter: filters.length === 1 ? filters[0] : { type: "AndFilter", config: filters },
  };

  const limit = parseInt(opts.limit || "10", 10);
  const routePath = `/api/data/v1/quick-search?_page_size=${limit}`;
  const resp = await proxyRequest("POST", routePath, body);
  return {
    count: (resp.features || []).length,
    items: (resp.features || []).map(formatItem),
  };
}

async function getItem(itemType, itemId) {
  const resp = await proxyRequest("GET", `/api/data/v1/item-types/${itemType}/items/${itemId}`);
  return {
    ...formatItem(resp),
    geometry: resp.geometry,
    properties: resp.properties,
  };
}

async function getAssets(itemType, itemId) {
  const resp = await proxyRequest("GET", `/api/data/v1/item-types/${itemType}/items/${itemId}/assets`);
  const assets = [];
  for (const [name, info] of Object.entries(resp || {})) {
    assets.push({
      name,
      type: info.type,
      status: info.status,
      md5_digest: info.md5_digest,
      expires_at: info.expires_at,
    });
  }
  return assets;
}

async function stats(opts) {
  const filters = [];

  if (opts.startDate || opts.endDate) {
    const config = {};
    if (opts.startDate) config.gte = opts.startDate;
    if (opts.endDate) config.lte = opts.endDate;
    filters.push({ type: "DateRangeFilter", field_name: "acquired", config });
  }

  if (opts.maxCloud !== undefined) {
    filters.push({
      type: "RangeFilter",
      field_name: "cloud_cover",
      config: { lte: parseFloat(opts.maxCloud) },
    });
  }

  if (opts.bbox) {
    const [west, south, east, north] = opts.bbox.split(",").map(Number);
    filters.push({
      type: "GeometryFilter",
      field_name: "geometry",
      config: {
        type: "Polygon",
        coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
      },
    });
  }

  if (opts.geometry) {
    try {
      const geo = JSON.parse(opts.geometry);
      filters.push({ type: "GeometryFilter", field_name: "geometry", config: geo });
    } catch (e) {
      throw new Error("Invalid GeoJSON geometry: " + e.message);
    }
  }

  const body = {
    item_types: [opts.itemType || "PSScene"],
    interval: opts.interval || "month",
    filter: filters.length === 0
      ? { type: "DateRangeFilter", field_name: "acquired", config: { gte: "2020-01-01T00:00:00Z" } }
      : filters.length === 1
        ? filters[0]
        : { type: "AndFilter", config: filters },
  };

  const resp = await proxyRequest("POST", "/api/data/v1/stats", body);
  const buckets = (resp.buckets || []).map((b) => ({
    start: b.start_time,
    count: b.count,
  }));
  const total = buckets.reduce((s, b) => s + b.count, 0);
  return { total, interval: body.interval, buckets };
}

async function listSearches(opts) {
  const limit = parseInt(opts.limit || "10", 10);
  const resp = await proxyRequest("GET", `/api/data/v1/searches?_page_size=${limit}&search_type=${opts.type || "any"}`);
  return (resp.searches || []).map((s) => ({
    id: s.id,
    name: s.name,
    created: s.created,
    last_executed: s.last_executed,
    item_types: s.item_types,
  }));
}

async function taskingPricing(opts) {
  const geometry = parseGeometry(opts);
  if (!geometry) throw new Error("--bbox or --geometry is required for tasking-pricing");
  const body = { geometry };
  if (opts.product) body.product = opts.product;
  if (opts.plNumber) body.pl_number = opts.plNumber;
  const resp = await proxyRequest("POST", "/api/tasking/v2/pricing/", body);
  return {
    estimated_quota_cost: resp.estimated_quota_cost,
    pricing_model: resp.pricing_model,
    area_km2: resp.area_km2,
    multipliers: resp.multipliers,
    product: resp.product,
    raw: resp,
  };
}

async function imagingWindows(opts) {
  const geometry = parseGeometry(opts);
  if (!geometry) throw new Error("--bbox or --geometry is required for imaging-windows");
  const body = { geometry };
  if (opts.startDate) body.start_time = opts.startDate;
  if (opts.endDate) body.end_time = opts.endDate;
  if (opts.maxCloud) body.cloud_cover = parseFloat(opts.maxCloud);
  if (opts.offNadir) body.off_nadir_angle = parseFloat(opts.offNadir);

  const searchResp = await proxyRequest("POST", "/api/tasking/v2/imaging-windows/search/", body);
  const searchId = searchResp.id || searchResp.search_id;
  if (!searchId) return { status: "immediate", results: searchResp };

  const maxAttempts = 15;
  for (let i = 0; i < maxAttempts; i++) {
    await sleep(2000);
    const poll = await proxyRequest("GET", `/api/tasking/v2/imaging-windows/search/${searchId}/`);
    const status = (poll.status || "").toLowerCase();
    if (status === "completed" || status === "complete" || poll.windows) {
      const windows = (poll.windows || poll.results || []).map((w) => ({
        start: w.start_time,
        end: w.end_time,
        satellite: w.satellite_name || w.satellite,
        off_nadir: w.off_nadir_angle,
        gsd: w.gsd,
        cloud_forecast: w.cloud_forecast,
        assured_tier: w.assured_tasking_tier,
        pricing: w.pricing_details,
      }));
      return { search_id: searchId, count: windows.length, windows };
    }
    if (status === "failed" || status === "error") {
      throw new Error(`Imaging window search failed: ${JSON.stringify(poll)}`);
    }
  }
  return { search_id: searchId, status: "pending", message: "Search still running. Poll manually with tasking-poll." };
}

async function taskingOrders(opts) {
  const params = [];
  if (opts.status) params.push(`status=${encodeURIComponent(opts.status)}`);
  if (opts.limit) params.push(`limit=${parseInt(opts.limit, 10)}`);
  const qs = params.length ? "?" + params.join("&") : "";
  const resp = await proxyRequest("GET", `/api/tasking/v2/orders/${qs}`);
  return (resp.results || resp.orders || []).map((o) => ({
    id: o.id,
    name: o.name,
    status: o.status,
    created: o.created_time || o.created,
    start: o.start_time,
    end: o.end_time,
    product: o.product,
    estimated_cost: o.estimated_quota_cost,
    captures_count: o.captures_count,
  }));
}

async function taskingOrder(id) {
  const resp = await proxyRequest("GET", `/api/tasking/v2/orders/${id}/`);
  return {
    id: resp.id,
    name: resp.name,
    status: resp.status,
    created: resp.created_time || resp.created,
    start: resp.start_time,
    end: resp.end_time,
    product: resp.product,
    estimated_cost: resp.estimated_quota_cost,
    geometry: resp.geometry,
    captures_count: resp.captures_count,
    parameters: resp.parameters,
  };
}

async function taskingCaptures(opts) {
  const params = [];
  if (opts.order) params.push(`order_id=${encodeURIComponent(opts.order)}`);
  if (opts.status) params.push(`status=${encodeURIComponent(opts.status)}`);
  if (opts.limit) params.push(`limit=${parseInt(opts.limit, 10)}`);
  const qs = params.length ? "?" + params.join("&") : "";
  const resp = await proxyRequest("GET", `/api/tasking/v2/captures/${qs}`);
  return (resp.results || resp.captures || []).map((c) => ({
    id: c.id,
    order_id: c.order_id,
    status: c.status,
    acquired: c.acquired_time || c.acquired,
    cloud_cover: c.cloud_cover_percentage || c.cloud_cover,
    satellite: c.satellite_name || c.satellite,
    published: c.published,
  }));
}

async function myQuota() {
  const resp = await proxyRequest("GET", "/api/account/v1/my/products");
  return (resp.products || resp || []).map((p) => ({
    name: p.name,
    product_type: p.product_type,
    quota_total: p.quota_sq_km || p.quota_total,
    quota_used: p.quota_used_sq_km || p.quota_used,
    quota_remaining: p.quota_remaining_sq_km || p.quota_remaining,
    active: p.active,
    start_date: p.start_date,
    end_date: p.end_date,
  }));
}

function tileUrl(itemType, itemId, z, x, y) {
  return `${PROXY_URL}/tiles/data/v1/${itemType}/${itemId}/${z || "{z}"}/${x || "{x}"}/${y || "{y}"}.png`;
}

async function main() {
  const [cmd, ...args] = process.argv.slice(2);
  function getArg(name) {
    const i = args.indexOf("--" + name);
    return i >= 0 && args[i + 1] ? args[i + 1] : null;
  }

  try {
    switch (cmd) {
      case "item-types": {
        console.log(JSON.stringify(await itemTypes(), null, 2));
        break;
      }
      case "search": {
        console.log(JSON.stringify(await search({
          itemType: getArg("type") || "PSScene",
          startDate: getArg("start"),
          endDate: getArg("end"),
          maxCloud: getArg("max-cloud"),
          bbox: getArg("bbox"),
          geometry: getArg("geometry"),
          limit: getArg("limit") || "10",
          downloadable: args.includes("--downloadable"),
        }), null, 2));
        break;
      }
      case "item": {
        const type = getArg("type") || "PSScene";
        const id = args.find((a) => !a.startsWith("--") && a !== type) || getArg("id");
        if (!id) { console.error("Usage: planet-api.js item --id <item-id> [--type PSScene]"); process.exit(1); }
        console.log(JSON.stringify(await getItem(type, id), null, 2));
        break;
      }
      case "assets": {
        const type = getArg("type") || "PSScene";
        const id = args.find((a) => !a.startsWith("--") && a !== type) || getArg("id");
        if (!id) { console.error("Usage: planet-api.js assets --id <item-id> [--type PSScene]"); process.exit(1); }
        console.log(JSON.stringify(await getAssets(type, id), null, 2));
        break;
      }
      case "stats": {
        console.log(JSON.stringify(await stats({
          itemType: getArg("type") || "PSScene",
          startDate: getArg("start"),
          endDate: getArg("end"),
          maxCloud: getArg("max-cloud"),
          bbox: getArg("bbox"),
          geometry: getArg("geometry"),
          interval: getArg("interval") || "month",
        }), null, 2));
        break;
      }
      case "searches": {
        console.log(JSON.stringify(await listSearches({
          limit: getArg("limit") || "10",
          type: getArg("type") || "any",
        }), null, 2));
        break;
      }
      case "tile-url": {
        const type = getArg("type") || "PSScene";
        const id = getArg("id");
        if (!id) { console.error("Usage: planet-api.js tile-url --id <item-id> [--type PSScene] [--z 15] [--x 0] [--y 0]"); process.exit(1); }
        console.log(JSON.stringify({
          template: tileUrl(type, id),
          example: tileUrl(type, id, getArg("z") || "15", getArg("x") || "0", getArg("y") || "0"),
        }, null, 2));
        break;
      }
      case "thumbnail": {
        const type = getArg("type") || "PSScene";
        const id = getArg("id");
        if (!id) { console.error("Usage: planet-api.js thumbnail --id <item-id> [--type PSScene] [--width 512]"); process.exit(1); }
        console.log(JSON.stringify(await thumbnail(type, id, getArg("width") || "512"), null, 2));
        break;
      }
      case "tasking-pricing": {
        console.log(JSON.stringify(await taskingPricing({
          bbox: getArg("bbox"),
          geometry: getArg("geometry"),
          product: getArg("product"),
          plNumber: getArg("pl-number"),
        }), null, 2));
        break;
      }
      case "imaging-windows": {
        console.log(JSON.stringify(await imagingWindows({
          bbox: getArg("bbox"),
          geometry: getArg("geometry"),
          startDate: getArg("start"),
          endDate: getArg("end"),
          maxCloud: getArg("max-cloud"),
          offNadir: getArg("off-nadir"),
        }), null, 2));
        break;
      }
      case "tasking-orders": {
        console.log(JSON.stringify(await taskingOrders({
          status: getArg("status"),
          limit: getArg("limit") || "10",
        }), null, 2));
        break;
      }
      case "tasking-order": {
        const id = getArg("id") || args.find((a) => !a.startsWith("--"));
        if (!id) { console.error("Usage: planet-api.js tasking-order --id <order-id>"); process.exit(1); }
        console.log(JSON.stringify(await taskingOrder(id), null, 2));
        break;
      }
      case "tasking-captures": {
        console.log(JSON.stringify(await taskingCaptures({
          order: getArg("order"),
          status: getArg("status"),
          limit: getArg("limit") || "10",
        }), null, 2));
        break;
      }
      case "my-quota": {
        console.log(JSON.stringify(await myQuota(), null, 2));
        break;
      }
      default:
        console.log("Planet API — Available commands:");
        console.log("");
        console.log("  Catalog:");
        console.log("    item-types                             List satellite constellations");
        console.log("    search [options]                       Search imagery catalog");
        console.log("    item --id <id> [--type PSScene]        Get item details");
        console.log("    assets --id <id> [--type PSScene]      List assets for an item");
        console.log("    stats [options]                        Imagery count statistics");
        console.log("    searches [--limit N]                   List saved searches");
        console.log("    tile-url --id <id> [--type type]       Generate tile URL");
        console.log("    thumbnail --id <id> [--type type]      Download thumbnail to /tmp/");
        console.log("");
        console.log("  Tasking (read-only, no orders placed):");
        console.log("    tasking-pricing --bbox W,S,E,N         Estimate tasking cost for an area");
        console.log("    imaging-windows --bbox W,S,E,N [opts]  Check satellite pass availability");
        console.log("    tasking-orders [--status S] [--limit]  List existing tasking orders");
        console.log("    tasking-order --id <order-id>          Get order details");
        console.log("    tasking-captures [--order id]          List imagery captures");
        console.log("");
        console.log("  Account:");
        console.log("    my-quota                               Show products and quota usage");
        console.log("");
        console.log("  Common options:");
        console.log("    --bbox <W,S,E,N>      Bounding box (west,south,east,north)");
        console.log("    --geometry <GeoJSON>   GeoJSON geometry object");
        console.log("    --start <ISO date>     Start date");
        console.log("    --end <ISO date>       End date");
        console.log("    --max-cloud <0-1>      Max cloud cover (0.1 = 10%)");
        console.log("    --type <ItemType>      Item type (default: PSScene)");
        console.log("    --limit <N>            Max results (default: 10)");
        console.log("    --interval <unit>      Stats interval: hour, day, week, month, year");
        console.log("    --downloadable         Only downloadable items");
        console.log("    --width <pixels>       Thumbnail width (default: 512)");
    }
  } catch (e) {
    console.error("Error:", e.message);
    process.exit(1);
  }
}

main();
