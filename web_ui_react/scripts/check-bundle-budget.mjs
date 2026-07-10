#!/usr/bin/env node
import { gzipSync } from "node:zlib";
import {
  mkdirSync,
  readFileSync,
  readdirSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendRoot = join(scriptDir, "..");
const repoRoot = join(frontendRoot, "..");
const distAssetsDir = join(frontendRoot, "dist", "assets");
const reactDomBudgetKb = Number(process.env.SIDAR_REACT_DOM_CHUNK_BUDGET_KB || "220");
const totalJsBudgetKb = optionalNumber(process.env.SIDAR_TOTAL_JS_BUDGET_KB);
const totalGzipBudgetKb = optionalNumber(process.env.SIDAR_TOTAL_GZIP_BUDGET_KB);
const productionBudgetGateActive =
  truthy(process.env.SIDAR_PRODUCTION_READINESS) || process.env.TEST_PROFILE === "ci";
const reportPath = resolve(
  repoRoot,
  process.env.SIDAR_BUNDLE_BUDGET_REPORT_PATH || "artifacts/frontend-bundle-budget.json",
);
const topChunkCount = 5;

function optionalNumber(value) {
  if (value === undefined || value === null || String(value).trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function truthy(value) {
  return ["1", "true", "yes", "y", "evet", "e"].includes(
    String(value ?? "").trim().toLowerCase(),
  );
}

function fail(message) {
  console.error(`❌ ${message}`);
  process.exitCode = 1;
}

function formatKb(bytes) {
  return (bytes / 1024).toFixed(2);
}

function budgetLabel(value) {
  return value === null ? "not set" : `${value} KB`;
}

function validateBudget(name, value) {
  if (value === null) return true;
  if (!Number.isFinite(value) || value <= 0) {
    fail(`${name} must be a positive number when set.`);
    return false;
  }
  return true;
}

function requireBudgetForProductionGate(name, value) {
  if (!productionBudgetGateActive || value !== null) return true;
  fail(`${name} must be set when SIDAR_PRODUCTION_READINESS=1 or TEST_PROFILE=ci.`);
  return false;
}

function writeReport(report) {
  mkdirSync(dirname(reportPath), { recursive: true });
  writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(`🧾 Bundle budget report written: ${reportPath}`);
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

validateBudget("SIDAR_REACT_DOM_CHUNK_BUDGET_KB", reactDomBudgetKb);
validateBudget("SIDAR_TOTAL_JS_BUDGET_KB", totalJsBudgetKb);
validateBudget("SIDAR_TOTAL_GZIP_BUDGET_KB", totalGzipBudgetKb);
requireBudgetForProductionGate("SIDAR_TOTAL_JS_BUDGET_KB", totalJsBudgetKb);
requireBudgetForProductionGate("SIDAR_TOTAL_GZIP_BUDGET_KB", totalGzipBudgetKb);

const jsChunks = entries
  .filter((name) => name.endsWith(".js"))
  .map((name) => {
    const filePath = join(distAssetsDir, name);
    const content = readFileSync(filePath);
    const sizeBytes = statSync(filePath).size;
    return {
      name,
      sizeBytes,
      gzipBytes: gzipSync(content).length,
    };
  })
  .sort((left, right) => right.sizeBytes - left.sizeBytes);

const reactDomChunks = jsChunks.filter((chunk) => /^react-dom-[\w-]+\.js$/.test(chunk.name));

if (reactDomChunks.length === 0) {
  fail(
    "React DOM chunk was not emitted as its own manual chunk; check Vite manualChunks config.",
  );
}

const totalJsBytes = jsChunks.reduce((total, chunk) => total + chunk.sizeBytes, 0);
const totalGzipBytes = jsChunks.reduce((total, chunk) => total + chunk.gzipBytes, 0);
const topChunks = jsChunks.slice(0, topChunkCount);

const oversizedChunks = reactDomChunks.filter(
  (chunk) => chunk.sizeBytes > reactDomBudgetKb * 1024,
);

for (const chunk of reactDomChunks) {
  console.log(
    `React DOM chunk: ${chunk.name} ${formatKb(chunk.sizeBytes)} KB (gzip ${formatKb(chunk.gzipBytes)} KB, budget ${reactDomBudgetKb} KB)`,
  );
}

console.log(
  `Total JS: ${formatKb(totalJsBytes)} KB (budget ${budgetLabel(totalJsBudgetKb)})`,
);
console.log(
  `Total gzip JS: ${formatKb(totalGzipBytes)} KB (budget ${budgetLabel(totalGzipBudgetKb)})`,
);
console.log(`Top ${topChunks.length} JS chunks by raw size:`);
for (const [index, chunk] of topChunks.entries()) {
  console.log(
    `  ${index + 1}. ${chunk.name}: ${formatKb(chunk.sizeBytes)} KB (gzip ${formatKb(chunk.gzipBytes)} KB)`,
  );
}

if (oversizedChunks.length > 0) {
  for (const chunk of oversizedChunks) {
    console.error(
      `React DOM chunk ${chunk.name} exceeds budget: ${formatKb(chunk.sizeBytes)} KB > ${reactDomBudgetKb} KB`,
    );
  }
  process.exitCode = 1;
}

if (totalJsBudgetKb !== null && Number.isFinite(totalJsBudgetKb) && totalJsBytes > totalJsBudgetKb * 1024) {
  fail(`Total JS exceeds budget: ${formatKb(totalJsBytes)} KB > ${totalJsBudgetKb} KB`);
}

if (
  totalGzipBudgetKb !== null &&
  Number.isFinite(totalGzipBudgetKb) &&
  totalGzipBytes > totalGzipBudgetKb * 1024
) {
  fail(`Total gzip JS exceeds budget: ${formatKb(totalGzipBytes)} KB > ${totalGzipBudgetKb} KB`);
}

writeReport({
  generatedAt: new Date().toISOString(),
  distAssetsDir,
  budgetsKb: {
    reactDomChunk: reactDomBudgetKb,
    totalJs: totalJsBudgetKb,
    totalGzip: totalGzipBudgetKb,
  },
  totals: {
    jsBytes: totalJsBytes,
    jsKb: Number(formatKb(totalJsBytes)),
    gzipBytes: totalGzipBytes,
    gzipKb: Number(formatKb(totalGzipBytes)),
  },
  reactDomChunks: reactDomChunks.map((chunk) => ({
    ...chunk,
    sizeKb: Number(formatKb(chunk.sizeBytes)),
    gzipKb: Number(formatKb(chunk.gzipBytes)),
  })),
  topChunks: topChunks.map((chunk) => ({
    ...chunk,
    sizeKb: Number(formatKb(chunk.sizeBytes)),
    gzipKb: Number(formatKb(chunk.gzipBytes)),
  })),
  allJsChunks: jsChunks.map((chunk) => ({
    ...chunk,
    sizeKb: Number(formatKb(chunk.sizeBytes)),
    gzipKb: Number(formatKb(chunk.gzipBytes)),
  })),
});

if (process.exitCode && process.exitCode !== 0) {
  process.exit();
}

console.log("✅ Bundle budget check passed.");
