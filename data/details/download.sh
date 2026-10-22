#!/bin/bash
# Only file allowed to use the network.
set -e
cd "$(dirname "$0")"
python3 scripts/download_data.py "${1:-all}"
