#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: bash tooling/ci/validate_release_tag.sh <tag-name> <publish-mode>" >&2
  exit 2
fi

tag_name="$1"
publish_mode="$2"
required_branch="${RELEASE_REQUIRED_BRANCH:-}"

case "$publish_mode" in
  bundle-only|draft|publish) ;;
  *)
    echo "Unsupported publish mode: $publish_mode" >&2
    exit 2
    ;;
esac

stable_regex='^v[0-9]+\.[0-9]+\.[0-9]+$'
prerelease_regex='^v[0-9]+\.[0-9]+\.[0-9]+-(alpha|beta|rc)\.[0-9]+$'

if ! [[ "$tag_name" =~ $stable_regex || "$tag_name" =~ $prerelease_regex ]]; then
  echo "Invalid release tag: $tag_name" >&2
  echo "Expected vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH-(alpha|beta|rc).N" >&2
  exit 1
fi

if ! git check-ref-format "refs/tags/$tag_name" >/dev/null 2>&1; then
  echo "Invalid git tag ref: $tag_name" >&2
  exit 1
fi

if [ "$publish_mode" = "publish" ] && [[ "$tag_name" =~ -(alpha|beta)\.[0-9]+$ ]]; then
  echo "Mode publish only supports stable or rc tags; use draft/bundle-only for alpha/beta tags" >&2
  exit 1
fi

if [ -n "$required_branch" ]; then
  current_branch="${GITHUB_REF_NAME:-}"
  if [ -z "$current_branch" ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    current_branch="$(git rev-parse --abbrev-ref HEAD)"
  fi
  if [ "$current_branch" != "$required_branch" ]; then
    echo "Release tag policy requires branch $required_branch, current branch is ${current_branch:-unknown}" >&2
    exit 1
  fi
fi

release_class="stable"
is_prerelease="false"
if [[ "$tag_name" =~ $prerelease_regex ]]; then
  release_class="${BASH_REMATCH[1]}"
  is_prerelease="true"
fi

printf 'release tag policy ok: tag=%s mode=%s prerelease=%s class=%s\n' \
  "$tag_name" "$publish_mode" "$is_prerelease" "$release_class"
