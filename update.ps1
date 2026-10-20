# ============================================================================
# Update MIDI-GPT for REAPER to the latest version (Windows / PowerShell)
# Usage: .\update.ps1 [any install.ps1 flag, e.g. -TorchGpu, -MidigptSrc PATH]
# ============================================================================

$ErrorActionPreference = "Continue"

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Info { param($msg) Write-Host "[INFO] " -ForegroundColor Blue -NoNewline; Write-Host $msg }
function Write-OK   { param($msg) Write-Host "[OK] " -ForegroundColor Green -NoNewline; Write-Host $msg }
function Write-Fail { param($msg) Write-Host "[ERROR] " -ForegroundColor Red -NoNewline; Write-Host $msg; exit 1 }
function Test-Interactive { -not [Console]::IsInputRedirected }

Write-Host ""
Write-Host ("-" * 40) -ForegroundColor White
Write-Host "  MIDI-GPT for REAPER -- Update" -ForegroundColor White
Write-Host ("-" * 40) -ForegroundColor White
Write-Host ""

# ── Pull latest plugin code ──────────────────────────────────────
Write-Info "Pulling latest plugin code..."
git -C $RepoDir pull
if ($LASTEXITCODE -ne 0) { Write-Fail "git pull failed. Check your internet connection." }
Write-OK "Plugin code up to date"

# ── Refresh the venv/backend via install.ps1 ──────────────────────
# Reuses install.ps1's own venv/backend logic (Steps 1-3, 6) instead of
# duplicating a simplified version of it here -- see update.sh's own
# comment for why (short version: install.ps1 already knows whether this
# environment is a PyPI install or an editable/source one, and updates it
# correctly either way).
#
# -BackendOnly skips every REAPER-side step (junction, ReaPack, reaper.ini)
# entirely, so this never needs REAPER closed and never re-asks the
# one-time Sforzando/Arachno question. MIDIGPT_SKIP_LAUNCH_PROMPT
# suppresses install.ps1's own "start the server now?" prompt so only this
# script's copy of that question runs.
$InstallScript = Join-Path $RepoDir "install.ps1"
if (-not (Test-Path $InstallScript)) { Write-Fail "install.ps1 not found -- this checkout looks incomplete." }
Write-Info "Refreshing the Python venv/backend..."
$env:MIDIGPT_SKIP_LAUNCH_PROMPT = "1"
& $InstallScript -BackendOnly -SkipDeps @args
$env:MIDIGPT_SKIP_LAUNCH_PROMPT = $null

# ── Done ─────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Update complete." -ForegroundColor Green
Write-Host ""

if (Test-Interactive) {
    $Launch = Read-Host "  Start the server now? [Y/n]"
    if (-not $Launch) { $Launch = "y" }
    if ($Launch -match "^[Yy]$") {
        Write-Host ""
        Write-Host "    [1] Yellow     (default)"
        Write-Host "    [2] Prism"
        Write-Host "    [3] Expressive"
        Write-Host ""
        $ModelChoice = Read-Host "  Model [1/2/3, default=1]"
        switch ($ModelChoice) {
            "2" { $Model = "prism_medium" }
            "3" { $Model = "expressive_medium" }
            default { $Model = "yellow_medium" }
        }
        Write-Host ""
        # midigpt-http only resolves once the venv is activated -- update.ps1
        # runs as its own process, so (unlike install.ps1's own copy of this
        # prompt, later in the same script's session) it can't assume that's
        # already been done here.
        $ActivateScript = Join-Path $RepoDir ".venv\Scripts\Activate.ps1"
        if (Test-Path $ActivateScript) {
            & $ActivateScript
            midigpt-http --pretrained $Model --port 3456 --device auto
        } else {
            Write-Fail "Virtual environment not found at .venv\ -- something went wrong above."
        }
    }
}
