#!/usr/bin/env node
// Run scenes/<name>.py with Blender in headless mode.
// Usage: node bin/blender.mjs <scene> [scene args...]
// Blender path: BLENDER_BIN environment variable (default: `blender` on PATH)
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const [scene, ...sceneArgs] = process.argv.slice(2);

if (!scene) {
  console.error("usage: node bin/blender.mjs <scene> [args...]");
  process.exit(1);
}

const script = join(root, "scenes", `${scene}.py`);
if (!existsSync(script)) {
  console.error(`scene not found: ${script}`);
  process.exit(1);
}

mkdirSync(join(root, "out"), { recursive: true });

const bin = process.env.BLENDER_BIN || "blender";
const result = spawnSync(
  bin,
  ["-b", "--factory-startup", "-noaudio", "-P", script, "--", ...sceneArgs],
  { cwd: root, stdio: "inherit" },
);

if (result.error?.code === "ENOENT") {
  console.error(
    `Could not find the Blender executable: ${bin}\n` +
      "Install Blender or set the BLENDER_BIN environment variable to its path.\n" +
      "  e.g. BLENDER_BIN=/Applications/Blender.app/Contents/MacOS/Blender",
  );
  process.exit(127);
}

process.exit(result.status ?? 1);
