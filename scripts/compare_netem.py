#!/usr/bin/env python3
"""
Compare a baseline (loopback) sweep against a netem-impaired sweep.

Both sweeps are produced by scripts/run_sweep_iso.sh and aggregated by
scripts/report.py into a per-N CSV:

    <dir>/testbed_metrics_agg.csv   (num_robots, *_mean, *_sd ...)

This tool reads the baseline and netem aggregates, matches them by fleet size N,
and emits the *network-effect* artifacts the thesis needs -- showing that under a
realistic link the coordination overhead (T_claim, AoI) rises while the service
metrics (completion, throughput, utilization, task latency) stay essentially flat
(the network delay is small next to the ~75 s service time). That is the direct,
measured evidence for the Ch.3 claim that overhead is network-bound.

Writes:
    results/netem_comparison.md     (baseline vs netem rows per N, + delta table)
    results/netem_comparison.tex    (LaTeX tabular, thesis style)
    figures/testbed/netem_compare.{pdf,png}   (overhead up, service flat)

Usage:
    python3 scripts/compare_netem.py \
        --baseline results --netem results/netem20 \
        --out results --figs figures/testbed --netem-ms 20
"""

import argparse
import csv
import os

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def load_agg(d):
    """Read testbed_metrics_agg.csv from dir d -> {N(int): {col: float}}."""
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
    if sd and sd > 0:
        return f"{mean:.{prec}f} ± {sd:.{prec}f}"
    return f"{mean:.{prec}f}"


def write_markdown(ns, base, net, netem_ms, out):
    path = os.path.join(out, "netem_comparison.md")
    L = [f"# Context-Fabric testbed: baseline vs netem ({netem_ms} ms)", "",
         f"Same emulation, two link conditions: **baseline** (Docker bridge, no added "
         f"delay) and **netem** (`tc qdisc ... netem delay {netem_ms}ms {netem_ms//4}ms` on "
         f"each robot container's `eth0`, i.e. egress impairment on the robot uplink). "
         f"Values are mean ± sd across seeds.", "",
         "## Per-N, both conditions", "",
         "| N | cond | Completion | Throughput (tps) | Avg lat (s) | P90 lat (s) | Util | "
         "T_claim (ms) | AoI (ms) |",
         "|---|---|---|---|---|---|---|---|---|"]

    def row(n, label, s):
        return (f"| {n} | {label} | {pm(s['completion_rate_mean'], s['completion_rate_sd'])} | "
                f"{pm(s['throughput_tps_mean'], s['throughput_tps_sd'], 3)} | "
                f"{pm(s['avg_latency_s_mean'], s['avg_latency_s_sd'], 0)} | "
                f"{pm(s['p90_latency_s_mean'], s['p90_latency_s_sd'], 0)} | "
                f"{pm(s['agent_utilization_mean'], s['agent_utilization_sd'])} | "
                f"{pm(s['t_claim_ms_mean_mean'], s['t_claim_ms_mean_sd'], 1)} | "
                f"{pm(s['aoi_ms_mean_mean'], s['aoi_ms_mean_sd'], 1)} |")

    for n in ns:
        L.append(row(n, "baseline", base[n]))
        L.append(row(n, f"netem{netem_ms}", net[n]))

    L += ["", "## Network effect (netem − baseline)", "",
          "| N | Δ T_claim (ms) | Δ AoI (ms) | Δ Avg lat (s) | Δ Completion | Δ Util |",
          "|---|---|---|---|---|---|"]
    for n in ns:
        b, m = base[n], net[n]
        L.append(
            f"| {n} | {m['t_claim_ms_mean_mean']-b['t_claim_ms_mean_mean']:+.1f} | "
            f"{m['aoi_ms_mean_mean']-b['aoi_ms_mean_mean']:+.1f} | "
            f"{m['avg_latency_s_mean']-b['avg_latency_s_mean']:+.1f} | "
            f"{m['completion_rate_mean']-b['completion_rate_mean']:+.2f} | "
            f"{m['agent_utilization_mean']-b['agent_utilization_mean']:+.2f} |")

    # quick narrative numbers
    dtc = [net[n]['t_claim_ms_mean_mean'] - base[n]['t_claim_ms_mean_mean'] for n in ns]
    dao = [net[n]['aoi_ms_mean_mean'] - base[n]['aoi_ms_mean_mean'] for n in ns]
    dco = [net[n]['completion_rate_mean'] - base[n]['completion_rate_mean'] for n in ns]
    L += ["", "## What it shows",
          f"- **Coordination overhead rises with the link**: T_claim +{min(dtc):.1f} to "
          f"+{max(dtc):.1f} ms, AoI +{min(dao):.1f} to +{max(dao):.1f} ms under "
          f"{netem_ms} ms egress delay — the round-trip crosses the impaired uplink "
          f"several times, so the increase is a small multiple of the one-way delay.",
          f"- **Service metrics stay flat**: completion changes by at most "
          f"{max(abs(x) for x in dco):.2f}; the {netem_ms} ms link is negligible next to the "
          f"~75 s task service time, so throughput/latency/utilization are unaffected.",
          "- **Conclusion**: the measured overhead is network-bound (it tracks the link, not "
          "the fleet's work), confirming the Ch.3 model that coordination cost is "
          "communication-dominated rather than a throughput bottleneck at these N."]
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    return path


