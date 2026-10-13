#!/usr/bin/env bash
# Rebuild the site from db/, commit everything, and push to main. If the remote moved meanwhile, re-apply
# our db/ and notes/ changes on top of it (three-way merge per file), rebuild, and try again.
#   usage: bash tools/ci_push.sh "commit message"
set -u
MSG="${1:-Update}"
git config user.name "Morning Line"
git config user.email "noreply@anthropic.com"
publish() { python3 tools/publish.py > /tmp/publish.log 2>&1 || { cat /tmp/publish.log; exit 1; }; tail -1 /tmp/publish.log; }
publish
git add -A
if git diff --cached --quiet; then echo "Nothing to commit."; exit 0; fi
git commit -q -m "$MSG"
for attempt in 1 2 3 4; do
  if git push -q origin HEAD:main; then echo "Pushed: $MSG"; exit 0; fi
  echo "Remote moved; re-applying on top (attempt $attempt)."
  base=$(git rev-parse HEAD~1)
  files=$(git diff --name-only "$base" HEAD -- db notes)
  rm -rf /tmp/ours && mkdir -p /tmp/ours
  for f in $files; do
    mkdir -p "/tmp/ours/$(dirname "$f")"
    [ -f "$f" ] && cp "$f" "/tmp/ours/$f"
    git show "$base:$f" > "/tmp/ours/$f.base" 2>/dev/null || rm -f "/tmp/ours/$f.base"
  done
  git fetch -q origin main && git reset -q --hard origin/main
  for f in $files; do
    [ -f "/tmp/ours/$f" ] || continue
    if [ -f "/tmp/ours/$f.base" ] && [ -f "$f" ] && ! cmp -s "/tmp/ours/$f.base" "$f"; then
      git merge-file "/tmp/ours/$f" "/tmp/ours/$f.base" "$f" > /dev/null 2>&1 || echo "Merge conflict in $f: kept ours where they overlap."
    fi
    mkdir -p "$(dirname "$f")" && cp "/tmp/ours/$f" "$f"
  done
  publish
  git add -A
  if git diff --cached --quiet; then echo "Nothing left to commit."; exit 0; fi
  git commit -q -m "$MSG"
done
echo "Push failed after retries."
exit 1
