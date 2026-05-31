#!/bin/bash
# Loopback network emulation for the testbed (threat-to-validity #1).
#
# The containers use network_mode: host, so all federation + DDS traffic rides
# the host loopback (lo). Real Jetsons talk over WiFi with non-trivial delay,
# jitter, and loss; on loopback those are ~0, so measured T_claim / AoI are
# best-case lower bounds. This injects a realistic network profile so a
# comparison run reflects deployment conditions.
#
# Usage:
#   sudo scripts/netem.sh on  [delay_ms] [jitter_ms] [loss_pct]   # default 5 1 0
#   sudo scripts/netem.sh off
#   scripts/netem.sh show
#
# WARNING: this affects ALL host loopback traffic while active. Turn it OFF
# after the run. Requires tc (iproute2) + NET_ADMIN (sudo).
set -e
DEV="${NETEM_DEV:-lo}"

case "${1:-}" in
  on)
    DELAY="${2:-5}ms"; JITTER="${3:-1}ms"; LOSS="${4:-0}%"
    tc qdisc replace dev "$DEV" root netem delay "$DELAY" "$JITTER" loss "$LOSS"
    echo "netem ON  dev=$DEV  delay=$DELAY jitter=$JITTER loss=$LOSS"
    tc qdisc show dev "$DEV"
    ;;
  off)
    tc qdisc del dev "$DEV" root 2>/dev/null || true
    echo "netem OFF dev=$DEV"
    ;;
  show)
    tc qdisc show dev "$DEV"
    ;;
  *)
    echo "usage: netem.sh on [delay_ms] [jitter_ms] [loss_pct] | off | show"
    exit 1
    ;;
esac
