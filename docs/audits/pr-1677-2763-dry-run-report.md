# Open PR triage dry-run: #1677–#2763

Snapshot time: **2026-09-16 UTC**. Repository: `niluferbagevi-gif/Sidar`.

## Safety contract

The triage classifications remain a **dry-run artifact**. A first controlled pass updated only #2706, #2737, #2768, #2793, #2795, #2796, and #2805 through GitHub's update-branch API. The authorized sequential merge operation merged #2805, initially stopped fail-closed on #2706's workflow-permission error, and then resumed after the fine-grained PAT received `Workflows: Read and write`. The resumed run merged #2706, #2737, #2768, #2793, and #2795 in order before stopping fail-closed because #2796 was conflicting/dirty. No pull request was closed, approved, or commented on. PRs #2739, #2794, and #2808 were not touched.

## Authentication and authorization

- `gh auth status`: authenticated to `github.com` as `niluferbagevi-gif`; active account; HTTPS Git protocol.
- `gh api user`: login `niluferbagevi-gif`, database id `253796649`.
- `gh repo view niluferbagevi-gif/Sidar --json nameWithOwner,viewerPermission`: `viewerPermission=ADMIN`.
- The initial repo-view call without `-R` failed because this checkout intentionally has no Git remote; the explicit repository call is authoritative.

## Reconciliation

The live query returned **279** open PRs overall. Exactly **272** are in the inclusive #1677–#2763 range; seven are newer than the range.

The earlier arithmetic covered only the **269 main-based PRs**: 234 close candidates plus approximately 35 human-review items. The three omitted PRs are stacked PRs whose base is not `main`: **#1942**, **#2069**, and **#2077**. Live GitHub data confirms that #2077 targets `codex/refactor-install_sidar.sh-into-modules`, whereas **#2696 targets `main`**. Therefore #2077—not #2696—is the third PR responsible for the numerical difference.

The numerical-difference set and the exclusive decision categories are separate dimensions. #1942 and #2069 are categorized as `UNCLEAR`; security-sensitive #2077 is categorized as `SECURITY` (which takes precedence over `UNCLEAR`) even though its non-`main` base is also recorded in the CSV. #2696 is an independent, `main`-based `UNCLEAR` item because it is a broad code-review analysis rather than a narrowly actionable change. Thus the `UNCLEAR` list correctly contains #1942, #2069, and #2696, while the three-PR reconciliation set correctly contains #1942, #2069, and #2077.

## Dry-run decision totals

| Category | Count | Dry-run action |
|---|---:|---|
| `CLOSE_CANDIDATE` | 234 | Would close only after explicit operator approval |
| `SECURITY` | 31 | Excluded; mandatory security review |
| `REAL_MISSING` | 4 | Excluded; refresh/validate the still-relevant dependency change |
| `UNCLEAR` | 3 | Excluded; stacked/non-main-base or broad semantic scope requires human review |
| **Total** | **272** | **No mutation performed** |

The machine-readable, row-by-row source of truth is [`pr-1677-2763-dry-run-manifest.csv`](pr-1677-2763-dry-run-manifest.csv).

## Programmatic integrity verification

The CSV was checked against a fresh live `OPEN` query, not only against the earlier snapshot:

- exactly 272 data rows and 272 unique PR numbers;
- exactly 234 `CLOSE_CANDIDATE`, 31 `SECURITY`, 4 `REAL_MISSING`, and 3 `UNCLEAR` rows;
- every pairwise category intersection is empty, including a zero intersection between `CLOSE_CANDIDATE` and every exclusion category;
- all 234 close candidates are still `OPEN` on GitHub and have `baseRefName=main`.

### Closure manifest (234)

