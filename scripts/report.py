#!/usr/bin/env python3
"""
Aggregate Context-Fabric emulation runs into thesis-ready artifacts.

Multi-seed aware: groups runs by fleet size N and reports mean +/- sd across
seeds. Reads:
  logs/summary_<config>_seed<seed>.json          (one per N x seed)
  logs/run_<config>_seed<seed>/claim_robot*.csv  (T_claim samples, ms)
  logs/run_<config>_seed<seed>/aoi_robot*.csv     (AoI samples, ms)

Writes:
  results/testbed_metrics.csv       (per-seed rows)
  results/testbed_metrics_agg.csv   (per-N: mean + sd across seeds)
  results/testbed_table.md          (markdown table, mean +/- sd)
  results/testbed_table.tex         (LaTeX tabular, thesis style)
  results/README.md                 (narrative + Ch.3 symbol mapping)
  figures/testbed/metrics_vs_n.{pdf,png}        (4 metrics vs N, error bars)
  figures/testbed/claim_overhead_vs_n.{pdf,png}
  figures/testbed/aoi_distribution.{pdf,png}

Tables need numpy; figures need matplotlib (run via a conda python).
"""

import csv
import glob
import json
import math
import os
from collections import defaultdict

import numpy as np

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
LOGS = os.path.join(REPO, "logs")
RESULTS = os.path.join(REPO, "results")
FIGS = os.path.join(REPO, "figures", "testbed")


def pct(arr, q):
    return float(np.percentile(arr, q)) if len(arr) else 0.0


def load_overhead(config_name, seed):
    run_dir = os.path.join(LOGS, f"run_{config_name}_seed{seed}")
    claims, aoi = [], []
    for fn in glob.glob(os.path.join(run_dir, "claim_robot*.csv")):
        with open(fn) as f:
            for row in csv.reader(f):
                if len(row) >= 2 and row[0] == "claim":
                    try:
                        claims.append(float(row[1]))
                    except ValueError:
                        pass
    for fn in glob.glob(os.path.join(run_dir, "aoi_robot*.csv")):
        with open(fn) as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    try:
                        aoi.append(float(row[1]))
                    except ValueError:
                        pass
    return claims, aoi


def load_runs():
    """One dict per (N, seed) run, with overhead attached."""
    runs = []
    for s in sorted(glob.glob(os.path.join(LOGS, "summary_*.json"))):
        with open(s) as f:
            d = json.load(f)
        claims, aoi = load_overhead(d["config_name"], d["seed"])
        d["t_claim_ms_mean"] = round(float(np.mean(claims)), 2) if claims else 0.0
        d["t_claim_ms_p95"] = round(pct(claims, 95), 2)
        d["aoi_ms_mean"] = round(float(np.mean(aoi)), 1) if aoi else 0.0
        d["aoi_ms_p95"] = round(pct(aoi, 95), 1)
        d["_claims"], d["_aoi"] = claims, aoi
        runs.append(d)
    return runs


# metrics aggregated across seeds (per N)
AGG_KEYS = [
    "completion_rate", "throughput_tps", "avg_latency_s", "p50_latency_s",
    "p90_latency_s", "p99_latency_s", "agent_utilization",
    "t_claim_ms_mean", "aoi_ms_mean", "tasks_completed", "tasks_created",
]


def mean_sd(vals):
    if not vals:
        return 0.0, 0.0
    m = float(np.mean(vals))
    s = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
    return m, s


def aggregate(runs):
    """Group per-seed runs by N -> {N: {key: (mean, sd), 'seeds': [...], ...}}."""
    by_n = defaultdict(list)
    for r in runs:
        by_n[r["num_robots"]].append(r)
    agg = []
    for n in sorted(by_n):
        group = by_n[n]
        row = {"num_robots": n, "n_seeds": len(group),
               "seeds": sorted(g["seed"] for g in group)}
        for k in AGG_KEYS:
            row[k + "_mean"], row[k + "_sd"] = mean_sd([g.get(k, 0.0) for g in group])
        row["_group"] = group
        agg.append(row)
    return agg


