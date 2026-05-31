#!/bin/bash
# =============================================================================
# Context-Fabric emulation sweep (multi-seed).
#
# For each fleet size N and each seed: bring up an N-robot LF federation in
# Docker, drive a reproducible Poisson task stream, drain, tear down.
# metrics_node writes logs/summary_<config>_seed<seed>.json; report.py
# aggregates mean +/- sd across seeds into results/ + figures/testbed/.
#
# Usage:
#   scripts/run_sweep.sh                    # sizes/seeds/duration from config
#   scripts/run_sweep.sh "2" 60             # smoke: N=2, 60 s (config seeds)
#   SEEDS="42" scripts/run_sweep.sh "2 8" 240   # override seeds via env
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO"

PY=python3
cfg() { "$PY" scripts/cfg.py "$1"; }

SIZES="${1:-$(cfg fleet_sizes)}"
DURATION="${2:-$(cfg run.duration_s)}"
SEEDS="${SEEDS:-$(cfg run.seeds)}"
WARMUP="$(cfg run.warmup_s)"
RATE_PR="$(cfg tasks.arrival_rate_per_robot)"
WORK_S="$(cfg timing.work_time_s)"
MODE="$(cfg mode)"
IMAGE=context-fabric-fed
DRAIN="$("$PY" -c "print(int(2*float('$WORK_S')))")"
RATE_MULT="${RATE_MULT:-1}"          # multiply lambda to stress-test load (#3)
LABEL="${LABEL:-}"                    # tag a pass into its own dirs (e.g. load/netem)

if [ -n "$LABEL" ]; then
    OUTLOGS="logs/$LABEL"; OUTRES="results/$LABEL"; OUTFIG="figures/testbed/$LABEL"
else
    OUTLOGS="logs"; OUTRES="results"; OUTFIG="figures/testbed"
fi
mkdir -p "$OUTLOGS" "$OUTRES" "$OUTFIG" logs

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo ">>> Building $IMAGE (first run; compiles LF federations 2,4,8,16) ..."
    docker build -f Dockerfile.fed -t "$IMAGE" .
fi

echo ">>> Sweep: sizes=[$SIZES] seeds=[$SEEDS] duration=${DURATION}s warmup=${WARMUP}s drain=${DRAIN}s mode=$MODE"

for N in $SIZES; do
    CONFIG="${MODE}_${N}robots"
    COMPOSE="docker-compose.${N}.yml"
    "$PY" scripts/gen_compose.py "$N"
    LAMBDA="$("$PY" -c "print(round(float('$RATE_PR')*$N*float('$RATE_MULT'), 4))")"

    for SEED in $SEEDS; do
        echo ""
        echo "================ N=$N  seed=$SEED  ($CONFIG) ================"
        export CF_SEED="$SEED"                       # -> metrics summary filename
        rm -f logs/claim_robot*.csv logs/aoi_robot*.csv

        docker compose -f "$COMPOSE" down -v --remove-orphans >/dev/null 2>&1 || true
        docker compose -f "$COMPOSE" up -d

        echo "  warmup ${WARMUP}s ..."
        sleep "$WARMUP"

        echo "  spawning Poisson lambda=${LAMBDA}/s for ${DURATION}s (seed $SEED) ..."
        docker compose -f "$COMPOSE" exec -T metrics bash -c \
            "source /ros2_ws/install/setup.bash && python3 /ros2_ws/scripts/task_spawner.py \
             --rate ${LAMBDA} --duration ${DURATION} --seed ${SEED} \
             --service /robot_1/coord/create_task" || echo "  (spawner exited non-zero)"

        echo "  draining ${DRAIN}s ..."
        sleep "$DRAIN"

        # Archive this (N, seed) run's overhead logs.
        run_dir="${OUTLOGS}/run_${CONFIG}_seed${SEED}"
        mkdir -p "$run_dir"
        mv logs/claim_robot*.csv logs/aoi_robot*.csv "$run_dir/" 2>/dev/null || true

        docker compose -f "$COMPOSE" down -v --remove-orphans >/dev/null 2>&1 || true
        # For a labeled pass, move summary/timeseries into the pass dir.
        if [ -n "$LABEL" ]; then
            mv "logs/summary_${CONFIG}_seed${SEED}.json" \
               "logs/timeseries_${CONFIG}_seed${SEED}.csv" "$OUTLOGS/" 2>/dev/null || true
        fi
        echo "  done -> ${OUTLOGS}/summary_${CONFIG}_seed${SEED}.json"
    done
done

echo ""
echo "=== aggregating results (mean +/- sd across seeds) ==="
REPORT_PY=python3
for cand in "$HOME/miniconda3/envs/habitat_test/bin/python" "$HOME/miniconda3/envs/behavior/bin/python" "$HOME/miniconda3/bin/python" python3; do
    if "$cand" -c "import matplotlib, numpy" >/dev/null 2>&1; then REPORT_PY="$cand"; break; fi
done
echo "  report python: $REPORT_PY"
"$REPORT_PY" scripts/report.py --logs-dir "$OUTLOGS" --results-dir "$OUTRES" --figs-dir "$OUTFIG" \
    || echo "  report.py failed (tables need numpy, figures need matplotlib)"

echo ""
echo "Done. Tables in results/, figures in figures/testbed/."
