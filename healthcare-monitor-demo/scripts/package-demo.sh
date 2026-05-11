#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARENT="$(dirname "$ROOT")"
NAME="$(basename "$ROOT")"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${1:-$PARENT/${NAME}-${STAMP}.zip}"

mkdir -p "$(dirname "$OUT")"

case "$OUT" in
  *.zip)
    python3 - "$PARENT" "$NAME" "$OUT" <<'PY'
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

parent = Path(sys.argv[1]).resolve()
name = sys.argv[2]
out = Path(sys.argv[3]).resolve()
root = parent / name

excluded_dirs = {".git", "__pycache__", "state", "outputs", "tmp"}
excluded_files = {".env", "DEPLOY-NOTES.md"}
excluded_suffixes = {".pyc", ".tgz", ".zip", ".plan.md"}

with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(parent)
        project_rel = path.relative_to(root)
        parts = set(project_rel.parts)
        if path.is_dir():
            continue
        if excluded_files.intersection(parts):
            continue
        if excluded_dirs.intersection(parts):
            continue
        if path.suffix in excluded_suffixes:
            continue
        info = zipfile.ZipInfo.from_file(path, rel.as_posix())
        mode = path.stat().st_mode
        if os.access(path, os.X_OK):
            info.external_attr = (mode & 0o777) << 16
        archive.writestr(info, path.read_bytes())
PY
    ;;
  *.tgz | *.tar.gz)
    tar \
      --create \
      --gzip \
      --file "$OUT" \
      --directory "$PARENT" \
      --exclude="$NAME/.git" \
      --exclude="$NAME/.env" \
      --exclude="$NAME/demo-app/state" \
      --exclude="$NAME/demo-app/__pycache__" \
      --exclude="$NAME/**/__pycache__" \
      --exclude="$NAME/**/*.pyc" \
      --exclude="$NAME/*.tgz" \
      --exclude="$NAME/*.zip" \
      --exclude="$NAME/outputs" \
      --exclude="$NAME/tmp" \
      --exclude="$NAME/docs/DEPLOY-NOTES.md" \
      --exclude="$NAME/*.plan.md" \
      "$NAME"
    ;;
  *)
    echo "Unsupported archive extension: $OUT" >&2
    echo "Use .zip, .tgz, or .tar.gz" >&2
    exit 1
    ;;
esac

echo "Created portable archive:"
echo "  $OUT"
echo
echo "Restore on another machine:"
case "$OUT" in
  *.zip)
    echo "  unzip $(basename "$OUT") -d ~"
    ;;
  *)
    echo "  tar -xzf $(basename "$OUT") -C ~"
    ;;
esac
echo "  cd ~/$NAME"
echo "  cp .env.example .env"
echo "  chmod 600 .env"
echo "  vi .env"
echo "  ./scripts/brev-runtime-setup.sh"
echo "  ./scripts/live-demo-ready.sh"
