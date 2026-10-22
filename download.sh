#!/bin/bash
# Only file allowed to use the network. Downloads raw data into data/raw/.
# Usage: ./download.sh [all|wikipedia|fineweb|phinc]
set -e
cd "$(dirname "$0")"
python3 data/details/scripts/download_data.py "${1:-all}"
