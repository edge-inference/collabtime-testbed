#!/bin/bash
set -e

# Launch one emulated robot: LF federate + ROS-LF bridge + DSM node + agent.
#
# Usage:
#   start_robot.sh <device_id> <fed_executable> <rti_host> <rti_port> \
#                  <federation_id> [start_node] [step_time_s] [work_time_s]
#
# The LF federate only opens its bridge socket (port 9000+device_id) AFTER the
# whole federation has assembled at the RTI, so we wait for that port before
# starting the bridge instead of using a fixed sleep.

DEVICE_ID=$1
FED_EXEC=$2
RTI_HOST=$3
RTI_PORT=$4
FED_ID=$5
START_NODE=${6:-0}
STEP_TIME_S=${7:-2.0}
WORK_TIME_S=${8:-45.0}

LF_PORT=$((9000 + DEVICE_ID))

echo "=== Starting Robot $DEVICE_ID ==="
echo "Federate:      $FED_EXEC"
echo "RTI:           $RTI_HOST:$RTI_PORT  (federation: $FED_ID)"
echo "Start node:    $START_NODE   step=${STEP_TIME_S}s  work=${WORK_TIME_S}s"
echo "Bridge port:   $LF_PORT"

source /ros2_ws/install/setup.bash

# 1. LF Federate (retries RTI connection internally until the federation forms)
echo "[robot $DEVICE_ID] starting LF federate..."
"$FED_EXEC" -i "$FED_ID" --rti "$RTI_HOST:$RTI_PORT" &
LF_PID=$!

# 2. Wait for the federate's bridge socket to come up (federation assembled)
echo "[robot $DEVICE_ID] waiting for federate socket on port $LF_PORT ..."
for _ in $(seq 1 180); do
    if (echo > "/dev/tcp/127.0.0.1/$LF_PORT") 2>/dev/null; then
        echo "[robot $DEVICE_ID] federate socket is up."
        break
    fi
    if ! kill -0 "$LF_PID" 2>/dev/null; then
        echo "[robot $DEVICE_ID] FATAL: federate process exited before binding socket."
        exit 1
    fi
    sleep 1
done

# 3. ROS-LF Bridge (translates ROS service calls <-> LF federate)
echo "[robot $DEVICE_ID] starting LF bridge..."
lf_bridge_node --ros-args \
    -r __ns:=/robot_"$DEVICE_ID" -r __node:=lf_bridge_node \
    -p device_id:="$DEVICE_ID" -p lf_port:="$LF_PORT" \
    -r task_events:=/task_events &
BRIDGE_PID=$!
sleep 2

# 4. DSM Node (eventually-consistent data plane / gossip)
echo "[robot $DEVICE_ID] starting DSM node..."
dsm_node --ros-args \
    -r __ns:=/robot_"$DEVICE_ID" -r __node:=dsm_node \
    -p device_id:="$DEVICE_ID" -r dsm_gossip:=/dsm_gossip &
DSM_PID=$!

# 5. Agent Node (state-machine policy)
echo "[robot $DEVICE_ID] starting agent node..."
agent_node --ros-args \
    -r __ns:=/robot_"$DEVICE_ID" -r __node:=agent_node \
    -p agent_id:="$DEVICE_ID" -p device_id:="$DEVICE_ID" \
    -p start_node:="$START_NODE" \
    -p step_time_s:="$STEP_TIME_S" -p work_time_s:="$WORK_TIME_S" \
    -r agent_state:=/agent_state -r dsm_gossip:=/dsm_gossip &
AGENT_PID=$!

# Wait for any process to exit, then clean up the rest.
wait -n
echo "[robot $DEVICE_ID] a process exited; shutting down robot."
kill "$LF_PID" "$BRIDGE_PID" "$DSM_PID" "$AGENT_PID" 2>/dev/null || true