#1677, #1705, #1707, #1710, #1711, #1725, #1732, #1737, #1752, #1781, #1782, #1784, #1785, #1795, #1796, #1847, #1853, #1858, #1863, #1864, #1865, #1866, #1869, #1871, #1873, #1887, #1913, #1914, #1919, #1922, #1924, #1925, #1926, #1927, #1929, #1935, #1940, #1941, #1943, #1944, #1945, #1946, #1947, #1949, #1952, #1955, #1959, #1961, #1962, #1963, #1964, #1972, #1973, #1975, #1976, #1977, #1979, #1986, #1987, #1988, #1991, #1993, #1997, #1998, #2000, #2002, #2009, #2017, #2020, #2022, #2029, #2033, #2047, #2050, #2051, #2052, #2053, #2055, #2065, #2067, #2068, #2071, #2073, #2075, #2081, #2083, #2084, #2085, #2088, #2094, #2096, #2097, #2103, #2107, #2115, #2116, #2121, #2127, #2130, #2146, #2152, #2158, #2167, #2168, #2169, #2170, #2175, #2176, #2180, #2184, #2188, #2191, #2192, #2193, #2194, #2195, #2196, #2197, #2198, #2199, #2200, #2201, #2202, #2203, #2208, #2210, #2214, #2217, #2219, #2220, #2223, #2226, #2227, #2229, #2233, #2236, #2237, #2242, #2243, #2245, #2246, #2253, #2259, #2262, #2263, #2264, #2267, #2280, #2286, #2287, #2288, #2289, #2290, #2294, #2307, #2316, #2317, #2318, #2323, #2331, #2332, #2333, #2334, #2335, #2340, #2343, #2349, #2350, #2352, #2355, #2365, #2370, #2372, #2375, #2376, #2377, #2378, #2379, #2380, #2394, #2411, #2412, #2415, #2431, #2437, #2447, #2450, #2451, #2457, #2459, #2461, #2466, #2468, #2483, #2484, #2485, #2486, #2489, #2499, #2500, #2506, #2508, #2511, #2523, #2546, #2548, #2553, #2558, #2568, #2570, #2572, #2574, #2575, #2579, #2591, #2593, #2600, #2602, #2603, #2604, #2625, #2626, #2627, #2650, #2658, #2665, #2678, #2680, #2686, #2693, #2753, #2754, #2757, #2763

### Excluded: security (31)

#1861, #1921, #1983, #1984, #2042, #2066, #2077, #2078, #2113, #2114, #2207, #2225, #2231, #2273, #2344, #2346, #2347, #2390, #2566, #2569, #2635, #2636, #2640, #2641, #2647, #2648, #2649, #2651, #2652, #2655, #2701

### Excluded: real missing (4)

#2420, #2706, #2737, #2739

### Excluded: unclear (3)

#1942, #2069, #2696

## Controlled update-branch result

Before the operation, all seven authorized PRs were `OPEN`, non-draft, based on `main`, `MERGEABLE`, `BEHIND`, and had no submitted `reviewDecision`. Each update used GitHub's `PUT /repos/niluferbagevi-gif/Sidar/pulls/{number}/update-branch` endpoint with the observed head SHA as `expected_head_sha`; no check was bypassed. GitHub accepted all seven requests with `Updating pull request branch.`

The workflow was then polled until all required checks completed. The common set of 11 required checks passed on every updated head: `PostgreSQL Connection Pool Stress Test`, `Production readiness aggregate`, `GPU Inference Required Evidence Gate`, `Required release checks audit`, `Installer manifest and smoke gate`, `Production-minimal runtime validation`, `migration-and-pool-checks`, `Production Compose runtime validation`, `Analyze (python)`, `Analyze (javascript-typescript)`, and `Base quality gates (lint, smoke, unit, coverage, frontend)`.

| PR | State | Draft | Base | Head SHA before → after | `mergeable` | `mergeStateStatus` | `reviewDecision` | Required checks | All checks |
|---|---|---|---|---|---|---|---|---|---|
| #2706 | `OPEN` | false | `main` | `e4726b6` → `f0277c4` | `MERGEABLE` | `CLEAN` | none | 11 passed | 15 success, 2 skipped, 0 failed/pending |
| #2737 | `OPEN` | false | `main` | `0ab78d7` → `dd91429` | `MERGEABLE` | `CLEAN` | none | 11 passed | 15 success, 2 skipped, 0 failed/pending |
| #2768 | `OPEN` | false | `main` | `2db8d02` → `81a0789` | `MERGEABLE` | `CLEAN` | none | 11 passed | 15 success, 2 skipped, 0 failed/pending |
| #2793 | `OPEN` | false | `main` | `aa00803` → `a874148` | `MERGEABLE` | `CLEAN` | none | 11 passed | 15 success, 2 skipped, 0 failed/pending |
| #2795 | `OPEN` | false | `main` | `82839c0` → `8e76c12` | `MERGEABLE` | `CLEAN` | none | 11 passed | 15 success, 2 skipped, 0 failed/pending |
| #2796 | `OPEN` | false | `main` | `1ebe239` → `4c8c4a8` | `MERGEABLE` | `CLEAN` | none | 11 passed | 15 success, 2 skipped, 0 failed/pending |
| #2805 | `OPEN` | false | `main` | `66cffeb` → `bdad082` | `MERGEABLE` | `CLEAN` | none | 11 passed | 16 success, 2 skipped, 0 failed/pending |

