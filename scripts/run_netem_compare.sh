#!/bin/bash
# Network-realism comparison pass (threat-to-validity #1).
#
# Re-runs the sweep with the host loopback shaped to emulate a real robot
# network (delay/jitter/loss), into a SEPARATE 'netem<delay>ms' label so the
# loopback baseline in results/ is left untouched. Compare the two to show how
# much T_claim / AoI grow under realistic network conditions.
#
# Needs sudo (tc/netem). Run it yourself:
#   scripts/run_netem_compare.sh [delay_ms=20] [jitter_ms=5] [loss_pct=0.5] [sizes="8 16"] [duration=240]
#
# WARNING: netem shapes ALL host loopback traffic while active; the trap below
# always removes it on exit.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

DELAY="${1:-20}"; JITTER="${2:-5}"; LOSS="${3:-0.5}"
SIZES="${4:-8 16}"; DURATION="${5:-240}"
LABEL="netem${DELAY}ms"

cleanup() { echo ">>> removing netem from lo"; sudo scripts/netem.sh off || true; }
trap cleanup EXIT

echo ">>> applying netem on lo: delay=${DELAY}ms jitter=${JITTER}ms loss=${LOSS}%"
sudo scripts/netem.sh on "$DELAY" "$JITTER" "$LOSS"

echo ">>> running sweep into label '$LABEL'  (sizes=[$SIZES], duration=${DURATION}s)"
LABEL="$LABEL" scripts/run_sweep.sh "$SIZES" "$DURATION"

echo ""
echo ">>> done. Compare loopback baseline vs realistic network:"
echo "    baseline : results/testbed_table.md         figures/testbed/"
echo "    netem    : results/$LABEL/testbed_table.md   figures/testbed/$LABEL/"
