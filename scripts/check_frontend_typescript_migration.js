#!/usr/bin/env node
"use strict";

const { existsSync, readFileSync, readdirSync, statSync } = require("node:fs");
const { basename, extname, relative, resolve, sep } = require("node:path");

function isTestSource(path, sourceDir) {
  const relativePath = relative(sourceDir, path);
  const segments = relativePath.split(sep);
  const filename = basename(path);
  return (
    segments.some((segment) => ["test", "tests", "__tests__"].includes(segment)) ||
    /\.(test|spec)\.[cm]?[jt]sx?$/.test(filename)
  );
}

function countSourceExtensions(sourceDir) {
  const counts = { js: 0, jsx: 0, ts: 0, tsx: 0 };
  const untyped = { production: 0, test: 0 };
  const visit = (directory) => {
    for (const entry of readdirSync(directory)) {
      const path = resolve(directory, entry);
      if (statSync(path).isDirectory()) {
        visit(path);
        continue;
      }
      const extension = extname(entry).slice(1);
      if (Object.hasOwn(counts, extension)) {
        counts[extension] += 1;
        if (extension === "js" || extension === "jsx") {
          untyped[isTestSource(path, sourceDir) ? "test" : "production"] += 1;
        }
      }
    }
  };
  visit(sourceDir);
  return { counts, untyped };
}

function parseRoot(argv) {
  const rootArgument = argv.find((argument) => argument.startsWith("--root="));
  return resolve(rootArgument ? rootArgument.slice("--root=".length) : process.cwd());
}

function parseEvaluationDate(argv) {
  const dateArgument = argv.find((argument) => argument.startsWith("--date="));
  const value = dateArgument ? dateArgument.slice("--date=".length) : new Date().toISOString().slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error(`Invalid --date value: ${value}`);
  }
  return value;
}

const root = parseRoot(process.argv.slice(2));
const evaluationDate = parseEvaluationDate(process.argv.slice(2));
const sourceDir = resolve(root, "src");
const baselinePath = resolve(root, "typescript-migration-baseline.json");
if (!existsSync(sourceDir) || !existsSync(baselinePath)) {
  console.error(`TypeScript migration inventory inputs are missing under ${root}`);
  process.exit(2);
}

const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
if (
  !Number.isInteger(baseline.maximum_untyped_files) ||
  baseline.maximum_untyped_files < 0 ||
  (baseline.maximum_production_untyped_files !== undefined &&
    (!Number.isInteger(baseline.maximum_production_untyped_files) ||
      baseline.maximum_production_untyped_files < 0)) ||
  (baseline.maximum_test_untyped_files !== undefined &&
    (!Number.isInteger(baseline.maximum_test_untyped_files) ||
      baseline.maximum_test_untyped_files < 0)) ||
  !Number.isInteger(baseline.minimum_typed_files) ||
  baseline.minimum_typed_files < 0
) {
  console.error(`TypeScript migration baseline is invalid: ${baselinePath}`);
  process.exit(2);
}
const inventory = countSourceExtensions(sourceDir);
const counts = inventory.counts;
const untyped = counts.js + counts.jsx;
const typed = counts.ts + counts.tsx;
const productionUntyped = inventory.untyped.production;
const testUntyped = inventory.untyped.test;
const failures = [];
const milestones = Array.isArray(baseline.milestones) ? baseline.milestones : [];

if (untyped > baseline.maximum_untyped_files) {
  failures.push(
    `untyped source count increased: ${untyped} > ${baseline.maximum_untyped_files}`,
  );
}
if (typed < baseline.minimum_typed_files) {
  failures.push(`typed source count decreased: ${typed} < ${baseline.minimum_typed_files}`);
}
if (
  Number.isInteger(baseline.maximum_production_untyped_files) &&
  productionUntyped > baseline.maximum_production_untyped_files
) {
  failures.push(
    `production untyped source count increased: ${productionUntyped} > ${baseline.maximum_production_untyped_files}`,
  );
}
if (
  Number.isInteger(baseline.maximum_test_untyped_files) &&
  testUntyped > baseline.maximum_test_untyped_files
) {
  failures.push(
    `test untyped source count increased: ${testUntyped} > ${baseline.maximum_test_untyped_files}`,
  );
}
for (const milestone of milestones) {
  if (
    typeof milestone.deadline !== "string" ||
    !Number.isInteger(milestone.maximum_untyped_files) ||
    !Number.isInteger(milestone.minimum_typed_files)
  ) {
    console.error(`TypeScript migration milestone is invalid: ${JSON.stringify(milestone)}`);
    process.exit(2);
  }
  if (evaluationDate < milestone.deadline) {
    continue;
  }
  if (untyped > milestone.maximum_untyped_files) {
    failures.push(
      `${milestone.deadline} milestone missed: untyped=${untyped} > ${milestone.maximum_untyped_files}`,
    );
  }
  if (typed < milestone.minimum_typed_files) {
    failures.push(
      `${milestone.deadline} milestone missed: typed=${typed} < ${milestone.minimum_typed_files}`,
    );
  }
}

console.log(
  `Frontend TypeScript migration inventory (${evaluationDate}): js=${counts.js}, jsx=${counts.jsx}, ts=${counts.ts}, tsx=${counts.tsx}; untyped=${untyped}, production_untyped=${productionUntyped}, test_untyped=${testUntyped}, typed=${typed}`,
);
if (failures.length > 0) {
  for (const failure of failures) {
    console.error(`TypeScript migration ratchet failed: ${failure}`);
  }
  process.exit(1);
}
