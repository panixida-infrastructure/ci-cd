#!/usr/bin/env bash
set -euo pipefail

action_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
destination="${1:?Usage: build.sh <archive-directory>}"
image="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["server_image"])' "$action_dir/versions.json")"
server_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["server_version"])' "$action_dir/versions.json")"
work_dir="$(mktemp -d)"
container=""
cleanup() {
  if [[ -n "$container" ]]; then
    docker rm -v "$container" >/dev/null
  fi
  rm -rf "$work_dir"
}
trap cleanup EXIT

mkdir -p "$work_dir/lib/scanner" "$work_dir/lib/extensions" "$work_dir/licenses"
docker pull --platform linux/amd64 "$image"
container="$(docker create --platform linux/amd64 "$image")"
# This also verifies that the image matches the configured server version.
docker cp "$container:/opt/sonarqube/lib/sonar-application-$server_version.jar" "$work_dir/lib/"
copy_directory() {
  # Image directories are read-only; extract as the unprivileged runner user.
  docker cp "$container:/opt/sonarqube/$1/." - \
    | tar -x --no-same-owner --no-same-permissions -C "$work_dir/$1"
  chmod -R u+rwX "$work_dir/$1"
}
copy_directory lib/scanner
copy_directory lib/extensions
docker cp "$container:/opt/sonarqube/COPYING" "$work_dir/"
copy_directory licenses
python3 "$action_dir/cache.py" build --sonarqube-dir "$work_dir" --destination "$destination"