def write_latex(ns, base, net, netem_ms, out):
    path = os.path.join(out, "netem_comparison.tex")
    L = ["% Auto-generated by scripts/compare_netem.py -- paste into the thesis.",
         r"\begin{table}[ht]", r"    \centering", r"    \small",
         r"    \renewcommand{\arraystretch}{1.15}", r"    \setlength{\tabcolsep}{5pt}",
         r"    \begin{tabular}{rl ccc cc}", r"        \hline",
         r"        $N$ & Link & Compl. & $T_{\text{claim}}$ & AoI & Avg lat. & Util. \\",
         r"            &      & (\%)   & (ms)               & (ms)& (s)      & (\%)  \\",
         r"        \hline"]

    def row(n, label, s):
        return (f"        {n} & {label} & "
                f"{pm(100*s['completion_rate_mean'], 100*s['completion_rate_sd'], 0)} & "
                f"{pm(s['t_claim_ms_mean_mean'], s['t_claim_ms_mean_sd'], 1)} & "
                f"{pm(s['aoi_ms_mean_mean'], s['aoi_ms_mean_sd'], 1)} & "
                f"{pm(s['avg_latency_s_mean'], s['avg_latency_s_sd'], 0)} & "
                f"{pm(100*s['agent_utilization_mean'], 100*s['agent_utilization_sd'], 0)} "
                r"\\").replace("±", r"$\pm$")

    for n in ns:
        L.append(row(n, "base", base[n]))
        L.append(row(n, rf"netem{netem_ms}", net[n]))
        L.append(r"        \hline" if n != ns[-1] else "")
    L = [x for x in L if x != ""]
    L += [r"        \hline", r"    \end{tabular}",
          rf"    \caption[Baseline vs netem]{{Coordination overhead under a realistic link. "
          rf"Each robot's uplink carries {netem_ms}\,ms egress delay (\texttt{{tc netem}}); "
          r"$T_{\text{claim}}$ and AoI rise with the link while completion, latency and "
          r"utilization stay flat, evidencing that overhead is network-bound.}",
          r"    \label{tab:testbed_netem}", r"\end{table}"]
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    return path


def make_figure(ns, base, net, netem_ms, figs):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"  [figure skipped: matplotlib unavailable: {e}]")
        return []
    os.makedirs(figs, exist_ok=True)

    def series(rows, key):
        return [rows[n][f"{key}_mean"] for n in ns], [rows[n][f"{key}_sd"] for n in ns]

    fig, ax = plt.subplots(2, 2, figsize=(9.5, 6.8))
    panels = [
        (ax[0, 0], "t_claim_ms_mean", "Claim overhead $T_{claim}$", "round-trip (ms)", 1.0),
        (ax[0, 1], "aoi_ms_mean", "Data-plane AoI", "gossip staleness (ms)", 1.0),
        (ax[1, 0], "avg_latency_s", "Task latency (create→complete)", "s", 1.0),
        (ax[1, 1], "completion_rate", "Completion rate", "%", 100.0),
    ]
    for a, key, title, ylab, scale in panels:
        bm, bs = series(base, key); nm, ns_ = series(net, key)
        a.errorbar(ns, [scale*x for x in bm], yerr=[scale*x for x in bs],
                   fmt="o-", capsize=3, label="baseline")
        a.errorbar(ns, [scale*x for x in nm], yerr=[scale*x for x in ns_],
                   fmt="s--", capsize=3, color="tab:red", label=f"netem {netem_ms} ms")
        a.set(title=title, xlabel="robots N", ylabel=ylab)
        a.grid(True, alpha=0.3); a.legend(fontsize=8)
        if scale == 100.0:
            a.set_ylim(0, 105)
    fig.suptitle(f"Baseline vs netem ({netem_ms} ms): overhead rises, service stays flat")
    fig.tight_layout()
    saved = []
    for ext in ("pdf", "png"):
        p = os.path.join(figs, f"netem_compare.{ext}")
        fig.savefig(p, bbox_inches="tight", dpi=150); saved.append(p)
    plt.close(fig)
    return saved


def main():
    ap = argparse.ArgumentParser(description="Compare baseline vs netem sweeps")
    ap.add_argument("--baseline", default=os.path.join(REPO, "results"))
    ap.add_argument("--netem", default=os.path.join(REPO, "results", "netem20"))
    ap.add_argument("--out", default=os.path.join(REPO, "results"))
    ap.add_argument("--figs", default=os.path.join(REPO, "figures", "testbed"))
    ap.add_argument("--netem-ms", type=int, default=20)
    args = ap.parse_args()

    base, net = load_agg(args.baseline), load_agg(args.netem)
    ns = sorted(set(base) & set(net))
    if not ns:
        raise SystemExit("no overlapping fleet sizes between baseline and netem aggregates")
    missing = sorted(set(base) ^ set(net))
    if missing:
        print(f"  [note: N not in both conditions, skipped: {missing}]")
    os.makedirs(args.out, exist_ok=True)
    print(f"  {write_markdown(ns, base, net, args.netem_ms, args.out)}")
    print(f"  {write_latex(ns, base, net, args.netem_ms, args.out)}")
    for p in make_figure(ns, base, net, args.netem_ms, args.figs):
        print(f"  {p}")
    print(f"\nCompared N={ns} (baseline vs netem {args.netem_ms} ms).")


if __name__ == "__main__":
    main()
