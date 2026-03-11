#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

version="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n 1)"
if [ -z "${version}" ]; then
  echo "Could not determine project version from pyproject.toml" >&2
  exit 1
fi

rm -rf dist
mkdir -p dist

recipe_file="$(mktemp)"
trap 'rm -f "${recipe_file}"' EXIT
sed "s/__APPIMAGE_VERSION__/${version}/" packaging/AppImageBuilder.yml > "${recipe_file}"

appimage-builder --recipe "${recipe_file}" --skip-test

shopt -s nullglob
appimages=(AppImage_Integrator-*.AppImage AppImage-Integrator-*.AppImage *.AppImage)
zsyncs=(AppImage_Integrator-*.zsync AppImage-Integrator-*.zsync *.zsync)

if [ "${#appimages[@]}" -eq 0 ]; then
  echo "appimage-builder did not produce an AppImage." >&2
  exit 1
fi

mv "${appimages[0]}" "dist/AppImage-Integrator-${version}-x86_64.AppImage"

if [ "${#zsyncs[@]}" -gt 0 ]; then
  mv "${zsyncs[0]}" "dist/AppImage-Integrator-${version}-x86_64.AppImage.zsync"
fi
