#!/bin/sh
set -eu

if [ ! -f /input/instruction.md ]; then
  echo "missing /input/instruction.md" >&2
  exit 2
fi
if [ ! -d /input/public ]; then
  echo "missing /input/public" >&2
  exit 2
fi
if [ -z "${GENERATION_COMMAND:-}" ]; then
  echo "GENERATION_COMMAND is required" >&2
  exit 2
fi

rm -rf /work/candidate
mkdir -p /work/candidate
cp -a /input/public/. /work/candidate/
cp /input/instruction.md /work/candidate/INSTRUCTION.md

cd /work/candidate
sh -lc "$GENERATION_COMMAND"

rm -rf /output/candidate
mkdir -p /output/candidate
cp -a /work/candidate/. /output/candidate/