No merge was performed during that earlier update-only pass and no required check was bypassed. At the time of that pass, this session had not closed or commented on the 234 historical close candidates; a later, separately observed closure batch is reconciled below.

## Authorized sequential merge operation

Operation time: **2026-09-16 UTC**. Authorized order: #2805, #2706, #2737, #2768, #2793, #2795, #2796. Authentication was revalidated as `niluferbagevi-gif` with `ADMIN` repository permission. The repository's ordinary merge-commit method was used without `--admin` or any branch-protection/check bypass.

#2805 was re-evaluated from scratch after #2817 merged. It was `OPEN`, non-draft, based on `main`, `MERGEABLE`, and `BEHIND`, with no review decision. GitHub accepted an update-branch request protected by `expected_head_sha=bdad082feb38b0fe31a929bf4967282405c1b9fe`; the new head was `7008d3f79fa4fa3de4d429d4b903185fd91152d7`. Only checks attached to that new head were used. All 11 required checks passed, every observed check completed without failure/cancellation/timeout/action-required/stale status, and the final gate was `MERGEABLE` / `CLEAN`. #2805 was merged with the normal merge-commit method, producing `c0fc691853c4669bde66d653f4c12096ac26669b`; its final state is `MERGED`.

Main changed after that merge, so #2706 was re-evaluated from scratch. It remained `OPEN`, non-draft, based on `main`, `MERGEABLE`, and `BEHIND`, with head `f0277c42182c8db3ac6803925954cb5538992bad` and no review decision. Its required update-branch request was rejected with HTTP 403 because the active personal access token lacks the `workflow` scope needed to update `.github/workflows/release-quality.yml`. No new head was created, prior `CLEAN` or check results were not reused, and #2706 was not merged. Per the fail-closed stop rule, #2737, #2768, #2793, #2795, and #2796 were not processed or mutated.

| PR | Old head | New head | Update-branch result | Required checks used for merge | Merge method | Merge commit | Final result |
|---|---|---|---|---|---|---|---|
| #2805 | `bdad082feb38b0fe31a929bf4967282405c1b9fe` | `7008d3f79fa4fa3de4d429d4b903185fd91152d7` | accepted | 11/11 passed on new head; 0 bad/pending | merge commit (`--merge`, no `--admin`) | `c0fc691853c4669bde66d653f4c12096ac26669b` | `MERGED` |
| #2706 | `f0277c42182c8db3ac6803925954cb5538992bad` | none | rejected: HTTP 403, token lacks `workflow` scope | not reused/evaluated for merge | none | none | `OPEN`, `BEHIND`; operation stopped |
| #2737 | `dd91429fd6810c7726e27a03adaf93033ebc69ac` | none | not attempted after stop | not evaluated | none | none | `OPEN`; not processed |
| #2768 | `81a078967f5b4cb73620404f5f94f761f1d80809` | none | not attempted after stop | not evaluated | none | none | `OPEN`; not processed |
| #2793 | `a87414854cb2ee02ea3f9d2bce38223b0ae8089f` | none | not attempted after stop | not evaluated | none | none | `OPEN`; not processed |
| #2795 | `8e76c12b97bf863321c2baf2380e43e3b8bef0e1` | none | not attempted after stop | not evaluated | none | none | `OPEN`; not processed |
| #2796 | `4c8c4a8d66e359bb1a8f65f065f130ec16d4d368` | none | not attempted after stop | not evaluated | none | none | `OPEN`; not processed |

No required check or branch protection was bypassed. During this sequential-merge operation, #2739, #2794, #2808, and the 234 historical close candidates were not mutated or commented on. A later live audit found closure/comment mutations outside that operation, documented below.

## Resumed sequential merge operation

