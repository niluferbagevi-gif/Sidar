# Open PR triage dry-run: #1677–#2763

Snapshot time: **2026-09-16 UTC**. Repository: `niluferbagevi-gif/Sidar`.

## Safety contract

The triage classifications remain a **dry-run artifact**. In the later controlled update-branch pass, only #2706, #2737, #2768, #2793, #2795, #2796, and #2805 were updated through GitHub's update-branch API. No pull request was closed, merged, approved, or commented on, and no PR was changed beyond those seven branch updates. PRs #2739, #2794, and #2808 were not touched.

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

No merge was performed. No required check was bypassed. The 234 historical close candidates were neither closed nor commented on.

## Explicit no-merge guard

- #2739: left open/unmerged; current checks include 4 failures, 5 skipped, and 8 successes; `MERGEABLE` / `BEHIND`; no review decision.
- #2794: left open/unmerged; current checks include 4 failures, 5 skipped, and 10 successes; `MERGEABLE` / `BEHIND`; no review decision.
- #2808: left open/unmerged; current checks include 4 failures, 5 skipped, and 8 successes; `MERGEABLE` / `BEHIND`; no review decision.
