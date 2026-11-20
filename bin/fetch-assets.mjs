#!/usr/bin/env node
// Download the Poly Haven (CC0) assets listed in assets/manifest.json into assets/.
// Files already downloaded are skipped. Usage: node bin/fetch-assets.mjs
// (NODE_USE_ENV_PROXY=1 is required behind a proxy)
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(readFileSync(join(root, "assets", "manifest.json"), "utf8"));
const res = manifest.resolution ?? "2k";
const API = "https://api.polyhaven.com/files";

// Poly Haven map name -> local filename suffix (names recognized by make_pbr_from_textures in scenes/lib.py)
const MAPS = { Diffuse: "diffuse", nor_gl: "normal", Rough: "roughness", Metal: "metallic", Displacement: "displacement" };

async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

async function download(url, dest) {
  if (existsSync(dest)) return false;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  mkdirSync(dirname(dest), { recursive: true });
  writeFileSync(dest, Buffer.from(await r.arrayBuffer()));
  return true;
}

for (const id of manifest.textures ?? []) {
  const files = await getJson(`${API}/${id}`);
  for (const [key, suffix] of Object.entries(MAPS)) {
    const entry = files[key]?.[res];
    const file = entry?.jpg ?? entry?.png;
    if (!file) continue;
    const ext = entry.jpg ? "jpg" : "png";
    const got = await download(file.url, join(root, "assets", "textures", id, `${id}_${suffix}.${ext}`));
    console.log(`${got ? "↓" : "="} texture ${id} ${suffix}`);
  }
}

for (const id of manifest.models ?? []) {
  const files = await getJson(`${API}/${id}`);
  const gltf = files.gltf?.[res]?.gltf ?? files.gltf?.["1k"]?.gltf;
  if (!gltf) {
    console.warn(`! model ${id}: no glTF`);
    continue;
  }
  const dir = join(root, "assets", "models", id);
  const main = await download(gltf.url, join(dir, `${id}.gltf`));
  let n = 0;
  for (const [rel, inc] of Object.entries(gltf.include ?? {})) {
    if (await download(inc.url, join(dir, rel))) n++;
  }
  console.log(`${main || n ? "↓" : "="} model ${id} (+${n} files)`);
}
