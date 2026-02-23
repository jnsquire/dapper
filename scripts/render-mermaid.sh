#!/bin/bash
set -euo pipefail
shopt -s nullglob
INPUT_DIR="doc/reference/diagrams"
OUTPUT_DIR="doc/reference/images"
FORCE=0

if [ "${1-}" = "--force" ]; then
  FORCE=1
fi

if [ ! -d "$INPUT_DIR" ]; then
  echo "Input directory $INPUT_DIR not found; skipping Mermaid render."
  exit 0
fi
mkdir -p "$OUTPUT_DIR"

if ! command -v npx >/dev/null 2>&1; then
  echo "npx not found in PATH. Install Node.js / npm to use npx and render diagrams (npm i -g npm)." >&2
  exit 2
fi

files=("$INPUT_DIR"/*.mmd)
if [ ${#files[@]} -eq 0 ]; then
  echo "No Mermaid source files found in $INPUT_DIR; nothing to render."
  exit 0
fi

for in in "${files[@]}"; do
  out="$OUTPUT_DIR/$(basename "${in%.*}").svg"
  render=0
  if [ $FORCE -eq 1 ]; then
    render=1
  elif [ ! -f "$out" ]; then
    render=1
  elif [ "$in" -nt "$out" ]; then
    render=1
  fi

  if [ $render -eq 0 ]; then
    echo "Skipping up-to-date: $in -> $out"
    continue
  fi

  echo "Rendering $in -> $out"
  npx -p @mermaid-js/mermaid-cli mmdc -i "$in" -o "$out"
done