Resume time: **2026-09-16/17 UTC**. GitHub identity and `ADMIN` repository permission were revalidated, and the existing audit PR remained #2818. #2805 was not processed again. Each remaining PR was queried from scratch after the previous merge; no earlier `CLEAN` or check result was reused. Every accepted update-branch request used that fresh head as `expected_head_sha`, and every merge used `--match-head-commit` plus the repository's normal merge-commit method without `--admin`.

#2706's retry succeeded after the token permission change. #2706, #2737, #2768, #2793, and #2795 were each `OPEN`, non-draft, based on `main`, `MERGEABLE`, and `BEHIND` immediately before their protected update. For each new head, the exact 11 required-check names were matched, all 11 passed, all observed checks completed, and there were zero failed, cancelled, timed-out, action-required, stale, or pending checks before the final `MERGEABLE` / `CLEAN` gate and merge.

When its turn arrived, #2796 was freshly observed as `OPEN`, non-draft, based on `main`, with head `f3a185f9acb8820670f86de388a8417cbec09834` and no review decision. GitHub then resolved it as `CONFLICTING` / `DIRTY`. No update-branch request or merge was attempted for #2796, and the operation stopped fail-closed.

| PR | Fresh old head | Updated head | Update-branch | Required checks on updated head | All observed checks | Merge method | Merge commit | Final result |
|---|---|---|---|---|---|---|---|---|
| #2706 | `f0277c42182c8db3ac6803925954cb5538992bad` | `0d3b63ff9047783edad58acd8b8be461d2257b05` | accepted | 11/11 passed | 16 pass, 2 skipped, 0 bad/pending | merge commit; no `--admin` | `d39414a0c169cacec549740358be2eddf49ce8e5` | `MERGED` |
| #2737 | `dd91429fd6810c7726e27a03adaf93033ebc69ac` | `dbdc2768dd33232bfcacc43e246d3759ee86410c` | accepted | 11/11 passed | 16 pass, 2 skipped, 0 bad/pending | merge commit; no `--admin` | `a206094015333852bc4bb1f5c4fc759f569b77bc` | `MERGED` |
| #2768 | `81a078967f5b4cb73620404f5f94f761f1d80809` | `fa58d2cda05569a16051b756bf7bb267ae33efcd` | accepted | 11/11 passed | 16 pass, 2 skipped, 0 bad/pending | merge commit; no `--admin` | `502696a9cc896ca42c869fccf9d31edd765121a4` | `MERGED` |
| #2793 | `a87414854cb2ee02ea3f9d2bce38223b0ae8089f` | `e89ad45e0b39fbe67412a95b620908e31ba43270` | accepted | 11/11 passed | 16 pass, 2 skipped, 0 bad/pending | merge commit; no `--admin` | `7432cdcdf0f538a7a46675745614fd1a5368e844` | `MERGED` |
| #2795 | `9e2786a423b5d459a7bb6d896b06cf0d0638abda` | `d03b18ce2b3ea0c1d87735b4308e53d20da35446` | accepted | 11/11 passed | 15 pass, 2 skipped, 0 bad/pending | merge commit; no `--admin` | `5cca39732d22eec6e886664ec47e3a1f8a1a5692` | `MERGED` |
| #2796 | `f3a185f9acb8820670f86de388a8417cbec09834` | none | not attempted: `CONFLICTING` / `DIRTY` | not evaluated/reused | not evaluated/reused | none | none | `OPEN`; operation stopped |

No required check or branch protection was bypassed. During the resumed sequential-merge operation, #2739, #2794, #2808, and the 234 historical close candidates were not mutated or commented on. This result was committed to the existing #2818 audit branch; no new audit PR was created.

## Emergency live closure reconciliation

