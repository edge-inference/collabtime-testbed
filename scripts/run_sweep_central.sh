#!/bin/bash
# =============================================================================
# CENTRALIZED-coordination baseline sweep (for the central-vs-distributed study).
#
# Builds ONE shared LF federate (coordinator_1) and points N robots at it, so a
# single central coordinator serves the whole fleet -- same robots/agents/metrics
# /workload as run_sweep_iso.sh (the distributed Context-Fabric), differing only
# in coordination topology (1 coordinator vs N replicas). Same metric defs, so
# results/central/ is directly comparable to results/ (distributed).
#
# Usage:
#   scripts/run_sweep_central.sh "2 4 8 16" 240
#   NETEM_MS=20 scripts/run_sweep_central.sh "2 4 8" 240    # impaired link
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"; cd "$REPO"
export PATH="$HOME/.local/bin:$PATH"

PY=python3
cfg() { "$PY" scripts/cfg.py "$1"; }
SIZES="${1:-$(cfg fleet_sizes)}"
DURATION="${2:-$(cfg run.duration_s)}"
SEEDS="${SEEDS:-$(cfg run.seeds)}"
WARMUP="$("$PY" -c "print(max(25, $(cfg run.warmup_s)))")"
RATE_PR="$(cfg tasks.arrival_rate_per_robot)"
WORK_S="$(cfg timing.work_time_s)"
DRAIN="$("$PY" -c "print(int(2*float('$WORK_S')))")"
NETEM_MS="${NETEM_MS:-0}"

OUTLOGS="logs/central"; OUTRES="results/central"; OUTFIG="figures/testbed/central"
mkdir -p "$OUTLOGS" "$OUTRES" "$OUTFIG" logs

docker image inspect context-fabric-fed >/dev/null 2>&1 || docker build -f Dockerfile.fed -t context-fabric-fed .

echo ">>> CENTRAL sweep: sizes=[$SIZES] seeds=[$SEEDS] dur=${DURATION}s drain=${DRAIN}s netem=${NETEM_MS}ms"

# Build the single shared central federate ONCE (1 federate serves every N).
echo "######## building 1-federate central coordinator (coordinator_1) ########"
rm -rf "fed-gen/coordinator_1"
"$PY" scripts/gen_lf.py --sizes 1 --docker --compile >/dev/null 2>&1
LFC="fed-gen/coordinator_1/src-gen/docker-compose.yml"
docker compose -f "$LFC" build >/dev/null 2>&1 && echo "  central federate image built"

for N in $SIZES; do
    echo ""; echo "######## CENTRAL N=$N robots -> 1 federate ########"
    "$PY" scripts/gen_compose_central.py "$N" >/dev/null
    ROSC="docker-compose.central.${N}.yml"
    LAMBDA="$("$PY" -c "print(round(float('$RATE_PR')*$N, 4))")"

    for SEED in $SEEDS; do
        CONFIG="central_${N}robots"
        echo "==== N=$N seed=$SEED ===="
        export CF_SEED="$SEED"
        rm -f logs/claim_robot*.csv logs/aoi_robot*.csv
        docker compose -f "$LFC" -f "$ROSC" down -v --remove-orphans >/dev/null 2>&1 || true
        docker compose -f "$LFC" -f "$ROSC" up -d >/dev/null 2>&1
        sleep "$WARMUP"

        if [ "$NETEM_MS" -gt 0 ]; then
            for i in $(seq 1 "$N"); do
                docker exec "cf_robot${i}" tc qdisc add dev eth0 root netem delay "${NETEM_MS}ms" "$((NETEM_MS/4))ms" 2>/dev/null || true
            done
            echo "  applied ${NETEM_MS}ms netem to $N robot containers"
        fi

        echo "  spawning lambda=${LAMBDA}/s for ${DURATION}s ..."
        docker exec -e PYTHONUNBUFFERED=1 cf_metrics bash -lc \
            "source /ros2_ws/install/setup.bash && python3 /ros2_ws/scripts/task_spawner.py \
             --rate ${LAMBDA} --duration ${DURATION} --seed ${SEED} \
             --service /robot_1/coord/create_task" || echo "  (spawner non-zero)"
        sleep "$DRAIN"

        mkdir -p "${OUTLOGS}/run_${CONFIG}_seed${SEED}"
        mv logs/claim_robot*.csv logs/aoi_robot*.csv "${OUTLOGS}/run_${CONFIG}_seed${SEED}/" 2>/dev/null || true
        docker compose -f "$LFC" -f "$ROSC" down -v --remove-orphans >/dev/null 2>&1 || true
        # metrics writes the summary into the mounted logs/; move it under OUTLOGS for aggregation
        mv "logs/summary_${CONFIG}_seed${SEED}.json" "logs/timeseries_${CONFIG}_seed${SEED}.csv" "$OUTLOGS/" 2>/dev/null || true
        echo "  done -> ${OUTLOGS}/summary_${CONFIG}_seed${SEED}.json"
    done
done

echo ""; echo "=== aggregating ==="
REPORT_PY=python3
for c in "$HOME/miniconda3/envs/habitat_test/bin/python" "$HOME/miniconda3/envs/behavior/bin/python" python3; do
    "$c" -c "import matplotlib,numpy" >/dev/null 2>&1 && { REPORT_PY="$c"; break; }
done
"$REPORT_PY" scripts/report.py --logs-dir "$OUTLOGS" --results-dir "$OUTRES" --figs-dir "$OUTFIG" || echo "report failed"
echo "Done -> $OUTRES, $OUTFIG"
