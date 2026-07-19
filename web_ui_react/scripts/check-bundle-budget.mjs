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
const distAssetsDir = resolve(
  repoRoot,
  process.env.SIDAR_BUNDLE_ASSETS_DIR || join(frontendRoot, "dist", "assets"),
);
const reactDomBudgetKb = Number(process.env.SIDAR_REACT_DOM_CHUNK_BUDGET_KB || "220");
const totalJsBudgetKb = optionalNumber(process.env.SIDAR_TOTAL_JS_BUDGET_KB);
const totalGzipBudgetKb = optionalNumber(process.env.SIDAR_TOTAL_GZIP_BUDGET_KB);
const gzipTrendWarnKb = optionalNumber(process.env.SIDAR_BUNDLE_GZIP_TREND_WARN_KB || "5");
const budgetWarnRatio = optionalNumber(process.env.SIDAR_BUNDLE_BUDGET_WARN_RATIO || "0.9");
const productionBudgetGateActive =
  truthy(process.env.SIDAR_PRODUCTION_READINESS) || process.env.TEST_PROFILE === "ci";
const reportPath = resolve(
  repoRoot,
  process.env.SIDAR_BUNDLE_BUDGET_REPORT_PATH || "artifacts/frontend-bundle-budget.json",
);
const previousReportPath = resolve(
  repoRoot,
  process.env.SIDAR_BUNDLE_BUDGET_PREVIOUS_REPORT_PATH || reportPath,
);
const topChunkCount = 5;
const missingRequiredBudgets = [];

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

function validateNonNegativeBudget(name, value) {
  if (value === null) return true;
  if (!Number.isFinite(value) || value < 0) {
    fail(`${name} must be zero or a positive number when set.`);
    return false;
  }
  return true;
}

function validateBudgetWarnRatio(name, value) {
  if (value === null) return true;
  if (!Number.isFinite(value) || value <= 0 || value > 1) {
    fail(`${name} must be greater than 0 and less than or equal to 1 when set.`);
    return false;
  }
  return true;
}

function requireBudgetForProductionGate(name, value) {
  if (!productionBudgetGateActive || value !== null) return true;
  missingRequiredBudgets.push(name);
  fail(`${name} must be set when SIDAR_PRODUCTION_READINESS=1 or TEST_PROFILE=ci.`);
  return false;
}

function readPreviousReport() {
  if (!previousReportPath || previousReportPath === reportPath) {
    try {
      return JSON.parse(readFileSync(reportPath, "utf8"));
    } catch {
      return null;
    }
  }

  try {
    return JSON.parse(readFileSync(previousReportPath, "utf8"));
  } catch {
    return null;
  }
}

function buildBudgetUsage(label, bytes, budgetKb) {
  if (budgetKb === null || !Number.isFinite(budgetKb) || budgetKb <= 0) {
    return { available: false };
  }

  const budgetBytes = budgetKb * 1024;
  const ratio = bytes / budgetBytes;
  const usage = {
    available: true,
    budgetKb,
    bytes,
    kb: Number(formatKb(bytes)),
    ratio,
    percent: Number((ratio * 100).toFixed(2)),
    warnRatio: budgetWarnRatio,
    warning: false,
  };

  if (
    budgetWarnRatio !== null &&
    Number.isFinite(budgetWarnRatio) &&
    ratio >= budgetWarnRatio &&
    bytes <= budgetBytes
  ) {
    usage.warning = true;
    console.warn(
      `⚠️ ${label} is at ${usage.percent}% of budget (${formatKb(bytes)}/${budgetKb} KB); watch dependency additions.`,
    );
  }

  return usage;
}

function buildGzipTrend(previousReport, totalGzipBytes) {
  const previousGzipBytes = Number(previousReport?.totals?.gzipBytes);
  if (!Number.isFinite(previousGzipBytes) || previousGzipBytes <= 0) {
    return { available: false };
  }

  const deltaBytes = totalGzipBytes - previousGzipBytes;
  const trend = {
    available: true,
    previousGzipBytes,
    previousGzipKb: Number(formatKb(previousGzipBytes)),
    deltaBytes,
    deltaKb: Number(formatKb(deltaBytes)),
    warnThresholdKb: gzipTrendWarnKb,
    warning: false,
  };

  console.log(
    `Total gzip JS trend: ${formatKb(deltaBytes)} KB vs previous bundle report (${formatKb(previousGzipBytes)} KB).`,
  );

  if (
    gzipTrendWarnKb !== null &&
    Number.isFinite(gzipTrendWarnKb) &&
    gzipTrendWarnKb > 0 &&
    deltaBytes > gzipTrendWarnKb * 1024
  ) {
    trend.warning = true;
    console.warn(
      `⚠️ Total gzip JS grew by ${formatKb(deltaBytes)} KB since the previous bundle report (warning threshold +${gzipTrendWarnKb} KB).`,
    );
  }

  return trend;
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
validateNonNegativeBudget("SIDAR_BUNDLE_GZIP_TREND_WARN_KB", gzipTrendWarnKb);
validateBudgetWarnRatio("SIDAR_BUNDLE_BUDGET_WARN_RATIO", budgetWarnRatio);
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
const previousReport = readPreviousReport();
const budgetUsage = {
  totalJs: buildBudgetUsage("Total JS", totalJsBytes, totalJsBudgetKb),
  totalGzip: buildBudgetUsage("Total gzip JS", totalGzipBytes, totalGzipBudgetKb),
};
const gzipTrend = buildGzipTrend(previousReport, totalGzipBytes);
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
    gzipTrendWarn: gzipTrendWarnKb,
    warnRatio: budgetWarnRatio,
  },
  missingRequiredBudgets,
  budgetUsage,
  totals: {
    jsBytes: totalJsBytes,
    jsKb: Number(formatKb(totalJsBytes)),
    gzipBytes: totalGzipBytes,
    gzipKb: Number(formatKb(totalGzipBytes)),
  },
  trend: {
    gzip: gzipTrend,
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
