#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: bash tooling/ci/materialize_release_tag.sh <tag-name> <target-commit>" >&2
  exit 2
fi

tag_name="$1"
target_ref="$2"
remote_name="${RELEASE_TAG_REMOTE:-origin}"
apply_mode="${RELEASE_TAG_APPLY:-0}"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "materialize_release_tag requires a git worktree" >&2
  exit 1
fi

if ! git rev-parse --verify "${target_ref}^{commit}" >/dev/null 2>&1; then
  echo "target commit is not resolvable: $target_ref" >&2
  exit 1
fi

if ! git remote get-url "$remote_name" >/dev/null 2>&1; then
  echo "remote not configured: $remote_name" >&2
  exit 1
fi

target_commit="$(git rev-parse "${target_ref}^{commit}")"

ensure_git_identity() {
  # Keep release tag creation deterministic in CI/pre-push-style clean checkouts
  # where repo-local git identity may be absent on the runner.
  if git config --local user.name >/dev/null 2>&1 && git config --local user.email >/dev/null 2>&1; then
    return 0
  fi

  local default_name="${RELEASE_TAG_GIT_USER_NAME:-github-actions[bot]}"
  local default_email="${RELEASE_TAG_GIT_USER_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"
  git config --local user.name "$default_name"
  git config --local user.email "$default_email"
}

resolve_local_tag_commit() {
  git rev-parse --verify "${tag_name}^{commit}" 2>/dev/null || true
}

remote_tag_exists() {
  git ls-remote --exit-code --tags "$remote_name" "refs/tags/$tag_name" >/dev/null 2>&1
}

local_commit="$(resolve_local_tag_commit)"
if [ -z "$local_commit" ]; then
  git fetch --no-tags "$remote_name" "refs/tags/$tag_name:refs/tags/$tag_name" >/dev/null 2>&1 || true
  local_commit="$(resolve_local_tag_commit)"
fi

if [ -n "$local_commit" ] && [ "$local_commit" != "$target_commit" ]; then
  echo "existing release tag points at $local_commit, expected $target_commit" >&2
  exit 1
fi

if [ -n "$local_commit" ] && remote_tag_exists; then
  printf 'release tag materialized: tag=%s target=%s remote=present\n' "$tag_name" "$target_commit"
  exit 0
fi

if [ -n "$local_commit" ] && [ "$apply_mode" != "1" ]; then
  echo "release tag matches target locally but is not present on remote; rerun with RELEASE_TAG_APPLY=1 to push it" >&2
  exit 1
fi

if [ -z "$local_commit" ] && [ "$apply_mode" != "1" ]; then
  echo "release tag is not materialized; rerun with RELEASE_TAG_APPLY=1 to create and push it" >&2
  exit 1
fi

if [ -z "$local_commit" ]; then
  ensure_git_identity
  git tag -a "$tag_name" "$target_commit" -m "Release $tag_name"
fi

git push "$remote_name" "refs/tags/$tag_name"
printf 'release tag materialized: tag=%s target=%s remote=created\n' "$tag_name" "$target_commit"
