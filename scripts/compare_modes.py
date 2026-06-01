#!/usr/bin/env python3
"""
Compare CENTRALIZED vs DISTRIBUTED coordination (the thesis's core axis), on the
real emulation testbed.

Both arms run the identical robots/agents/workload and the same LF Coordinator
logic; the only difference is topology:
  * distributed: N coordinator replicas (one federate per robot) + gossip
    -- aggregated by report.py into <distributed>/testbed_metrics_agg.csv
  * centralized: ONE federate serves all N robots
    -- aggregated into <central>/testbed_metrics_agg.csv

This isolates the single variable (1 coordinator vs N replicas) and lets the
emulation reproduce the sim's central-vs-distributed comparison on real ROS2/LF
infrastructure.

Writes:
    results/modes_comparison.md     (per-N both modes + delta table)
    results/modes_comparison.tex    (LaTeX tabular)
    figures/testbed/modes_compare.{pdf,png}

Usage:
    python3 scripts/compare_modes.py --distributed results --central results/central
"""

import argparse
import csv
import os

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def load_agg(d):
    path = os.path.join(d, "testbed_metrics_agg.csv")
    if not os.path.exists(path):
        raise SystemExit(f"missing aggregate: {path} (run the sweep + report.py first)")
    rows = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            n = int(float(r["num_robots"]))
            rows[n] = {k: (float(v) if v not in ("", None) else 0.0)
                       for k, v in r.items() if k != "num_robots"}
            rows[n]["num_robots"] = n
    return rows


def pm(mean, sd, prec=2):
    return f"{mean:.{prec}f} ± {sd:.{prec}f}" if sd and sd > 0 else f"{mean:.{prec}f}"


