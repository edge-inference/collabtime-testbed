#!/bin/bash
# Start the Lingua Franca RTI for an N-federate coordinator federation.
#
# The RTI coordinates logical time across all federates and must be running
# before they start. Federation size N must match the compiled program.
#
# Usage: start_rti.sh [N] [federation_id] [exchanges_per_interval]
#   (docker-compose normally runs the RTI directly; this is a host helper.)

set -e

N=${1:-2}
FED_ID=${2:-context-fabric-testbed-2025}
EXCHANGES=${3:-10}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../../.." && pwd)"          # src/coord/scripts -> repo root
RTI_BIN="$REPO/fed-gen/coordinator_${N}/bin/RTI"

if [ ! -f "$RTI_BIN" ]; then
    echo "Error: RTI binary not found for N=$N."
    echo "Expected: $RTI_BIN"
    echo "Generate + compile it first, e.g.:  python3 scripts/gen_lf.py --sizes $N --compile"
    exit 1
fi

echo "Starting LF RTI for $N federates (federation: $FED_ID, port 15045)..."
"$RTI_BIN" -i "$FED_ID" -n "$N" -c init exchanges-per-interval "$EXCHANGES"