def write_per_seed_csv(runs):
    cols = ["config_name", "num_robots", "seed", "tasks_created", "tasks_completed",
            "tasks_failed", "completion_rate", "throughput_tps", "avg_latency_s",
            "p50_latency_s", "p90_latency_s", "p99_latency_s", "agent_utilization",
            "t_claim_ms_mean", "t_claim_ms_p95", "aoi_ms_mean", "aoi_ms_p95"]
    path = os.path.join(RESULTS, "testbed_metrics.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(runs, key=lambda r: (r["num_robots"], r["seed"])):
            w.writerow({k: r.get(k, "") for k in cols})
    return path


def write_agg_csv(agg):
    path = os.path.join(RESULTS, "testbed_metrics_agg.csv")
    cols = ["num_robots", "n_seeds"] + [f"{k}_{stat}" for k in AGG_KEYS for stat in ("mean", "sd")]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in agg:
            w.writerow({c: round(row[c], 4) if isinstance(row.get(c), float) else row.get(c, "")
                        for c in cols})
    return path


def pm(mean, sd, prec=2):
    """Format 'mean +/- sd' (omit sd if a single seed / zero)."""
    if sd and sd > 0:
        return f"{mean:.{prec}f} ± {sd:.{prec}f}"
    return f"{mean:.{prec}f}"


def write_markdown(agg, n_seeds):
    path = os.path.join(RESULTS, "testbed_table.md")
    lines = ["# Context-Fabric testbed: emulated N-robot results", "",
             f"Real ROS2 + Lingua Franca federation (one federate per robot), Poisson task "
             f"stream, robot policy (state machine). Values are mean ± sd over {n_seeds} seeds.",
             "",
             "| N | Completion | Throughput (tps) | Avg lat (s) | P90 lat (s) | Utilization | "
             "T_claim mean (ms) | AoI mean (ms) |",
             "|---|---|---|---|---|---|---|---|"]
    for r in agg:
        lines.append(
            f"| {r['num_robots']} | {pm(r['completion_rate_mean'], r['completion_rate_sd'])} | "
            f"{pm(r['throughput_tps_mean'], r['throughput_tps_sd'], 3)} | "
            f"{pm(r['avg_latency_s_mean'], r['avg_latency_s_sd'], 0)} | "
            f"{pm(r['p90_latency_s_mean'], r['p90_latency_s_sd'], 0)} | "
            f"{pm(r['agent_utilization_mean'], r['agent_utilization_sd'])} | "
            f"{pm(r['t_claim_ms_mean_mean'], r['t_claim_ms_mean_sd'], 1)} | "
            f"{pm(r['aoi_ms_mean_mean'], r['aoi_ms_mean_sd'], 1)} |")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def write_latex(agg, n_seeds):
    path = os.path.join(RESULTS, "testbed_table.tex")
    lines = [
        "% Auto-generated by scripts/report.py -- paste into the thesis.",
        r"\begin{table}[ht]", r"    \centering", r"    \small",
        r"    \renewcommand{\arraystretch}{1.15}", r"    \setlength{\tabcolsep}{5pt}",
        r"    \begin{tabular}{rccccccc}", r"        \hline",
        r"        $N$ & Compl. & Thrpt. & Avg lat. & P90 lat. & Util. & "
        r"$T_{\text{claim}}$ & AoI \\",
        r"            & (\%)   & (tps)  & (s)      & (s)      & (\%)  & (ms) & (ms) \\",
        r"        \hline",
    ]
    for r in agg:
        lines.append(
            f"        {r['num_robots']} & {pm(100*r['completion_rate_mean'], 100*r['completion_rate_sd'], 0)} & "
            f"{pm(r['throughput_tps_mean'], r['throughput_tps_sd'], 3)} & "
            f"{pm(r['avg_latency_s_mean'], r['avg_latency_s_sd'], 0)} & "
            f"{pm(r['p90_latency_s_mean'], r['p90_latency_s_sd'], 0)} & "
            f"{pm(100*r['agent_utilization_mean'], 100*r['agent_utilization_sd'], 0)} & "
            f"{pm(r['t_claim_ms_mean_mean'], r['t_claim_ms_mean_sd'], 1)} & "
            f"{pm(r['aoi_ms_mean_mean'], r['aoi_ms_mean_sd'], 1)} \\\\".replace("±", r"$\pm$"))
    lines += [
        r"        \hline", r"    \end{tabular}",
        r"    \caption[Emulated testbed results]{Context-Fabric testbed on real ROS2 + "
        rf"Lingua Franca, one federate per emulated robot (mean $\pm$ sd over {n_seeds} seeds). "
        r"$T_{\text{claim}}$ is the measured ROS$\to$LF$\to$RTI claim round-trip; AoI is mean "
        r"data-plane gossip staleness.}",
        r"    \label{tab:testbed_results}", r"\end{table}",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def make_figures(agg):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"  [figures skipped: matplotlib unavailable: {e}]")
        return []
    os.makedirs(FIGS, exist_ok=True)
    ns = [r["num_robots"] for r in agg]
    saved = []

    def errs(key):
        return ([r[f"{key}_mean"] for r in agg], [r[f"{key}_sd"] for r in agg])

    def save(fig, name):
        for ext in ("pdf", "png"):
            p = os.path.join(FIGS, f"{name}.{ext}")
            fig.savefig(p, bbox_inches="tight", dpi=150); saved.append(p)
        plt.close(fig)

    # Fig 1: four metrics vs N with error bars.
    fig, ax = plt.subplots(2, 2, figsize=(9.5, 6.8))
    cr_m, cr_s = errs("completion_rate")
    ax[0, 0].errorbar(ns, [100*m for m in cr_m], yerr=[100*s for s in cr_s], fmt="o-", capsize=3)
    ax[0, 0].set(title="Completion rate", xlabel="robots N", ylabel="%"); ax[0, 0].set_ylim(0, 105)
    th_m, th_s = errs("throughput_tps")
    ax[0, 1].errorbar(ns, th_m, yerr=th_s, fmt="o-", color="tab:green", capsize=3)
    ax[0, 1].set(title="Throughput", xlabel="robots N", ylabel="tasks/s")
    la_m, la_s = errs("avg_latency_s"); p9_m, p9_s = errs("p90_latency_s")
    ax[1, 0].errorbar(ns, la_m, yerr=la_s, fmt="o-", color="tab:orange", capsize=3, label="avg")
    ax[1, 0].errorbar(ns, p9_m, yerr=p9_s, fmt="s--", color="tab:red", capsize=3, label="P90")
    ax[1, 0].set(title="Task latency (create->complete)", xlabel="robots N", ylabel="s"); ax[1, 0].legend()
    u_m, u_s = errs("agent_utilization")
    ax[1, 1].errorbar(ns, [100*m for m in u_m], yerr=[100*s for s in u_s], fmt="o-", color="tab:purple", capsize=3)
    ax[1, 1].set(title="Robot utilization", xlabel="robots N", ylabel="% time working"); ax[1, 1].set_ylim(0, 105)
    fig.suptitle(f"Context-Fabric testbed: metrics vs fleet size (mean±sd, {agg[0]['n_seeds']} seeds)")
    fig.tight_layout(); save(fig, "metrics_vs_n")

    # Fig 2: claim overhead vs N (mean across seeds, sd error bars).
    tc_m, tc_s = errs("t_claim_ms_mean")
    fig, axx = plt.subplots(figsize=(6, 4))
    axx.errorbar(ns, tc_m, yerr=tc_s, fmt="o-", capsize=3)
    axx.set(title=r"Claim overhead $T_{claim}$ vs fleet size", xlabel="robots N",
            ylabel="claim round-trip (ms)"); axx.grid(True, alpha=0.3)
    save(fig, "claim_overhead_vs_n")

    # Fig 3: pooled AoI distribution at the largest N (all seeds).
    big = agg[-1]
    pooled = [v for g in big["_group"] for v in g["_aoi"]]
    if pooled:
        fig, axx = plt.subplots(figsize=(6, 4))
        axx.hist(pooled, bins=40, color="tab:gray", edgecolor="k", alpha=0.8)
        axx.axvline(300, color="tab:red", ls="--", label="300 ms gossip period")
        axx.set(title=f"Data-plane AoI (gossip staleness), N={big['num_robots']}",
                xlabel="age of information (ms)", ylabel="count"); axx.legend()
        save(fig, "aoi_distribution")
    return saved


def write_readme(agg, n_seeds):
    path = os.path.join(RESULTS, "README.md")
    lo, hi = agg[0], agg[-1]
    thr_ratio = (hi["throughput_tps_mean"] / lo["throughput_tps_mean"]) if lo["throughput_tps_mean"] else 0.0
    n_ratio = (hi["num_robots"] / lo["num_robots"]) if lo["num_robots"] else 0.0
    lat_means = [r["avg_latency_s_mean"] for r in agg]
    aoi_max = max(r["aoi_ms_mean_mean"] for r in agg)
    compl_min = min(r["completion_rate_mean"] for r in agg)
    # Separate the cleanly-coordinating range from any centralized-coordination
    # ceiling (claim latency blows up / completion collapses at large N).
    clean = [r for r in agg if r["t_claim_ms_mean_mean"] < 500 and r["completion_rate_mean"] >= 0.6]
    ceiling = [r for r in agg if r["t_claim_ms_mean_mean"] >= 500 or r["completion_rate_mean"] < 0.5]
    lines = [
        "# Context-Fabric testbed results",
        "",
        f"Quantitative validation of the federated coordination architecture, emulating "
        f"**one Lingua Franca federate per robot** in Docker. Tasks arrive as a Poisson stream; "
        f"the robot **policy is a state machine**. Values below are **mean ± sd over "
        f"{n_seeds} seeds** ({', '.join(str(s) for s in lo['seeds'])}).",
        "",
        "## Metric definitions (match the thesis simulation)",
        "- **Completion rate** = completed / created   - **Throughput** = completed / wall-second",
        "- **Latency** = create->complete (avg/P50/P90/P99 s)   - **Utilization** = per-robot %WORKING, fleet-avg",
        "- **T_claim** = ROS->LF->RTI claim round-trip (ms)   - **AoI** = data-plane gossip staleness (ms)",
        "",
        "## Results",
        "",
        "| N | Completion | Throughput | Avg/P90 lat (s) | Util | T_claim (ms) | AoI (ms) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in agg:
        lines.append(
            f"| {r['num_robots']} | {pm(r['completion_rate_mean'], r['completion_rate_sd'])} | "
            f"{pm(r['throughput_tps_mean'], r['throughput_tps_sd'], 3)} | "
            f"{pm(r['avg_latency_s_mean'], r['avg_latency_s_sd'], 0)}/"
            f"{pm(r['p90_latency_s_mean'], r['p90_latency_s_sd'], 0)} | "
            f"{pm(r['agent_utilization_mean'], r['agent_utilization_sd'])} | "
            f"{pm(r['t_claim_ms_mean_mean'], r['t_claim_ms_mean_sd'], 1)} | "
            f"{pm(r['aoi_ms_mean_mean'], r['aoi_ms_mean_sd'], 1)} |")
    lines += ["", "## What the data shows"]
    if clean:
        cl_hi = clean[-1]
        lines += [
            f"- **Coordination stays cheap through N={cl_hi['num_robots']}**: completion "
            f"{cl_hi['completion_rate_mean']:.0%}, claim overhead "
            f"{clean[0]['t_claim_ms_mean_mean']:.1f}->{cl_hi['t_claim_ms_mean_mean']:.1f} ms, "
            f"AoI <= {max(r['aoi_ms_mean_mean'] for r in clean):.1f} ms (<< 300 ms gossip period) -- "
            f"all far below the ~75 s task service time.",
            f"- **Latency bounded** in this range (avg "
            f"{min(r['avg_latency_s_mean'] for r in clean):.0f}-"
            f"{max(r['avg_latency_s_mean'] for r in clean):.0f} s); throughput grows with the fleet.",
        ]
    for c in ceiling:
        lines.append(
            f"- **Centralized-coordination ceiling at N={c['num_robots']}**: claim latency rises to "
            f"~{c['t_claim_ms_mean_mean']:.0f} ms and completion falls to {c['completion_rate_mean']:.0%}. "
            f"Under LF centralized coordination every federate's tag advance is gated by an all-to-all "
            f"barrier, so logical time cannot track real time at this scale. The latency is tunable via "
            f"the connection `after` grant-horizon, but the breakdown is the measured scaling frontier and "
            f"motivates decentralized coordination (future work).")
    lines += [
        "",
        "## Artifacts",
        "- `results/testbed_metrics.csv` (per-seed) and `results/testbed_metrics_agg.csv` (per-N mean/sd)",
        "- `results/testbed_table.md` / `.tex` (drop-in tables)",
        "- `figures/testbed/metrics_vs_n.*`, `claim_overhead_vs_n.*`, `aoi_distribution.*`",
        "- `figures/testbed/architecture_*.{png,svg,pdf}` (architecture diagrams)",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def main():
    global LOGS, RESULTS, FIGS
    import argparse
    ap = argparse.ArgumentParser(description="Aggregate testbed runs into tables + figures")
    ap.add_argument("--logs-dir", default=LOGS)
    ap.add_argument("--results-dir", default=RESULTS)
    ap.add_argument("--figs-dir", default=FIGS)
    args = ap.parse_args()
    LOGS, RESULTS, FIGS = args.logs_dir, args.results_dir, args.figs_dir

    os.makedirs(RESULTS, exist_ok=True)
    runs = load_runs()
    if not runs:
        print(f"No summary_*.json in {LOGS}/. Run scripts/run_sweep.sh first.")
        return
    agg = aggregate(runs)
    n_seeds = max(r["n_seeds"] for r in agg)
    print(f"  {write_per_seed_csv(runs)}")
    print(f"  {write_agg_csv(agg)}")
    print(f"  {write_markdown(agg, n_seeds)}")
    print(f"  {write_latex(agg, n_seeds)}")
    print(f"  {write_readme(agg, n_seeds)}")
    for p in make_figures(agg):
        print(f"  {p}")
    print(f"\nAggregated N={[r['num_robots'] for r in agg]} over up to {n_seeds} seeds.")


if __name__ == "__main__":
    main()
