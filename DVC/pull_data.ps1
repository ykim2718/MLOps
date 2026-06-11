Clear-Host
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "   DVC & Git Data Timemachine Automation     " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# -------------------------------------------------------------
# [Step 1] Check Git repository status and get repository URL
# -------------------------------------------------------------
if (-not (Test-Path ".git")) {
    Write-Host "`n[Warning] Current directory is not a Git repository!" -ForegroundColor Red
    $Choice = Read-Host "Do you want to clone the GitHub repository into this folder? (y/n)"

    if ($Choice -eq 'y' -or $Choice -eq 'Y') {
        # Prompt user for the GitHub repository URL dynamically if not a Git repo
        $RepoUrl = Read-Host "`nEnter GitHub Repository URL"

        if ([string]::IsNullOrEmpty($RepoUrl)) {
            Write-Host "[Terminated] URL is empty. Aborting process." -ForegroundColor Red
            exit
        }

        Write-Host "`n[Proceeding] Cloning project into the current directory..." -ForegroundColor Green
        # Clone directly into the current directory (.)
        git clone $RepoUrl .

        if ($LASTEXITCODE -ne 0) {
            Write-Error "Git clone failed. Please check the URL or directory permissions."; exit
        }
    } else {
        Write-Host "[Terminated] Aborting process. Please move to a Git repository and run again." -ForegroundColor Yellow
        exit
    }
} else {
    Write-Host "`n[Verified] Existing Git repository detected. Proceeding to the next step." -ForegroundColor Green
}

# -------------------------------------------------------------
# [Step 2] Display Git commit history for DVC (.dvc) files only
# -------------------------------------------------------------
Write-Host "`n=============================================" -ForegroundColor Cyan
Write-Host "  [Recommended] Commit History for Data (.dvc)" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# Enclose the pathspec in single quotes to prevent PowerShell from misinterpreting the colon (:)
git log -n 5 --format="%h %cd : %s" --date=format:"%Y-%m-%d %H:%M" -- ':(top)**/*.dvc'

# -------------------------------------------------------------
# [Step 3] Prompt user for Commit ID and restore data
# -------------------------------------------------------------
Write-Host ""
$CommitId = Read-Host "Enter the Target Commit ID (First 7 characters) to restore"

if ([string]::IsNullOrEmpty($CommitId)) {
    Write-Host "[Terminated] No Commit ID entered. Aborting process." -ForegroundColor Red
    exit
}

# CRITICAL: Extract ONLY .dvc files from the past commit. Python files (*.py) remain untouched.
Write-Host "`n[$CommitId] Fetching only the data tracking files (.dvc) from the selected commit..." -ForegroundColor Yellow
git checkout $CommitId -- ':(top)**/*.dvc'

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to checkout .dvc files from commit $CommitId."; exit
}

# Synchronize large data files from MinIO remote storage based on the restored .dvc files
Write-Host "Synchronizing large data files from remote storage (dvc pull)..." -ForegroundColor Yellow
dvc pull

# CLEANUP: Reset the .dvc index and files back to current main/working state so they don't overwrite your next commit
Write-Host "`n[Cleanup] Unstaging and restoring .dvc tracking state to current working branch..." -ForegroundColor Yellow
git restore --staged -- ':(top)**/*.dvc'   # Unstage from index (replaces 'git reset HEAD')
git restore -- ':(top)**/*.dvc'            # Discard changes in working directory (replaces 'git checkout --')

Write-Host "`n[Success] Data has been perfectly restored while keeping your current Python code intact!" -ForegroundColor Green