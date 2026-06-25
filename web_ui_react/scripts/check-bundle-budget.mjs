#!/usr/bin/env node
import { readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const distAssetsDir = join(scriptDir, "..", "dist", "assets");
const reactDomBudgetKb = Number(process.env.SIDAR_REACT_DOM_CHUNK_BUDGET_KB || "220");

function fail(message) {
  console.error(`❌ ${message}`);
  process.exitCode = 1;
}

function formatKb(bytes) {
  return (bytes / 1024).toFixed(2);
}

let entries;
try {
  entries = readdirSync(distAssetsDir);
} catch (error) {
  fail(
    `Vite dist assets not found at ${distAssetsDir}; run npm run build first. (${error.message})`,
  );
  process.exit();
}

const reactDomChunks = entries
  .filter((name) => /^react-dom-[\w-]+\.js$/.test(name))
  .map((name) => {
    const filePath = join(distAssetsDir, name);
    return { name, sizeBytes: statSync(filePath).size };
  });

if (reactDomChunks.length === 0) {
  fail(
    "React DOM chunk was not emitted as its own manual chunk; check Vite manualChunks config.",
  );
  process.exit();
}

const oversizedChunks = reactDomChunks.filter(
  (chunk) => chunk.sizeBytes > reactDomBudgetKb * 1024,
);

for (const chunk of reactDomChunks) {
  console.log(
    `React DOM chunk: ${chunk.name} ${formatKb(chunk.sizeBytes)} KB (budget ${reactDomBudgetKb} KB)`,
  );
}

if (oversizedChunks.length > 0) {
  for (const chunk of oversizedChunks) {
    console.error(
      `React DOM chunk ${chunk.name} exceeds budget: ${formatKb(chunk.sizeBytes)} KB > ${reactDomBudgetKb} KB`,
    );
  }
  process.exitCode = 1;
} else {
  console.log("✅ React DOM bundle budget check passed.");
}
