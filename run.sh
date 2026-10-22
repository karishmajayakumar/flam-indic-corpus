#!/bin/bash
# ./run.sh <raw_dir> <out_dir> — offline. Downloading lives in download.sh only.
set -e
cd "$(dirname "$0")"
python3 -m src.pipeline "$1" "$2"
