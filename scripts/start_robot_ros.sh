#!/bin/bash
set -e
# Launch one robot's ROS stack (bridge + DSM + agent) for the ISOLATED-NETWORK
# (LF-docker) testbed. The robot's LF federate runs in a SEPARATE container
# reachable at $LF_FED_HOST:9000+device_id (docker service-DNS on the `lf`
# bridge network) -- this script does NOT start a federate.
#
# Usage: start_robot_ros.sh <device_id> [start_node] [step_time_s] [work_time_s]

DEVICE_ID=$1
START_NODE=${2:-0}
STEP_TIME_S=${3:-2.0}
WORK_TIME_S=${4:-45.0}
LF_FED_HOST="${LF_FED_HOST:-localhost}"
# LF_FED_PORT (set by the centralized compose) points every robot at ONE shared
# federate; unset -> per-robot federate port 9000+device_id (distributed).
LF_PORT="${LF_FED_PORT:-$((9000 + DEVICE_ID))}"

echo "=== Robot $DEVICE_ID ROS stack (federate at ${LF_FED_HOST}:${LF_PORT}) ==="
source /ros2_ws/install/setup.bash

# Wait for this robot's (external) federate to be reachable before the bridge.
echo "[robot $DEVICE_ID] waiting for federate ${LF_FED_HOST}:${LF_PORT} ..."
for _ in $(seq 1 180); do
    if (echo > "/dev/tcp/${LF_FED_HOST}/${LF_PORT}") 2>/dev/null; then
        echo "[robot $DEVICE_ID] federate reachable."; break
    fi
    sleep 1
done

echo "[robot $DEVICE_ID] starting LF bridge (-> ${LF_FED_HOST}:${LF_PORT})..."
lf_bridge_node --ros-args \
    -r __ns:=/robot_"$DEVICE_ID" -r __node:=lf_bridge_node \
    -p device_id:="$DEVICE_ID" -p lf_port:="$LF_PORT" \
    -r task_events:=/task_events &
BRIDGE_PID=$!
sleep 2

echo "[robot $DEVICE_ID] starting DSM node..."
dsm_node --ros-args \
    -r __ns:=/robot_"$DEVICE_ID" -r __node:=dsm_node \
    -p device_id:="$DEVICE_ID" -r dsm_gossip:=/dsm_gossip &
DSM_PID=$!

echo "[robot $DEVICE_ID] starting agent node..."
agent_node --ros-args \
    -r __ns:=/robot_"$DEVICE_ID" -r __node:=agent_node \
    -p agent_id:="$DEVICE_ID" -p device_id:="$DEVICE_ID" \
    -p start_node:="$START_NODE" \
    -p step_time_s:="$STEP_TIME_S" -p work_time_s:="$WORK_TIME_S" \
    -r agent_state:=/agent_state -r dsm_gossip:=/dsm_gossip &
AGENT_PID=$!

wait -n
echo "[robot $DEVICE_ID] a process exited; shutting down."
kill "$BRIDGE_PID" "$DSM_PID" "$AGENT_PID" 2>/dev/null || true
