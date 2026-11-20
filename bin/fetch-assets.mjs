#!/usr/bin/env node
// assets/manifest.json 에 적힌 Poly Haven(CC0) 에셋을 assets/ 아래로 내려받는다.
// 이미 받은 파일은 건너뛴다. 사용: node bin/fetch-assets.mjs
// (프록시 환경에서는 NODE_USE_ENV_PROXY=1 필요)
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(readFileSync(join(root, "assets", "manifest.json"), "utf8"));
const res = manifest.resolution ?? "2k";
const API = "https://api.polyhaven.com/files";

// Poly Haven 맵 이름 -> 로컬 파일명 접미사 (scenes/lib.py make_pbr_from_textures 가 인식하는 이름)
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
    console.warn(`! model ${id}: glTF 없음`);
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
