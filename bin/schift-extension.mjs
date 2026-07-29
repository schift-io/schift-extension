#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const entrypoint = join(here, "..", "src", "apm_bridge", "cli.py");
const python = process.env.PYTHON ?? "python3";
const result = spawnSync(python, [entrypoint, ...process.argv.slice(2)], { stdio: "inherit" });

if (result.error) {
  console.error(`schift-extension could not start ${python}: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
