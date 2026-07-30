#!/usr/bin/env node
const { spawnSync } = require("node:child_process");
const { mkdirSync, rmSync, writeFileSync } = require("node:fs");
const { dirname, resolve } = require("node:path");

const NETWORK_MARKERS = [
  "audit endpoint returned an error",
  "request to https://registry.npmjs.org",
  "eai_again",
  "econnreset",
  "enotfound",
  "etimedout",
  "network",
  "socket hang up",
  "timeout",
  "tunneling socket could not be established",
];
const AUDIT_LEVELS = ["info", "low", "moderate", "high", "critical"];

function severityMeetsThreshold(severity, threshold) {
  const severityIndex = AUDIT_LEVELS.indexOf(String(severity || "").toLowerCase());
  const thresholdIndex = AUDIT_LEVELS.indexOf(String(threshold || "").toLowerCase());
  return severityIndex >= 0 && thresholdIndex >= 0 && severityIndex >= thresholdIndex;
}

function parseAuditPayload(stdout) {
  if (!stdout.trim()) {
    return {};
  }
  try {
    return JSON.parse(stdout);
  } catch {
    return {};
  }
}

function hasAuditFindingsAtOrAboveLevel(payload, threshold) {
  const counts = payload.metadata?.vulnerabilities;
  if (counts && typeof counts === "object") {
    return AUDIT_LEVELS.some(
      (level) => severityMeetsThreshold(level, threshold) && Number(counts[level] || 0) > 0,
    );
  }

  const vulnerabilities = payload.vulnerabilities;
  if (vulnerabilities && typeof vulnerabilities === "object") {
    return Object.values(vulnerabilities).some((finding) =>
      severityMeetsThreshold(finding?.severity, threshold),
    );
  }
  return false;
}

function parseArgs(argv) {
  const options = {
    allowNetworkFailure: undefined,
    artifactDir: process.env.FRONTEND_NPM_AUDIT_ARTIFACT_DIR || "../artifacts/frontend-security",
    level: process.env.FRONTEND_NPM_AUDIT_LEVEL || "high",
    npmBinary: process.env.FRONTEND_NPM_AUDIT_NPM_BINARY || "npm",
    retries: Number.parseInt(process.env.FRONTEND_NPM_AUDIT_MAX_RETRIES || "2", 10),
    retryWaitSeconds: Number.parseInt(process.env.FRONTEND_NPM_AUDIT_RETRY_WAIT_SECONDS || "5", 10),
  };

  for (const arg of argv) {
    if (arg === "--") {
      continue;
    } else if (arg.startsWith("--level=")) {
      options.level = arg.slice("--level=".length);
    } else if (arg.startsWith("--retries=")) {
      options.retries = Number.parseInt(arg.slice("--retries=".length), 10);
    } else if (arg.startsWith("--retry-wait-seconds=")) {
      options.retryWaitSeconds = Number.parseInt(arg.slice("--retry-wait-seconds=".length), 10);
    } else if (arg.startsWith("--artifact-dir=")) {
      options.artifactDir = arg.slice("--artifact-dir=".length);
    } else if (arg === "--allow-network-failure") {
      options.allowNetworkFailure = true;
    } else if (arg === "--no-allow-network-failure") {
      options.allowNetworkFailure = false;
    } else {
      console.error(`Unknown option: ${arg}`);
      process.exit(2);
    }
  }

  if (!Number.isFinite(options.retries) || options.retries < 1) {
    options.retries = 1;
  }
  if (!Number.isFinite(options.retryWaitSeconds) || options.retryWaitSeconds < 0) {
    options.retryWaitSeconds = 0;
  }
  if (options.allowNetworkFailure === undefined) {
    const envOverride = process.env.FRONTEND_NPM_AUDIT_ALLOW_NETWORK_FAILURE;
    if (envOverride !== undefined) {
      options.allowNetworkFailure = envOverride === "1" || envOverride.toLowerCase() === "true";
    } else {
      options.allowNetworkFailure = !process.env.CI && !process.env.GITHUB_ACTIONS;
    }
  }
  return options;
}

