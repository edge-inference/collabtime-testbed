#!/usr/bin/env python3
"""Read a value from config/testbed.yaml by dotted key (for shell scripts).

    python3 scripts/cfg.py fleet_sizes        -> "2 4 8 16"
    python3 scripts/cfg.py run.duration_s     -> "300"
"""
import os
import sys

import yaml

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: cfg.py <dotted.key>")
    cfg = yaml.safe_load(open(os.path.join(REPO, "config", "testbed.yaml")))
    cur = cfg
    for key in sys.argv[1].split("."):
        cur = cur[key]
    if isinstance(cur, (list, tuple)):
        print(" ".join(str(x) for x in cur))
    else:
        print(cur)


if __name__ == "__main__":
    main()
