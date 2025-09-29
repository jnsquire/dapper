<#
.SYNOPSIS
  Collapse repository history into a single commit on a new branch (PowerShell).

.DESCRIPTION
  This script creates a backup branch, then creates a new orphan branch
  containing a single commit with the current working tree. It does NOT
  push anything to remotes; after running you may force-push the new branch
  to replace remote history.

.WARNING
  This operation rewrites history and is destructive if you force-push
  over an existing remote. Use with care and ensure you have backups.
#>

param(
    [string]$NewBranch = 'clean-main',
    [string]$BackupBranch = 'history-backup',
    [switch]$Force
)

function Confirm-OrAbort($msg) {
    if ($Force) { return }
    $r = Read-Host "$msg (type 'yes' to continue)"
    if ($r -ne 'yes') {
        Write-Host 'Aborted by user.' -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "Preparing to collapse git history in: $(Get-Location)" -ForegroundColor Cyan

Confirm-OrAbort "This will create a backup branch '$BackupBranch' and a new orphan branch '$NewBranch' containing a single commit. Continue?"

Write-Host "Creating backup branch '$BackupBranch'..." -ForegroundColor Green
git branch -f $BackupBranch

Write-Host "Creating orphan branch '$NewBranch'..." -ForegroundColor Green
git checkout --orphan $NewBranch

Write-Host 'Removing all files from the index (working tree preserved)...' -ForegroundColor Green
git reset --hard

Write-Host 'Adding all files and creating the single consolidated commit...' -ForegroundColor Green
git add -A
git commit -m "Initial import: collapsed history" --allow-empty

Write-Host "Done. You now have branch '$NewBranch' with a single commit.
Next steps (manual):
  - Inspect the branch: git log --oneline -n 5
  - If you want to replace the remote main branch, run:
      git push --force origin $NewBranch:main
  - Or push the new branch as-is: git push origin $NewBranch
" -ForegroundColor Cyan

Write-Host 'Important: DO NOT force-push unless you understand the impact.' -ForegroundColor Yellow