function classifyAuditFailure(stdout, stderr, threshold) {
  const combined = `${stdout}\n${stderr}`.toLowerCase();
  const payload = parseAuditPayload(stdout);
  if (hasAuditFindingsAtOrAboveLevel(payload, threshold)) {
    return "vulnerability";
  }

  if (NETWORK_MARKERS.some((marker) => combined.includes(marker))) {
    return "network";
  }
  return "unknown";
}

function sleepSeconds(seconds) {
  if (seconds <= 0) {
    return;
  }
  spawnSync(process.execPath, ["-e", `setTimeout(() => {}, ${seconds * 1000})`], { stdio: "ignore" });
}

const options = parseArgs(process.argv.slice(2));
const artifactDir = resolve(process.cwd(), options.artifactDir);
const rawReportPath = resolve(artifactDir, "npm-audit-report.raw.json");
const stderrLogPath = resolve(artifactDir, "npm-audit-stderr.log");
const failureArtifactPath = resolve(artifactDir, "npm-audit-failure.json");
mkdirSync(artifactDir, { recursive: true });

for (let attempt = 1; attempt <= options.retries; attempt += 1) {
  const result = spawnSync(options.npmBinary, ["audit", `--audit-level=${options.level}`, "--json"], {
    encoding: "utf8",
    maxBuffer: 20 * 1024 * 1024,
  });
  const stdout = result.stdout || "";
  const stderr = result.stderr || "";
  writeFileSync(rawReportPath, stdout, "utf8");
  writeFileSync(stderrLogPath, stderr, "utf8");

  // npm versions have not always applied --audit-level consistently to the
  // JSON-mode exit status. Treat the JSON report as the security gate's source
  // of truth, even when npm itself exits successfully.
  const category = classifyAuditFailure(stdout, stderr, options.level);
  if (result.status === 0 && category !== "vulnerability") {
    rmSync(failureArtifactPath, { force: true });
    process.stdout.write(stdout);
    process.stderr.write(stderr);
    process.exit(0);
  }

  if (category === "network" && attempt < options.retries) {
    console.warn(
      `⚠️ npm audit ağ hatası aldı (deneme ${attempt}/${options.retries}). ${options.retryWaitSeconds}s sonra yeniden denenecek...`,
    );
    sleepSeconds(options.retryWaitSeconds);
    continue;
  }

  mkdirSync(dirname(failureArtifactPath), { recursive: true });
  const effectiveExitCode = result.status || 1;
  writeFileSync(
    failureArtifactPath,
    `${JSON.stringify(
      {
        tool: "npm audit",
        failure_category: category,
        exit_code: effectiveExitCode,
        audit_level: options.level,
        raw_report: rawReportPath,
        stderr_log: stderrLogPath,
      },
      null,
      2,
    )}\n`,
    "utf8",
  );

  if (category === "network" && options.allowNetworkFailure) {
    console.warn("⚠️ npm audit ağ/registry hatası nedeniyle tamamlanamadı — bu gerçek bir güvenlik bulgusu DEĞİLDİR.");
    console.warn(`    Ayrıntılar: ${stderrLogPath}`);
    console.warn("    Strict mod için: FRONTEND_NPM_AUDIT_ALLOW_NETWORK_FAILURE=0 npm run audit:high");
    process.exit(0);
  }

  if (category === "network") {
    console.error(
      `❌ npm audit ağ/registry hatası strict modda fail edildi (FRONTEND_NPM_AUDIT_ALLOW_NETWORK_FAILURE=${options.allowNetworkFailure ? "1" : "0"}).`,
    );
  } else if (category === "vulnerability") {
    console.error(`❌ npm audit gerçek ${options.level} veya üstü güvenlik bulgusu raporladı.`);
  } else {
    console.error(`❌ npm audit hata sınıflandırması belirsiz (failure_category=${category}).`);
  }
  console.error(`🧾 npm audit hata artefaktı yazıldı: ${failureArtifactPath}`);
  process.stdout.write(stdout);
  process.stderr.write(stderr);
  process.exit(effectiveExitCode);
}
