#!/usr/bin/env node
// Blender를 헤드리스로 실행해 scenes/<name>.py 를 돌린다.
// 사용: node bin/blender.mjs <scene> [scene args...]
// Blender 경로: 환경변수 BLENDER_BIN (기본값: PATH 의 `blender`)
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
    `Blender 실행 파일을 찾을 수 없습니다: ${bin}\n` +
      "Blender를 설치하거나 BLENDER_BIN 환경변수에 경로를 지정하세요.\n" +
      "  예) BLENDER_BIN=/Applications/Blender.app/Contents/MacOS/Blender",
  );
  process.exit(127);
}

process.exit(result.status ?? 1);