def write_markdown(ns, dist, cen, out, tag=""):
    path = os.path.join(out, f"modes_comparison{tag}.md")
    L = ["# Context-Fabric testbed: centralized vs distributed coordination", "",
         "The two Ch.3 architectures on identical robots / workload / `Coordinator` code: "
         "**distributed** = a coordinator replica (federate) per robot + inter-robot gossip; "
         "**centralized** = one shared coordinator serving the whole fleet, with **no inter-robot "
         "gossip** (hence no AoI). Values are mean ± sd across seeds.", "",
         "## Per-N, both modes", "",
         "| N | mode | Completion | Throughput (tasks/min) | Avg lat (s) | Util | "
         "T_claim (ms) | AoI (ms) |",
         "|---|---|---|---|---|---|---|---|"]

    def row(n, label, s):
        return (f"| {n} | {label} | {pm(s['completion_rate_mean'], s['completion_rate_sd'])} | "
                f"{pm(60*s['throughput_tps_mean'], 60*s['throughput_tps_sd'], 2)} | "
                f"{pm(s['avg_latency_s_mean'], s['avg_latency_s_sd'], 0)} | "
                f"{pm(s['agent_utilization_mean'], s['agent_utilization_sd'])} | "
                f"{pm(s['t_claim_ms_mean_mean'], s['t_claim_ms_mean_sd'], 1)} | "
                f"{'n/a' if s['aoi_ms_mean_mean'] == 0 else pm(s['aoi_ms_mean_mean'], s['aoi_ms_mean_sd'], 1)} |")

    for n in ns:
        L.append(row(n, "distributed", dist[n]))
        L.append(row(n, "centralized", cen[n]))

    L += ["", "## Coordinator-contention delta (centralized − distributed)", "",
          "| N | Δ T_claim (ms) | Δ Completion | Δ Avg lat (s) | Δ Util |",
          "|---|---|---|---|---|"]
    for n in ns:
        d, c = dist[n], cen[n]
        L.append(
            f"| {n} | {c['t_claim_ms_mean_mean']-d['t_claim_ms_mean_mean']:+.1f} | "
            f"{c['completion_rate_mean']-d['completion_rate_mean']:+.2f} | "
            f"{c['avg_latency_s_mean']-d['avg_latency_s_mean']:+.1f} | "
            f"{c['agent_utilization_mean']-d['agent_utilization_mean']:+.2f} |")

    parity = [n for n in ns if abs(cen[n]['completion_rate_mean'] - dist[n]['completion_rate_mean']) < 0.1
              and dist[n]['t_claim_ms_mean_mean'] < 500 and cen[n]['t_claim_ms_mean_mean'] < 500]
    dist_bad = [n for n in ns if dist[n]['t_claim_ms_mean_mean'] >= 500 or dist[n]['completion_rate_mean'] < 0.5]
    cen_bad = [n for n in ns if cen[n]['t_claim_ms_mean_mean'] >= 500 or cen[n]['completion_rate_mean'] < 0.5]
    L += ["", "## What it shows",
          "- Identical robots, workload and `Coordinator` code; the arms differ only in the two "
          "Ch.3 design choices -- **N replicas + gossip** (distributed) vs **one central "
          "coordinator, no gossip** (centralized)."]
    if parity:
        L.append(f"- **Comparable at N = {', '.join(map(str, parity))}**: completion, latency and "
                 f"claim overhead are within noise between the two -- at these fleet sizes the single "
                 f"coordinator is not yet a bottleneck, and the distributed replicas add no measurable "
                 f"penalty.")
    for n in dist_bad:
        L.append(f"- **At N = {n} the _distributed_ arm degrades** (completion "
                 f"{dist[n]['completion_rate_mean']:.0%}, T_claim {dist[n]['t_claim_ms_mean_mean']:.0f} ms) "
                 f"while centralized holds ({cen[n]['completion_rate_mean']:.0%}, "
                 f"{cen[n]['t_claim_ms_mean_mean']:.0f} ms): Context-Fabric's all-to-all LF proposal mesh "
                 f"(replicated, strongly-consistent task state) hits its centralized-RTI control-plane "
                 f"limit here, which a single federate has no reason to. **On raw service metrics at "
                 f"workstation scale, centralized matches or exceeds distributed.**")
    for n in cen_bad:
        L.append(f"- **At N = {n} the _centralized_ arm degrades** (completion "
                 f"{cen[n]['completion_rate_mean']:.0%}, T_claim {cen[n]['t_claim_ms_mean_mean']:.0f} ms): "
                 f"the single coordinator saturates; the distributed replicas do not.")
    L += ["- **The distributed architecture's advantage is not small-N raw metrics** but (i) **fault "
          "tolerance** -- no single point of failure (the coordinator-kill test), and (ii) **very-"
          "large-N scaling**, where the central node finally saturates (the simulation regime, far "
          "beyond one workstation). This emulation, capped at modest N, shows service-metric parity "
          "and exposes a control-plane cost in the current distributed implementation.",
          "- **Baseline caveat -- the centralized arm is a _single_ coordinator, the _idealized_ best "
          "case.** One coordinator has the minimum possible coordination latency (no "
          "replication/consensus overhead) and is a single point of failure. A production centralized "
          "coordinator (ZooKeeper/etcd/Chubby-style) would replicate via consensus (Raft/ZAB), "
          "_adding_ latency. So this pits distributed against the _most favorable_ centralized case; a "
          "realistically replicated coordinator would only widen the distributed architecture's "
          "relative standing."]
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    return path


def write_latex(ns, dist, cen, out, tag=""):
    path = os.path.join(out, f"modes_comparison{tag}.tex")
    L = ["% Auto-generated by scripts/compare_modes.py -- paste into the thesis.",
         r"\begin{table}[ht]", r"    \centering", r"    \small",
         r"    \renewcommand{\arraystretch}{1.15}", r"    \setlength{\tabcolsep}{5pt}",
         r"    \begin{tabular}{rl ccc cc}", r"        \hline",
         r"        $N$ & Coord. & Compl. & $T_{\text{claim}}$ & AoI & Avg lat. & Util. \\",
         r"            &        & (\%)   & (ms)               & (ms)& (s)      & (\%)  \\",
         r"        \hline"]

    def row(n, label, s):
        return (f"        {n} & {label} & "
                f"{pm(100*s['completion_rate_mean'], 100*s['completion_rate_sd'], 0)} & "
                f"{pm(s['t_claim_ms_mean_mean'], s['t_claim_ms_mean_sd'], 1)} & "
                f"{'n/a' if s['aoi_ms_mean_mean'] == 0 else pm(s['aoi_ms_mean_mean'], s['aoi_ms_mean_sd'], 1)} & "
                f"{pm(s['avg_latency_s_mean'], s['avg_latency_s_sd'], 0)} & "
                f"{pm(100*s['agent_utilization_mean'], 100*s['agent_utilization_sd'], 0)} "
                r"\\").replace("±", r"$\pm$")

    for n in ns:
        L.append(row(n, "distrib.", dist[n]))
        L.append(row(n, "central", cen[n]))
        if n != ns[-1]:
            L.append(r"        \hline")
    L += [r"        \hline", r"    \end{tabular}",
          r"    \caption[Centralized vs distributed coordination]{Centralized vs distributed "
          r"coordination on the emulation testbed (identical robots/workload/coordinator "
          r"logic; topology is the only variable). $T_{\text{claim}}$ is the coordinator "
          r"round-trip; a single central coordinator serializes the fleet's claims.}",
          r"    \label{tab:testbed_modes}", r"\end{table}"]
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    return path


