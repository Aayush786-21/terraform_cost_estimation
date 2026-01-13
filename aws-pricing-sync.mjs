#!/usr/bin/env node
/**
 * aws-pricing-sync.mjs
 * Downloads AWS Price List Bulk API regional offer files and stores them locally.
 * Node >= 18 (uses global fetch).
 *
 * Examples:
 *   node aws-pricing-sync.mjs --out pricing-cache/aws --services AmazonEC2,AmazonRDS,AmazonS3 --gzip
 *   node aws-pricing-sync.mjs --out pricing-cache/aws --all-services --gzip --concurrency 8
 */

import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import crypto from "node:crypto";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";

const BASE = "https://pricing.us-east-1.amazonaws.com";
const SERVICE_INDEX_URL = `${BASE}/offers/v1.0/aws/index.json`;

function parseArgs(argv) {
  const args = {
    out: "pricing-cache/aws",
    services: null,       // comma list
    allServices: false,
    regions: null,        // comma list
    gzip: true,
    concurrency: 6,
    force: false,
  };

  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--out") args.out = argv[++i];
    else if (a === "--services") args.services = argv[++i];
    else if (a === "--all-services") args.allServices = true;
    else if (a === "--regions") args.regions = argv[++i];
    else if (a === "--no-gzip") args.gzip = false;
    else if (a === "--gzip") args.gzip = true;
    else if (a === "--concurrency") args.concurrency = Number(argv[++i] || "6");
    else if (a === "--force") args.force = true;
  }

  args.concurrency = Number.isFinite(args.concurrency) && args.concurrency > 0 ? args.concurrency : 6;
  return args;
}

function toAbsUrl(urlOrPath) {
  if (!urlOrPath) return null;
  if (urlOrPath.startsWith("http://") || urlOrPath.startsWith("https://")) return urlOrPath;
  // AWS region index returns a *relative* URL like: /offers/v1.0/aws/AmazonRDS/<version>/us-east-2/index.json
  return `${BASE}${urlOrPath}`;
}

async function ensureDir(dir) {
  await fs.promises.mkdir(dir, { recursive: true });
}

async function fetchJson(url) {
  const res = await fetch(url, { headers: { "accept": "application/json" } });
  if (!res.ok) throw new Error(`Fetch failed ${res.status} ${res.statusText}: ${url}`);
  return await res.json();
}

async function downloadFile(url, destPath, { gzip, force }) {
  if (!force && fs.existsSync(destPath)) {
    return { skipped: true, sha256: null, bytes: 0 };
  }

  await ensureDir(path.dirname(destPath));

  const res = await fetch(url);
  if (!res.ok) throw new Error(`Download failed ${res.status} ${res.statusText}: ${url}`);

  const hash = crypto.createHash("sha256");
  let bytes = 0;

  const tap = new Transform({
    transform(chunk, _enc, cb) {
      bytes += chunk.length;
      hash.update(chunk);
      cb(null, chunk);
    },
  });

  const body = Readable.fromWeb(res.body);

  const out = fs.createWriteStream(destPath);
  if (gzip) {
    await pipeline(body, tap, zlib.createGzip({ level: 9 }), out);
  } else {
    await pipeline(body, tap, out);
  }

  return { skipped: false, sha256: hash.digest("hex"), bytes };
}

async function asyncPool(limit, items, iteratorFn) {
  const ret = [];
  const executing = new Set();

  for (const item of items) {
    const p = Promise.resolve().then(() => iteratorFn(item));
    ret.push(p);
    executing.add(p);

    const clean = () => executing.delete(p);
    p.then(clean).catch(clean);

    if (executing.size >= limit) {
      await Promise.race(executing);
    }
  }
  return Promise.all(ret);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  const regionFilter = args.regions
    ? new Set(args.regions.split(",").map((s) => s.trim()).filter(Boolean))
    : null;

  console.log(`Fetching service index: ${SERVICE_INDEX_URL}`);
  const index = await fetchJson(SERVICE_INDEX_URL);

  const offers = index.offers || index.Offers;
  if (!offers) throw new Error("Unexpected service index format: missing 'offers'");

  const allServiceCodes = Object.keys(offers);

  let serviceCodes;
  if (args.allServices) {
    serviceCodes = allServiceCodes;
  } else if (args.services) {
    serviceCodes = args.services.split(",").map((s) => s.trim()).filter(Boolean);
  } else {
    // sensible default set for Terraform estimators
    serviceCodes = [
      "AmazonEC2",
      "AmazonEBS",
      "AmazonRDS",
      "AmazonS3",
      "AWSLambda",
      "AWSDataTransfer",
      "ElasticLoadBalancing",
      "AmazonCloudFront",
    ].filter((s) => allServiceCodes.includes(s));
  }

  await ensureDir(args.out);

  const manifest = {
    generatedAt: new Date().toISOString(),
    base: BASE,
    serviceIndex: SERVICE_INDEX_URL,
    services: [],
  };

  // Build a big list of download tasks
  const tasks = [];

  for (const serviceCode of serviceCodes) {
    const offer = offers[serviceCode];
    if (!offer) continue;

    const regionIndexUrl =
      toAbsUrl(offer.currentRegionIndexUrl || offer.currentRegionIndexURL || offer.currentRegionIndexUrl);

    if (!regionIndexUrl) {
      console.warn(`No region index URL for ${serviceCode}, skipping.`);
      continue;
    }

    console.log(`Fetching region index for ${serviceCode}`);
    const regionIndex = await fetchJson(regionIndexUrl);

    const regionsObj = regionIndex.regions || regionIndex.Regions;
    if (!regionsObj) {
      console.warn(`Unexpected region index format for ${serviceCode}, skipping.`);
      continue;
    }

    const serviceEntry = {
      serviceCode,
      regionIndexUrl,
      publicationDate: regionIndex.publicationDate || null,
      files: [],
    };

    for (const key of Object.keys(regionsObj)) {
      const r = regionsObj[key];
      const regionCode = r.regionCode || key;
      if (regionFilter && !regionFilter.has(regionCode)) continue;

      const priceUrl = toAbsUrl(r.currentVersionUrl);
      if (!priceUrl) continue;

      const fileName = `${regionCode}.json${args.gzip ? ".gz" : ""}`;
      const destPath = path.join(args.out, serviceCode, fileName);

      tasks.push({
        serviceCode,
        regionCode,
        url: priceUrl,
        destPath,
        gzip: args.gzip,
        force: args.force,
      });

      serviceEntry.files.push({
        regionCode,
        url: priceUrl,
        path: path.relative(path.dirname(args.out), destPath),
      });
    }

    manifest.services.push(serviceEntry);
  }

  console.log(`Planned downloads: ${tasks.length}`);
  const results = await asyncPool(args.concurrency, tasks, async (t) => {
    const r = await downloadFile(t.url, t.destPath, { gzip: t.gzip, force: t.force });
    if (!r.skipped) {
      console.log(`✓ ${t.serviceCode}/${t.regionCode} (${r.bytes} bytes raw)`);
    }
    return { ...t, ...r };
  });

  const manifestPath = path.join(path.dirname(args.out), "manifest.json");
  await fs.promises.writeFile(
    manifestPath,
    JSON.stringify({ ...manifest, downloads: results }, null, 2),
    "utf8"
  );

  console.log(`Done. Manifest written to: ${manifestPath}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