Reconciliation time: **2026-09-17 UTC**. Before any write in this reconciliation task, the manifest was read directly from `main` and all 272 manifest PRs were queried in bulk through GitHub GraphQL. The live repository query returned 38 open PRs overall (the observed 37 plus the still-open #2818 audit PR). The immutable input remained 234 `CLOSE_CANDIDATE`, 31 `SECURITY`, 4 `REAL_MISSING`, and 3 `UNCLEAR` records.

The candidate-by-candidate result is stored in [`pr-1677-2763-live-reconciliation.csv`](pr-1677-2763-live-reconciliation.csv). It records state, merged flag, `closedAt`, `updatedAt`, the latest pre-close reason-comment author/time/URL, close actor/time, and reconciliation result for every one of the 234 candidates.

### Close-candidate result

- **211** of 234 close candidates are `CLOSED`; all 211 have `merged=false`.
- Every one of those 211 has a substantive reason comment authored by `niluferbagevi-gif` no later than `closedAt`, followed by a `ClosedEvent` attributed to `niluferbagevi-gif`. All 211 comments carry a `Generated by Claude Code` footer.
- The 211 close events span **2026-09-16T23:38:09Z–23:43:39Z**.
- **23** candidates were skipped and remain `OPEN`: #1711, #1737, #1929, #1940, #1941, #2065, #2083, #2085, #2088, #2130, #2175, #2180, #2217, #2219, #2317, #2412, #2461, #2489, #2506, #2508, #2548, #2658, and #2763.
- Candidate anomalies are **0**: none of the 211 closed candidates was merged, missing a pre-close reason comment, closed before its reason comment, or closed by an unexpected actor.

Example reason comments: [#1677](https://github.com/niluferbagevi-gif/Sidar/pull/1677#issuecomment-5706147062), [#2000](https://github.com/niluferbagevi-gif/Sidar/pull/2000#issuecomment-5706159496), [#2200](https://github.com/niluferbagevi-gif/Sidar/pull/2200#issuecomment-5706157923), [#2411](https://github.com/niluferbagevi-gif/Sidar/pull/2411#issuecomment-5706171837), [#2415](https://github.com/niluferbagevi-gif/Sidar/pull/2415#issuecomment-5706172402), and [#2500](https://github.com/niluferbagevi-gif/Sidar/pull/2500#issuecomment-5706182499).

### Exclusion anomalies

The live results contradict the earlier exclusion safety expectation:

- **25 of 31 `SECURITY` PRs were closed without merge** by `niluferbagevi-gif`: #1861, #1921, #1983, #1984, #2042, #2066, #2077, #2078, #2113, #2114, #2225, #2231, #2273, #2344, #2346, #2347, #2569, #2635, #2636, #2647, #2648, #2649, #2651, #2655, and #2701. Their close events span **2026-09-16T23:38:34Z–23:43:43Z**. The six still open are #2207, #2390, #2566, #2640, #2641, and #2652. Example: [#2648 reason comment](https://github.com/niluferbagevi-gif/Sidar/pull/2648#issuecomment-5706199052).
- All three `UNCLEAR` PRs—#1942, #2069, and #2696—were closed without merge, rather than remaining open. Their close events span **2026-09-16T23:40:10Z–23:43:29Z**, with pre-close reason comments and close events attributed to `niluferbagevi-gif`.
- These **28 exclusion closures** are the anomaly set. Combined with the 211 intended candidate closures, the manifest now contains 239 closed-without-merge PRs.

### REAL_MISSING verification

- #2706 and #2737 are `MERGED` by the authorized sequential operation.
- #2739 remains `OPEN`, unmerged, with no close/merge timeline event.
- The fourth entry, #2420, remains `OPEN`, unmerged, with no close/merge timeline event.

### Attribution boundary

GitHub timeline data attributes all 239 close events to the `niluferbagevi-gif` account. The reason comments are also authored by that account and contain a `Generated by Claude Code` footer. The 23:38–23:43 UTC closure window overlaps the separately recorded sequential-merge check-waiting window, and this reconciliation task issued no close, reopen, merge, comment, or update request. This is evidence of a distinct automated activity using the same GitHub account, but GitHub PR timeline data does not expose the originating token, process, or session; it is therefore not sufficient to identify a specific parallel task more precisely.

## Exclusion-remediation preflight — blocked

Preflight time: **2026-09-17 UTC**. The source manifest was read directly from `main`, and `pr-1677-2763-live-reconciliation.csv` was read directly from the existing #2818 branch before any PR write. The manifest still defines 31 `SECURITY` and 3 `UNCLEAR` records, but the reconciliation CSV contains only the 234 `CLOSE_CANDIDATE` rows. It therefore contains no `SECURITY` or `UNCLEAR` row marked `ANOMALY`.

The authorization predicate—manifest category `SECURITY`/`UNCLEAR`, reconciliation state `CLOSED`, `merged=false`, close actor `niluferbagevi-gif`, and reconciliation result `ANOMALY`—produced **0 unique PRs**, not the mandatory 28. The expected set from the report was #1861, #1921, #1942, #1983, #1984, #2042, #2066, #2069, #2077, #2078, #2113, #2114, #2225, #2231, #2273, #2344, #2346, #2347, #2569, #2635, #2636, #2647, #2648, #2649, #2651, #2655, #2696, and #2701, but none can satisfy the CSV-membership condition because those rows are absent from that file.

Per the mandatory fail-closed rule, the remediation stopped before live per-PR state checks and before any reopen/comment request. Exact result: **0 reopened, 0 idempotently skipped, 0 reopen failures, 28 blocked by preflight data mismatch**. No reopen-result columns were added to the CSV because no authorized remediation operation began. The six already-open security PRs (#2207, #2390, #2566, #2640, #2641, #2652), all `REAL_MISSING` and `CLOSE_CANDIDATE` PRs, #2739, #2794, #2808, #2796, and #2818 were not mutated.

## Reconciliation CSV coverage repair

Repair time: **2026-09-17 UTC**. This data-only repair made no PR state, comment, review, or merge mutation. The category/action/base/title/URL fields came exclusively from the 272-row manifest on `main`; all 272 unique PRs were re-queried through GitHub GraphQL. The previously verified evidence for the original 234 `CLOSE_CANDIDATE` rows was preserved, while all 31 `SECURITY`, 4 `REAL_MISSING`, and 3 `UNCLEAR` rows were added.

The repaired [`pr-1677-2763-live-reconciliation.csv`](pr-1677-2763-live-reconciliation.csv) now has 272 data rows and 272 unique PR numbers. Its deterministic category/result cross-table is:

| Manifest category | Reconciliation result | Count |
|---|---|---:|
| `CLOSE_CANDIDATE` | `CLOSED_VERIFIED` | 211 |
| `CLOSE_CANDIDATE` | `SKIPPED_OPEN` | 23 |
| `SECURITY` | `EXCLUSION_ANOMALY_CLOSED` | 25 |
| `SECURITY` | `EXCLUDED_OPEN` | 6 |
| `UNCLEAR` | `EXCLUSION_ANOMALY_CLOSED` | 3 |
| `REAL_MISSING` | `AUTHORIZED_MERGED` | 2 |
| `REAL_MISSING` | `EXCLUDED_OPEN` | 2 |
| all categories | `UNEXPECTED_ANOMALY` | 0 |

The exact `EXCLUSION_ANOMALY_CLOSED` set is 28 unique PRs: #1861, #1921, #1942, #1983, #1984, #2042, #2066, #2069, #2077, #2078, #2113, #2114, #2225, #2231, #2273, #2344, #2346, #2347, #2569, #2635, #2636, #2647, #2648, #2649, #2651, #2655, #2696, and #2701. All count and exact-set invariants passed; no remediation/reopen action was performed in this task.

## Exclusion anomaly remediation

Remediation time: **2026-09-17T01:02:16Z–01:04:53Z**. The 272-row reconciliation CSV was read directly from the existing #2818 head, and its strict predicate produced the exact authorized 28-PR set. A read-only GraphQL preflight confirmed all 28 were `CLOSED`, `merged=false`, and categorized only as `SECURITY` or `UNCLEAR`.

Each PR was checked again immediately before mutation, reopened with the normal `gh pr reopen` path without `--admin`, force, or bypass, and verified `OPEN`/unmerged before exactly one category-specific correction comment was written. No reopen, verification, or comment call failed; no PR was idempotently skipped. Exact operation result: **28 reopened, 0 skipped, 0 failed**.

A post-operation GraphQL verification confirmed all **31 `SECURITY` PRs are `OPEN` and unmerged** and all **3 `UNCLEAR` PRs are `OPEN` and unmerged**. The CSV retains the historical `EXCLUSION_ANOMALY_CLOSED` value while adding `remediation_action`, `remediation_result`, `reopened_at`, and `correction_comment_url`; the current `live_state` for the remediated rows is now `OPEN`. No `CLOSE_CANDIDATE`, `REAL_MISSING`, protected PR, review, merge, or close operation was performed.

| PR | Category | Reopened at | Correction comment | Result |
|---|---|---|---|---|
| #1861 | `SECURITY` | `2026-09-17T01:02:16Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/1861#issuecomment-5706824481) | `SUCCESS` |
| #1921 | `SECURITY` | `2026-09-17T01:02:21Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/1921#issuecomment-5706825243) | `SUCCESS` |
| #1942 | `UNCLEAR` | `2026-09-17T01:02:27Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/1942#issuecomment-5706825956) | `SUCCESS` |
| #1983 | `SECURITY` | `2026-09-17T01:02:33Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/1983#issuecomment-5706826676) | `SUCCESS` |
| #1984 | `SECURITY` | `2026-09-17T01:02:39Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/1984#issuecomment-5706827400) | `SUCCESS` |
| #2042 | `SECURITY` | `2026-09-17T01:02:45Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2042#issuecomment-5706828140) | `SUCCESS` |
| #2066 | `SECURITY` | `2026-09-17T01:02:50Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2066#issuecomment-5706828810) | `SUCCESS` |
| #2069 | `UNCLEAR` | `2026-09-17T01:02:56Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2069#issuecomment-5706829624) | `SUCCESS` |
| #2077 | `SECURITY` | `2026-09-17T01:03:02Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2077#issuecomment-5706830318) | `SUCCESS` |
| #2078 | `SECURITY` | `2026-09-17T01:03:07Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2078#issuecomment-5706831094) | `SUCCESS` |
| #2113 | `SECURITY` | `2026-09-17T01:03:13Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2113#issuecomment-5706831738) | `SUCCESS` |
| #2114 | `SECURITY` | `2026-09-17T01:03:18Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2114#issuecomment-5706832413) | `SUCCESS` |
| #2225 | `SECURITY` | `2026-09-17T01:03:25Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2225#issuecomment-5706833204) | `SUCCESS` |
| #2231 | `SECURITY` | `2026-09-17T01:03:31Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2231#issuecomment-5706833945) | `SUCCESS` |
| #2273 | `SECURITY` | `2026-09-17T01:03:37Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2273#issuecomment-5706834688) | `SUCCESS` |
| #2344 | `SECURITY` | `2026-09-17T01:03:42Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2344#issuecomment-5706835408) | `SUCCESS` |
| #2346 | `SECURITY` | `2026-09-17T01:03:48Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2346#issuecomment-5706836150) | `SUCCESS` |
| #2347 | `SECURITY` | `2026-09-17T01:03:54Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2347#issuecomment-5706836935) | `SUCCESS` |
| #2569 | `SECURITY` | `2026-09-17T01:04:00Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2569#issuecomment-5706837805) | `SUCCESS` |
| #2635 | `SECURITY` | `2026-09-17T01:04:06Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2635#issuecomment-5706838573) | `SUCCESS` |
| #2636 | `SECURITY` | `2026-09-17T01:04:11Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2636#issuecomment-5706839287) | `SUCCESS` |
| #2647 | `SECURITY` | `2026-09-17T01:04:17Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2647#issuecomment-5706840030) | `SUCCESS` |
| #2648 | `SECURITY` | `2026-09-17T01:04:23Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2648#issuecomment-5706840795) | `SUCCESS` |
| #2649 | `SECURITY` | `2026-09-17T01:04:29Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2649#issuecomment-5706841399) | `SUCCESS` |
| #2651 | `SECURITY` | `2026-09-17T01:04:35Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2651#issuecomment-5706842247) | `SUCCESS` |
| #2655 | `SECURITY` | `2026-09-17T01:04:41Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2655#issuecomment-5706842882) | `SUCCESS` |
| #2696 | `UNCLEAR` | `2026-09-17T01:04:47Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2696#issuecomment-5706843631) | `SUCCESS` |
| #2701 | `SECURITY` | `2026-09-17T01:04:53Z` | [comment](https://github.com/niluferbagevi-gif/Sidar/pull/2701#issuecomment-5706844392) | `SUCCESS` |

## Explicit no-merge guard

- #2739: left open/unmerged; current checks include 4 failures, 5 skipped, and 8 successes; `MERGEABLE` / `BEHIND`; no review decision.
- #2794: left open/unmerged; current checks include 4 failures, 5 skipped, and 10 successes; `MERGEABLE` / `BEHIND`; no review decision.
- #2808: left open/unmerged; current checks include 4 failures, 5 skipped, and 8 successes; `MERGEABLE` / `BEHIND`; no review decision.