def make_figure(ns, dist, cen, figs, tag=""):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"  [figure skipped: matplotlib unavailable: {e}]")
        return []
    os.makedirs(figs, exist_ok=True)
    plt.rcParams.update({"font.size": 15})

    def mean(rows, key):
        return [rows[n][f"{key}_mean"] for n in ns]

    fig, ax = plt.subplots(2, 2, figsize=(10, 7.4))
    # the same four metrics the thesis simulation reports, for both modes.
    # Metric goes in the y-axis label; no titles, no grid, no error bars.
    panels = [
        (ax[0, 0], "completion_rate", "Completion rate (%)", 100.0),
        (ax[0, 1], "throughput_tps", "Throughput (tasks/min)", 60.0),
        (ax[1, 0], "avg_latency_s", "Task latency (s)", 1.0),
        (ax[1, 1], "agent_utilization", "Utilization (% working)", 100.0),
    ]
    handles = []
    for a, key, ylab, scale in panels:
        l1, = a.plot(ns, [scale*x for x in mean(dist, key)], "o-", linewidth=2.4,
                     markersize=9, label="distributed")
        l2, = a.plot(ns, [scale*x for x in mean(cen, key)], "s--", linewidth=2.4,
                     markersize=9, color="tab:red", label="centralized")
        handles = [l1, l2]
        a.set_xlabel("robots N", fontsize=16)
        a.set_ylabel(ylab, fontsize=16)
        a.set_xticks(ns)
        a.tick_params(labelsize=14)
        if scale == 100.0:
            a.set_ylim(0, 105)
    # one shared legend for the whole figure (not one per panel)
    fig.legend(handles, ["distributed", "centralized"], loc="upper center",
               ncol=2, fontsize=15, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    saved = []
    for ext in ("pdf", "png"):
        p = os.path.join(figs, f"modes_compare{tag}.{ext}")
        fig.savefig(p, bbox_inches="tight", dpi=150); saved.append(p)
    plt.close(fig)
    return saved


def main():
    ap = argparse.ArgumentParser(description="Compare centralized vs distributed coordination")
    ap.add_argument("--distributed", default=os.path.join(REPO, "results"))
    ap.add_argument("--central", default=os.path.join(REPO, "results", "central"))
    ap.add_argument("--out", default=os.path.join(REPO, "results"))
    ap.add_argument("--figs", default=os.path.join(REPO, "figures", "testbed"))
    ap.add_argument("--max-n", type=int, default=0,
                    help="cap the comparison at N<=max-n (e.g. 8); 0 = all overlapping N")
    args = ap.parse_args()

    dist, cen = load_agg(args.distributed), load_agg(args.central)
    ns = sorted(set(dist) & set(cen))
    if args.max_n:
        ns = [n for n in ns if n <= args.max_n]
    tag = f"_n{args.max_n}" if args.max_n else ""
    if not ns:
        raise SystemExit("no overlapping fleet sizes between distributed and central aggregates")
    missing = sorted(set(dist) ^ set(cen))
    if missing:
        print(f"  [note: N not in both modes, skipped: {missing}]")
    os.makedirs(args.out, exist_ok=True)
    print(f"  {write_markdown(ns, dist, cen, args.out, tag)}")
    print(f"  {write_latex(ns, dist, cen, args.out, tag)}")
    for p in make_figure(ns, dist, cen, args.figs, tag):
        print(f"  {p}")
    print(f"\nCompared N={ns} (distributed vs centralized).")


if __name__ == "__main__":
    main()
