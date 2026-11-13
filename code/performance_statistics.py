"""Statistics over the existing runtime measurements (no database needed).

1. Task 3: least-squares line of mean execution time against sales rows for each query,
   giving the marginal cost per 100,000 sales and the fit quality (R^2) over the five sizes,
   plus the runtime change between stages 1->2 and 4->5 next to the sales and distance-pair changes.
2. Task 4: exact two-sided permutation test for every baseline-vs-index comparison.
   With five runs per side there are C(10,5) = 252 ways to split the ten timings, so the
   smallest attainable p-value is 2/252 = 0.0079. No distributional assumption is needed.

Output: results/performance_statistics.json (cited in Sections 3.2.3 and 4.2 of the report).
"""
from itertools import combinations
from pathlib import Path
from statistics import mean
import csv
import json

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'results'


def read(name):
    with (RESULTS / name).open(encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def linear_fit(xs, ys):
    """Ordinary least squares y = a + b x; returns slope, intercept and R^2."""
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    intercept = my - slope * mx
    residual = sum((y - intercept - slope * x) ** 2 for x, y in zip(xs, ys))
    total = sum((y - my) ** 2 for y in ys)
    return slope, intercept, 1 - residual / total


def change(before, after):
    """Percentage change from `before` to `after`, one decimal."""
    return round(100 * (after / before - 1), 1)


def permutation_p(a, b):
    """Exact two-sided permutation p-value for the difference in means of samples a and b."""
    pooled = a + b
    observed = abs(mean(a) - mean(b))
    extreme = splits = 0
    for chosen in combinations(range(len(pooled)), len(a)):
        first = [pooled[i] for i in chosen]
        second = [pooled[i] for i in range(len(pooled)) if i not in chosen]
        splits += 1
        if abs(mean(first) - mean(second)) >= observed - 1e-9:
            extreme += 1
    return extreme / splits


def main():
    baseline = read('baseline_measurements.csv')
    queries = sorted({row['query'] for row in baseline})

    growth = []
    for query in queries:
        points = {}
        for row in baseline:
            if row['query'] == query:
                points.setdefault(int(row['transaction_rows']), []).append(float(row['execution_ms']))
        xs = sorted(points)
        ys = [mean(points[x]) for x in xs]
        slope, intercept, r2 = linear_fit(xs, ys)
        growth.append(dict(query=query, ms_per_100k_sales=round(slope * 100_000, 2),
                           intercept_ms=round(intercept, 2), r_squared=round(r2, 4),
                           growth_factor=round(ys[-1] / ys[0], 2), sales_factor=round(xs[-1] / xs[0], 2)))

    # Stage-to-stage growth: stage 2 adds few sales but many distance pairs, stage 5 the reverse.
    sizes = {}
    for row in baseline:
        sizes[int(row['stage'])] = int(row['transaction_rows'])
    plan = json.loads((ROOT / 'data/prepared/load_plan.json').read_text())
    pairs = {stage['stage']: stage['cumulative_rows']['block_hawker_distance'] for stage in plan}
    stage_means = {(int(r['stage']), r['query']): [] for r in baseline}
    for row in baseline:
        stage_means[(int(row['stage']), row['query'])].append(float(row['execution_ms']))
    increments = []
    for before, after in [(1, 2), (4, 5)]:
        increments.append(dict(
            stages=f'{before}->{after}', sales_change_percent=change(sizes[before], sizes[after]),
            distance_pair_change_percent=change(pairs[before], pairs[after]),
            runtime_change_percent={q: change(mean(stage_means[(before, q)]), mean(stage_means[(after, q)]))
                                    for q in queries}))

    full = {q: [float(r['execution_ms']) for r in baseline if r['query'] == q and r['stage'] == '5']
            for q in queries}
    combined = []
    for query in queries:
        after = [float(r['execution_ms']) for r in read('indexed_measurements.csv') if r['query'] == query]
        combined.append(dict(query=query, baseline_mean_ms=round(mean(full[query]), 2),
                             indexed_mean_ms=round(mean(after), 2),
                             permutation_p=round(permutation_p(full[query], after), 4)))
    isolated = []
    for row_group in sorted({(r['phase'], r['query']) for r in read('index_individual_measurements.csv')}):
        phase, query = row_group
        alone = [float(r['execution_ms']) for r in read('index_individual_measurements.csv')
                 if r['phase'] == phase and r['query'] == query]
        isolated.append(dict(index=phase, query=query, baseline_mean_ms=round(mean(full[query]), 2),
                             index_alone_mean_ms=round(mean(alone), 2),
                             permutation_p=round(permutation_p(full[query], alone), 4)))
    result = dict(minimum_attainable_p=round(2 / 252, 4), growth=growth, stage_increments=increments,
                  combined_indexes=combined, isolated_indexes=isolated)
    (RESULTS / 'performance_statistics.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
