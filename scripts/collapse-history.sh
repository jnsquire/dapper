#!/usr/bin/env bash
set -euo pipefail

# Collapse repo history into a single commit on a new orphan branch.
# Usage: ./scripts/collapse-history.sh [new-branch] [backup-branch]

NEW_BRANCH=${1:-clean-main}
BACKUP_BRANCH=${2:-history-backup}

read -p "This will create a backup branch '$BACKUP_BRANCH' and a new orphan branch '$NEW_BRANCH' with a single commit. Continue? (type 'yes' to proceed) " ans
if [ "$ans" != "yes" ]; then
  echo "Aborted."
  exit 1
fi

echo "Creating backup branch '$BACKUP_BRANCH'..."
git branch -f "$BACKUP_BRANCH"

echo "Creating orphan branch '$NEW_BRANCH'..."
git checkout --orphan "$NEW_BRANCH"

echo "Resetting index (working tree preserved)..."
git reset --hard

echo "Adding all files and committing..."
git add -A
git commit -m "Initial import: collapsed history" --allow-empty

cat <<EOF
Done. Next steps (manual):
  - Inspect the branch: git log --oneline -n 5
  - To replace remote main (destructive):
      git push --force origin $NEW_BRANCH:main
  - Or push the new branch normally:
      git push origin $NEW_BRANCH

Warning: Force-pushing rewritten history will affect all collaborators.
EOF
