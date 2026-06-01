#!/bin/bash
# Quick N=2 smoke test for the Context-Fabric testbed.
#
# Brings up a 2-robot federation, drives a short task burst, and asserts the
# federation actually COORDINATES -- tasks complete, no federate errors, RTI
# alive. Catches the regression classes we hit during development (RTI SIGSEGV,
# stale-.pyc get_tasks failure, federation-assembly hangs). Exit 0 = pass.
#
#   scripts/smoke_test.sh                      # centralized coordination
#   LF_COORD=decentralized scripts/smoke_test.sh   # decentralized (STP_offset)
#
# (gen_lf.py reads LF_COORD / LF_STA_MS from the environment, so no extra args.)
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"; cd "$REPO"
export PATH="$HOME/.local/bin:$PATH"
N=2; SEED=999

fail() { echo "SMOKE FAIL: $1"; exit 1; }

docker image inspect context-fabric-fed >/dev/null 2>&1 || docker build -f Dockerfile.fed -t context-fabric-fed . >/dev/null 2>&1 || fail "context-fabric-fed build"
rm -rf "fed-gen/coordinator_${N}"
python3 scripts/gen_lf.py --sizes "$N" --docker --compile >/tmp/smoke_gen.log 2>&1 || { tail -8 /tmp/smoke_gen.log; fail "lfc compile"; }
LFC="fed-gen/coordinator_${N}/src-gen/docker-compose.yml"
docker compose -f "$LFC" build >/tmp/smoke_build.log 2>&1 || { tail -8 /tmp/smoke_build.log; fail "federate image build"; }
python3 scripts/gen_compose_ros.py "$N" >/dev/null
ROSC="docker-compose.ros.${N}.yml"

export CF_SEED="$SEED"
docker compose -f "$LFC" -f "$ROSC" down -v --remove-orphans >/dev/null 2>&1 || true
docker compose -f "$LFC" -f "$ROSC" up -d >/dev/null 2>&1
sleep 28
docker exec cf_metrics bash -lc "source /ros2_ws/install/setup.bash && python3 /ros2_ws/scripts/task_spawner.py \
    --rate 0.5 --duration 20 --seed 5 --service /robot_1/coord/create_task" >/dev/null 2>&1 || true
sleep 70

completed=$(python3 -c "import json;print(json.load(open('logs/summary_iso_${N}robots_seed${SEED}.json')).get('tasks_completed',0))" 2>/dev/null || echo 0)
errs=$(docker compose -f "$LFC" -f "$ROSC" logs 2>&1 | grep -ciE "no attribute|Parse Error|Traceback|SIGSEGV" || true)
rti_up=$(docker ps --filter "name=coordinator_${N}-rti" --format '{{.Status}}' | grep -c Up || true)

docker compose -f "$LFC" -f "$ROSC" down -v --remove-orphans >/dev/null 2>&1 || true
rm -f "logs/summary_iso_${N}robots_seed${SEED}.json" "logs/timeseries_iso_${N}robots_seed${SEED}.csv" \
      logs/claim_robot*.csv logs/aoi_robot*.csv 2>/dev/null || true

echo "completed=$completed  federate_errors=$errs  rti_up=$rti_up  (coord=${LF_COORD:-centralized})"
[ "${completed:-0}" -ge 1 ] || fail "no tasks completed (federation not coordinating)"
[ "${errs:-1}" -eq 0 ]      || fail "$errs federate error line(s) in logs"
[ "${rti_up:-0}" -ge 1 ]    || fail "RTI not running"
echo "SMOKE TEST PASSED"
