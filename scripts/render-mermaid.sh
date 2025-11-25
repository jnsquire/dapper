#!/bin/bash
set -euo pipefail
INPUT_DIR="doc/reference/diagrams"
OUTPUT_DIR="doc/reference/images"
FORCE=0

if [ "${1-}" = "--force" ]; then
  FORCE=1
fi

if [ ! -d "$INPUT_DIR" ]; then
  echo "Input directory $INPUT_DIR not found." >&2
  exit 1
fi
mkdir -p "$OUTPUT_DIR"

if command -v mmdc >/dev/null 2>&1; then
  USE_NPX=0
elif command -v npx >/dev/null 2>&1; then
  USE_NPX=1
else
  echo "Neither mmdc nor npx found in PATH. Install mermaid-cli globally (npm i -g @mermaid-js/mermaid-cli) or install Node.js to use npx" >&2
  exit 2
fi

for in in "$INPUT_DIR"/*.mmd; do
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
  if [ $USE_NPX -eq 1 ]; then
    npx -p @mermaid-js/mermaid-cli mmdc -i "$in" -o "$out"
  else
    mmdc -i "$in" -o "$out"
  fi
done
