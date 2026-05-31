#!/bin/bash
# Interactive demo with the LIVE BROWSER grid view at http://localhost:8089.
# Brings up N robots (each = federate + ROS-stack container on the lf net) plus
# the fleet web viz, drives a Poisson task stream, and stays live until Ctrl-C.
#
#   scripts/demo_viz.sh [N=8] [duration_s=900]
#
# Then open http://localhost:8089 in a browser to watch the fleet.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$SCRIPT_DIR/.."
export PATH="$HOME/.local/bin:$PATH"
N="${1:-8}"; DUR="${2:-900}"; MULT="${3:-1}"   # 3rd arg = load multiplier (e.g. 3 = busier grid)

echo ">>> building LF-docker federation for N=$N (clean regen) ..."
rm -rf "fed-gen/coordinator_${N}"
python3 scripts/gen_lf.py --sizes "$N" --docker --compile >/dev/null 2>&1
LFC="fed-gen/coordinator_${N}/src-gen/docker-compose.yml"
docker compose -f "$LFC" build >/dev/null 2>&1
WITH_VIZ=1 python3 scripts/gen_compose_ros.py "$N" >/dev/null
ROSC="docker-compose.ros.${N}.yml"

cleanup(){ echo; echo ">>> tearing down"; docker compose -f "$LFC" -f "$ROSC" down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker compose -f "$LFC" -f "$ROSC" down -v --remove-orphans >/dev/null 2>&1 || true
docker compose -f "$LFC" -f "$ROSC" up -d

echo ""
echo "============================================================"
echo "   LIVE FLEET VIEW  ->  http://localhost:8089"
echo "   N=$N robots · spawning tasks for ${DUR}s · Ctrl-C to stop"
echo "============================================================"
sleep 20
RATE=$(python3 -c "print(round(0.012*$N*$MULT, 4))")
docker exec cf_metrics bash -lc "source /ros2_ws/install/setup.bash && python3 /ros2_ws/scripts/task_spawner.py \
    --rate $RATE --duration $DUR --seed 42 --service /robot_1/coord/create_task" || true
echo ">>> spawn window finished; viz still live. Ctrl-C to stop."
sleep infinity
