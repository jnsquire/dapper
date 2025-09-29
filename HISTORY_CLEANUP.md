History cleanup and collapsing
=================================

This repository includes helper scripts to collapse the Git history into a single commit.

Why collapse history?
- Reduce repository size
- Remove sensitive data accidentally committed

Important warnings
- Collapsing history rewrites commits and is destructive if you replace remote branches with a force-push.
- Always create a backup branch (the scripts do this by default).
- Inform collaborators before force-pushing rewritten history.

Provided scripts
- `scripts/collapse-history.sh` — POSIX bash script for Unix/Linux/macOS.
- `scripts/collapse-history.ps1` — PowerShell script for Windows.

Typical safe workflow
1. Ensure working tree is clean and you have pushed all important refs:

   git status
   git fetch --all --prune

2. Run the script to create a backup and a new orphan branch (confirm when prompted):

   # Example (bash)
   ./scripts/collapse-history.sh clean-main history-backup

   # Example (PowerShell)
   ./scripts/collapse-history.ps1 -NewBranch clean-main -BackupBranch history-backup

3. Inspect the new branch and backup branch locally:

   git checkout clean-main
   git log --oneline -n 10
   git checkout history-backup
   git log --oneline -n 10

4. When you are certain, push the cleaned branch to the remote (destructive):

   git push --force origin clean-main:main

5. Communicate with collaborators: explain that history was rewritten and that they will need to reset their clones.

Recovery notes
- If something goes wrong, the `history-backup` branch contains the previous refs and can be used to restore.

Support
- If you want, I can add a GitHub Actions workflow to automate creating a release branch after collapsing history, or add a CI gate to prevent accidental force-pushes.
