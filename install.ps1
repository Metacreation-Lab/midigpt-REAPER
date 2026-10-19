# ============================================================================
# MIDI-GPT for REAPER — Windows Installer (PowerShell)
#
# Installs everything needed to run MIDI-GPT in REAPER:
#   1. System dependencies (python, git) via winget or choco, plus the
#      Microsoft Visual C++ Runtime PyTorch needs (from Microsoft, with UAC)
#   2. Python virtual environment + PyTorch
#   3. MIDI-GPT backend library (pip, from PyPI or a sibling/source checkout)
#   4. REAPER integration (Scripts junction), plus ReaPack and ReaImGui (the
#      dashboard UI's REAPER extension dependencies)
#   5. REAPER Python/ReaScript configuration (reaper.ini)
#   6. Verification of installation
#
# ReaPack itself is installed directly (it's just an extension DLL,
# downloaded over HTTPS from its GitHub release and checksum-verified
# against GitHub's own published digest before use -- it isn't code-signed,
# so this is the only integrity check available for it; Unblock-File then
# clears the downloaded-file mark so REAPER can load it without a manual
# SmartScreen click-through). The dashboard UI's ReaImGui extension is also
# downloaded directly from codeberg.org (ReaTeam Extensions) with checksum
# verification. Both installs require REAPER to be closed (the installer
# will ask permission to close it).
#
# Usage:
#   .\install.ps1                              # Full install
#   .\install.ps1 -SkipDeps                    # Skip dependency check
#   .\install.ps1 -SkipReaperConfig            # Don't modify reaper.ini
#   .\install.ps1 -ReaperOnly                  # Only Step 4/5 (REAPER
#                                                 integration) -- skips
#                                                 venv/backend entirely
#   .\install.ps1 -BackendOnly                 # Only venv/backend (Steps
#                                                 1-3, 6) -- skips REAPER
#                                                 integration entirely, so
#                                                 REAPER never needs closing
#   .\install.ps1 -TorchGpu                    # Install PyTorch with CUDA
#   .\install.ps1 -MidigptSrc C:\path\to\MIDI-GPT
# ============================================================================

param(
    [switch]$SkipDeps,
    [switch]$SkipReaperConfig,
    [switch]$ReaperOnly,
    [switch]$BackendOnly,
    [switch]$TorchGpu,
    [string]$MidigptSrc = "",
    [switch]$Help
)

# NOT "Stop" -- Windows PowerShell 5.1 (unlike pwsh 7+) promotes *any*
# stderr output from a native command (git, pip, python -- all used
# throughout this script) into a terminating NativeCommandError under
# "Stop", even when that output is just a warning or an expected failure
# already handled via $LASTEXITCODE below (confirmed against a real
# windows-latest run: `python -c "import torch" 2>$null`, whose whole
# point is to fail silently before PyTorch is installed, still aborted the
# script here). Every native-command result that actually needs to stop
# the install already checks $LASTEXITCODE explicitly and calls
# Write-Fail; every cmdlet call that needs to stop the install (the
# network downloads) already has its own try/catch, which still catches
# real terminating exceptions regardless of this preference.
$ErrorActionPreference = "Continue"

# ── Config ──────────────────────────────────────────────────────
$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $RepoDir ".venv"
$PythonMinVersion = "3.10"
$PythonCmd = ""

# ── Helpers ─────────────────────────────────────────────────────

function Write-Info { param($msg) Write-Host "[INFO] " -ForegroundColor Blue -NoNewline; Write-Host $msg }
function Write-OK   { param($msg) Write-Host "[OK] " -ForegroundColor Green -NoNewline; Write-Host $msg }
function Write-Warn { param($msg) Write-Host "[WARN] " -ForegroundColor Yellow -NoNewline; Write-Host $msg }
function Write-Fail { param($msg) Write-Host "[ERROR] " -ForegroundColor Red -NoNewline; Write-Host $msg; exit 1 }

function Write-Step {
    param($msg)
    Write-Host ""
    Write-Host ("-" * 52) -ForegroundColor White
    Write-Host "  $msg" -ForegroundColor White
    Write-Host ("-" * 52) -ForegroundColor White
}

function Test-Command { param($cmd) $null -ne (Get-Command $cmd -ErrorAction SilentlyContinue) }

function Test-Interactive { -not [Console]::IsInputRedirected }

# Test-only override (see tests/) -- simulates REAPER being open without
# needing a real REAPER process running.
function Test-ReaperRunning {
    if ($env:MIDIGPT_FAKE_REAPER_RUNNING) {
        return $env:MIDIGPT_FAKE_REAPER_RUNNING -eq "true"
    }
    return $null -ne (Get-Process -Name "reaper" -ErrorAction SilentlyContinue)
}

function Test-BuildTools {
    $Missing = @()
    # Windows: need Visual Studio Build Tools + CMake for source installs
    if (-not (Test-Command "cl.exe") -and -not (Test-Command "cmake")) {
        $Missing += "Visual Studio Build Tools + CMake (winget install Microsoft.VisualStudio.2022.BuildTools; winget install Kitware.CMake)"
    }
    if ($Missing.Count -gt 0) {
        Write-Warn "Source install requires compilation tools:"
        foreach ($m in $Missing) { Write-Host "  - $m" }
        return $false
    }
    return $true
}

# ── Microsoft Visual C++ Runtime ────────────────────────────────
# PyTorch's Windows wheels link against the MSVC runtime (vcruntime140_1.dll,
# msvcp140.dll) but don't ship it. Fresh Windows installs often don't have it
# (GitHub's windows-latest runners always do, so CI never sees this), and
# then `pip install torch` succeeds but `import torch` fails with
# "[WinError 126] ... c10.dll or one of its dependencies".
#
# 14.40 minimum: binaries built with MSVC 17.10+ (as current PyTorch releases
# are) can crash inside std::mutex on older runtimes, so an outdated runtime
# is treated the same as a missing one.
$VcRuntimeMinVersion = [version]"14.40"

# The runtime must match the Python that loads torch, not the OS: x64 Python
# runs (emulated) on ARM64 Windows too, and needs the x64 runtime there.
function Get-VcRuntimeArch {
    param([string]$Py)
    $Machine = & $Py -c "import platform; print(platform.machine())" 2>$null
    if ($Machine -eq "ARM64") { return "arm64" }
    return "x64"
}

function Get-VcRuntimeVersion {
    param([string]$Arch)
    foreach ($Key in @(
        "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\$Arch",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\$Arch"
    )) {
        $Rt = Get-ItemProperty -Path $Key -ErrorAction SilentlyContinue
        if ($Rt -and $Rt.Installed -eq 1) {
            return [version]"$($Rt.Major).$($Rt.Minor).$($Rt.Bld)"
        }
    }
    return $null
}

function Test-VcRuntime {
    param([string]$Arch)
    $Ver = Get-VcRuntimeVersion -Arch $Arch
    return ($null -ne $Ver) -and ($Ver -ge $VcRuntimeMinVersion)
}

function Write-VcRuntimeHelp {
    param([string]$Arch = "x64")
    Write-Host ""
    Write-Host "  PyTorch needs the Microsoft Visual C++ Redistributable ($VcRuntimeMinVersion or newer)."
    Write-Host "  Download and run Microsoft's installer, then re-run this installer:"
    Write-Host "    https://aka.ms/vc14/vc_redist.$Arch.exe"
    Write-Host ""
}

# Downloads Microsoft's redistributable, checks its signature, and runs it
# elevated (it installs machine-wide, so UAC is unavoidable). Returns $true
# on success; warns and returns $false on any failure, including the user
# declining the UAC prompt.
function Install-VcRuntime {
    param([string]$Arch)
    $Url = "https://aka.ms/vc14/vc_redist.$Arch.exe"
    $Exe = Join-Path $env:TEMP "vc_redist.$Arch.exe"

    # Windows PowerShell 5.1's progress bar slows Invoke-WebRequest to a crawl
    # on a file this size (~25MB).
    $ProgressPreference = "SilentlyContinue"
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Exe -UseBasicParsing -TimeoutSec 300
    } catch {
        Write-Warn "Failed to download the Visual C++ Runtime installer"
        return $false
    }

    # Unlike ReaPack, this one is Authenticode-signed -- only run it if
    # Windows validates the signature as Microsoft's.
    $Sig = Get-AuthenticodeSignature -FilePath $Exe
    if ($Sig.Status -ne "Valid" -or $Sig.SignerCertificate.Subject -notmatch "O=Microsoft Corporation") {
        Remove-Item $Exe -Force -ErrorAction SilentlyContinue
        Write-Warn "Downloaded Visual C++ Runtime installer isn't validly signed by Microsoft -- discarded"
        return $false
    }

    Write-Info "Installing (Windows will ask for administrator permission)..."
    try {
        $Proc = Start-Process -FilePath $Exe -ArgumentList "/install", "/quiet", "/norestart" -Verb RunAs -Wait -PassThru -ErrorAction Stop
    } catch {
        # Start-Process throws when the UAC prompt is declined.
        Remove-Item $Exe -Force -ErrorAction SilentlyContinue
        Write-Warn "Administrator permission wasn't granted -- Visual C++ Runtime not installed"
        return $false
    }
    Remove-Item $Exe -Force -ErrorAction SilentlyContinue

    switch ($Proc.ExitCode) {
        0    { return $true }
        1638 { return $true }  # a newer version is already installed
        3010 {
            Write-Warn "Visual C++ Runtime installed; Windows recommends a restart (usually not needed to continue)"
            return $true
        }
        default {
            Write-Warn "Visual C++ Runtime installer failed (exit code $($Proc.ExitCode))"
            return $false
        }
    }
}

# Tells "torch isn't installed" apart from "torch is installed but won't
# load" -- they need completely different fixes, and a bare
# `python -c "import torch"` exit code can't distinguish them. Returns
# @{ State = "ok"|"missing"|"broken"; Detail = version or error line }.
function Get-TorchState {
    python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('torch') else 1)" 2>$null
    if ($LASTEXITCODE -ne 0) { return @{ State = "missing"; Detail = "" } }

    $Lines = @(python -c "import torch; print(torch.__version__)" 2>&1 | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
    if ($LASTEXITCODE -eq 0) { return @{ State = "ok"; Detail = $Lines[-1] } }

    # The traceback's final "SomeError: message" line; torch may print its
    # own hints after it, so don't just take the last line.
    $ErrLine = $Lines | Where-Object { $_ -match "^\w+(Error|Exception)\b.*:" } | Select-Object -Last 1
    if (-not $ErrLine) { $ErrLine = $Lines -join " " }
    return @{ State = "broken"; Detail = $ErrLine }
}

# Whether a torch import error is a native DLL failing to load -- on Windows
# almost always the missing/outdated MSVC runtime (see Get-VcRuntimeVersion).
function Test-TorchDllLoadError {
    param([string]$Detail)
    return $Detail -match "WinError 126|WinError 1114|DLL load failed|c10\.dll"
}

# Sets Key=Value in reaper.ini's [reaper] section (Content in, Content out).
function Set-ReaperIniKey {
    param([string]$Key, [string]$Value, [string]$Content)
    # REAPER writes reaper.ini with CRLF; keep whatever the file already
    # uses so no line ends up with a bare LF.
    $Nl = "`r`n"
    if (($Content -match "`n") -and ($Content -notmatch "`r`n")) { $Nl = "`n" }

    # [^\r\n]*, not .*: in .NET, .* also eats the \r of a CRLF line (and
    # (?m)$ only matches before \n), so the replacement would drop it.
    $KeyPattern = "(?m)^$([regex]::Escape($Key))=[^\r\n]*"
    if ($Content -match $KeyPattern) {
        return ($Content -replace $KeyPattern, "$Key=$Value")
    }
    # Explicit IgnoreCase: unlike -match, [regex]::Match is case-sensitive,
    # and REAPER's own header is [reaper]. Missing it meant appending a
    # second, duplicate section, which REAPER never reads (first matching
    # section wins).
    $SectionMatch = [regex]::Match($Content, "(?m)^\[reaper\][ \t]*(?=\r?$)", "IgnoreCase")
    if ($SectionMatch.Success) {
        $InsertAt = $SectionMatch.Index + $SectionMatch.Length
        return $Content.Substring(0, $InsertAt) + "$Nl$Key=$Value" + $Content.Substring($InsertAt)
    }
    # No [reaper] section at all yet (fresh ini) -- append one.
    $Sep = ""
    if ($Content.TrimEnd().Length -gt 0) { $Sep = "$Nl$Nl" }
    return $Content.TrimEnd() + "$Sep[reaper]$Nl$Key=$Value$Nl"
}

# Ask REAPER to quit gracefully (taskkill without /F sends a close request
# to the main window, so REAPER's own "save changes?" prompt still fires --
# never force-killed) and wait for the process to actually exit.
function Invoke-ReaperQuitAndWait {
    Write-Info "Asking REAPER to quit -- any unsaved project will prompt you to save first..."
    try {
        Start-Process -FilePath "taskkill.exe" -ArgumentList "/IM", "reaper.exe" -NoNewWindow -Wait -ErrorAction SilentlyContinue | Out-Null
    } catch {}

    $Waited = 0
    while ((Test-ReaperRunning) -and ($Waited -lt 120)) {
        Start-Sleep -Seconds 2
        $Waited += 2
    }

    if (Test-ReaperRunning) {
        Write-Warn "REAPER is still open (it may be waiting on a save prompt)."
        Read-Host "  Close it manually, then press Enter to continue (Ctrl+C to abort)" | Out-Null
    }
}

function Start-ReaperApp {
    # Test-only override -- simulates REAPER relaunch without real process
    if ($env:MIDIGPT_FAKE_REAPER_RUNNING) {
        Write-Info "Test mode: simulating REAPER relaunch"
        return $true
    }
    $Candidates = @(
        (Join-Path $env:ProgramFiles "REAPER (x64)\reaper.exe"),
        (Join-Path $env:ProgramFiles "REAPER\reaper.exe")
    )
    if (${env:ProgramFiles(x86)}) {
        $Candidates += (Join-Path ${env:ProgramFiles(x86)} "REAPER\reaper.exe")
    }
    foreach ($p in $Candidates) {
        if (Test-Path $p) {
            Start-Process -FilePath $p
            return $true
        }
    }
    Write-Warn "Could not find REAPER's install location to relaunch it automatically -- start it manually."
    return $false
}

function Open-Url { 
    param($Url) 
    try {
        Start-Process $Url | Out-Null
        return $true
    } catch {
        return $false
    }
}

# Installs the complete ReaImGui package directly from codeberg.org,
# replicating what ReaPack does from the ReaTeam Extensions repo (same as
# install.sh's download_reaimgui): the native extension into UserPlugins,
# plus the Python API (imgui.py -- MIDI-GPT.py imports it from
# Scripts\ReaTeam Extensions\API) and the Lua shims.
#
# Checksums: used when codeberg's release API publishes one for a file
# (a `sha256`, or a GitHub-style `digest`, field on the asset). At the time
# of writing it publishes none -- and imgui.lua isn't a release asset at all
# -- so these install unverified, with a warning saying so.
# ReaImGui releases: https://codeberg.org/cfillion/reaimgui/releases
$ReaImGuiVersion = "0.10.0.5"
$ReaImGuiDll = "reaper_imgui-x64.dll"

function Get-ReaImGuiFiles {
    param([string]$ReaperDir)
    $Rel = "https://codeberg.org/cfillion/reaimgui/releases/download/v$ReaImGuiVersion"
    $ApiDir = Join-Path $ReaperDir "Scripts\ReaTeam Extensions\API"
    return @(
        @{ Name = $ReaImGuiDll; Url = "$Rel/$ReaImGuiDll"; Dir = (Join-Path $ReaperDir "UserPlugins"); Required = $true },
        @{ Name = "imgui.py"; Url = "$Rel/imgui.py"; Dir = $ApiDir; Required = $true },
        @{ Name = "imgui.lua"; Url = "https://codeberg.org/cfillion/reaimgui/raw/v$ReaImGuiVersion/shims/imgui.lua"; Dir = $ApiDir; Required = $false },
        @{ Name = "gfx2imgui.lua"; Url = "$Rel/gfx2imgui.lua"; Dir = $ApiDir; Required = $false }
    )
}

# Returns a hashtable of asset name -> expected lowercase SHA256, for the
# assets codeberg publishes one for (possibly none).
function Get-ReaImGuiChecksums {
    $Sums = @{}
    try {
        $Release = Invoke-RestMethod -Uri "https://codeberg.org/api/v1/repos/cfillion/reaimgui/releases/tags/v$ReaImGuiVersion" -TimeoutSec 15
        foreach ($Asset in $Release.assets) {
            $Sha = $null
            if ($Asset.PSObject.Properties["sha256"] -and $Asset.sha256) { $Sha = $Asset.sha256 }
            elseif ($Asset.PSObject.Properties["digest"] -and $Asset.digest) { $Sha = $Asset.digest -replace "^sha256:", "" }
            if ($Sha) { $Sums[$Asset.name] = $Sha.ToLower() }
        }
    } catch {}
    return $Sums
}

# The dashboard needs both the extension DLL and imgui.py; a DLL alone (e.g.
# from an older version of this installer) still leaves `import imgui` failing.
function Test-ReaImGuiInstalled {
    param([string]$ReaperDir)
    foreach ($F in (Get-ReaImGuiFiles -ReaperDir $ReaperDir)) {
        if ($F.Required -and -not (Test-Path (Join-Path $F.Dir $F.Name))) { return $false }
    }
    return $true
}

function Install-ReaImGui {
    param([string]$ReaperDir)

    Write-Info "Installing ReaImGui v$ReaImGuiVersion ($ReaImGuiDll + Python API)..."
    $ProgressPreference = "SilentlyContinue"

    $Checksums = Get-ReaImGuiChecksums
    $Unverified = @()

    foreach ($F in (Get-ReaImGuiFiles -ReaperDir $ReaperDir)) {
        $TmpFile = Join-Path ([System.IO.Path]::GetTempPath()) "midigpt-imgui-$([System.Guid]::NewGuid())"
        try {
            Invoke-WebRequest -Uri $F.Url -OutFile $TmpFile -UseBasicParsing -TimeoutSec 60
        } catch {
            Remove-Item $TmpFile -Force -ErrorAction SilentlyContinue
            Write-Warn "Failed to download $($F.Name) from $($F.Url)"
            if ($F.Required) { return $false } else { continue }
        }

        $ExpectedSha = $Checksums[$F.Name]
        if ($ExpectedSha) {
            $ActualSha = (Get-FileHash -Path $TmpFile -Algorithm SHA256).Hash.ToLower()
            if ($ActualSha -ne $ExpectedSha) {
                Remove-Item $TmpFile -Force -ErrorAction SilentlyContinue
                Write-Warn "$($F.Name) didn't match its published checksum -- discarded (expected $ExpectedSha, got $ActualSha)"
                if ($F.Required) { return $false } else { continue }
            }
        }

        New-Item -ItemType Directory -Path $F.Dir -Force | Out-Null
        try {
            Move-Item -Path $TmpFile -Destination (Join-Path $F.Dir $F.Name) -Force -ErrorAction Stop
        } catch {
            # Windows locks a loaded DLL, e.g. REAPER still open with an
            # older ReaImGui.
            Remove-Item $TmpFile -Force -ErrorAction SilentlyContinue
            Write-Warn "Couldn't write $($F.Name) to $($F.Dir) -- is REAPER still running?"
            if ($F.Required) { return $false } else { continue }
        }
        # Same Mark-of-the-Web clearing as ReaPack, so REAPER can load the
        # DLL without a manual SmartScreen click-through.
        Unblock-File -Path (Join-Path $F.Dir $F.Name) -ErrorAction SilentlyContinue
        if ($ExpectedSha) {
            Write-OK "$($F.Name) installed and checksum-verified"
        } else {
            Write-OK "$($F.Name) installed"
            $Unverified += $F.Name
        }
    }
    if ($Unverified.Count -gt 0) {
        Write-Warn "No published checksum for ReaImGui $($Unverified -join ', ') -- installed unverified"
    }
    return $true
}

# Downloads the Arachno GM SoundFont into this repo's own soundfonts\
# folder (kept alongside the plugin, not scattered into REAPER's resource
# dir), under its real filename -- MIDI-GPT Setup Tracks.py reads
# whatever .sf2 is actually there rather than a hardcoded name, so this
# doesn't need to match anything else exactly. Arachno is freeware and this
# is the exact .zip Arachnosoft's own download page links to (mirrored on
# Dropbox) -- not a third-party scrape. Sforzando itself is a real
# application installer, not a data file, so it's intentionally NOT
# auto-installed the same way (see the instrument-setup prompt below).
# -- Hugging Face access --
# The model checkpoints on Hugging Face are gated: downloading them needs
# an account that accepted the license, and a token saved where
# midigpt-http finds it (~\.cache\huggingface\token).

$HfRepo = "Metacreation/MIDI-GPT"
$HfProbeModel = "yellow_medium"

# Runs a Python snippet from a temp file (Windows PowerShell 5.1 mangles
# double quotes in native-command arguments, so no `python -c`) with
# HF_TOKEN left out: what counts is the saved token, the one the server
# launchers will use. Extra environment variables go in $Env.
function Invoke-HfPython {
    param([string]$Code, [string[]]$PyArgs = @(), [hashtable]$Env = @{})
    $tmp = [System.IO.Path]::GetTempFileName() + ".py"
    Set-Content -Path $tmp -Value $Code -Encoding ASCII
    $savedToken = $env:HF_TOKEN
    Remove-Item Env:HF_TOKEN -ErrorAction SilentlyContinue
    foreach ($k in $Env.Keys) { Set-Item "Env:$k" $Env[$k] }
    try {
        $out = & python $tmp @PyArgs 2>$null
        return @{ Out = ($out | Select-Object -Last 1); Code = $LASTEXITCODE }
    } finally {
        foreach ($k in $Env.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
        if ($null -ne $savedToken) { $env:HF_TOKEN = $savedToken }
        Remove-Item $tmp -ErrorAction SilentlyContinue
    }
}

# Returns ok (the saved token can download), nologin (no token saved),
# gated (the token's account has no access), cached (Hugging Face couldn't
# be reached, but a model is already downloaded), or offline. Access is
# per repo, so one checkpoint is enough to probe.
function Get-HfAccess {
    $code = @'
import glob, os, sys
from huggingface_hub import constants, get_hf_file_metadata, get_token, hf_hub_url
from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError
from midigpt.inference.engine import _resolve_checkpoint_filename
repo, model = sys.argv[1:]
try:
    get_hf_file_metadata(hf_hub_url(repo, _resolve_checkpoint_filename(repo, model)))
    print("ok")
except (GatedRepoError, RepositoryNotFoundError):
    print("gated" if get_token() else "nologin")
except Exception:
    snapshots = os.path.join(constants.HF_HUB_CACHE, "models--" + repo.replace("/", "--"), "snapshots")
    print("cached" if glob.glob(os.path.join(snapshots, "*", "*.safetensors")) else "offline")
'@
    $r = Invoke-HfPython -Code $code -PyArgs @($HfRepo, $HfProbeModel)
    if ($r.Code -ne 0 -or -not $r.Out) { return "offline" }
    return "$($r.Out)".Trim()
}

# Saves a Hugging Face token where midigpt-http finds it. The token is
# passed in the environment, not on a command line.
function Save-HfToken {
    param([string]$Token)
    $code = @'
import os, sys
from huggingface_hub import login
try:
    login(token=os.environ["MIDIGPT_HF_TOKEN"], add_to_git_credential=False)
except Exception as e:
    sys.exit(1)
'@
    $r = Invoke-HfPython -Code $code -Env @{ MIDIGPT_HF_TOKEN = $Token }
    return ($r.Code -eq 0)
}

function Invoke-HfAccess {
    $access = Get-HfAccess
    switch ($access) {
        "ok"      { Write-OK "Hugging Face: access to $HfRepo"; return }
        "cached"  { Write-Warn "Couldn't reach Hugging Face; using the models already downloaded."; return }
        "offline" { Write-Warn "Couldn't reach Hugging Face; the server downloads the model on its first start."; return }
    }
    # No console (CI, or redirected input): use HF_TOKEN if it is set
    if (-not (Test-Interactive)) {
        if ($env:HF_TOKEN -and (Save-HfToken $env:HF_TOKEN)) { $access = Get-HfAccess }
        if ($access -eq "ok") {
            Write-OK "Hugging Face: access to $HfRepo (HF_TOKEN saved)"
        } else {
            Write-Warn "No access to ${HfRepo}: accept its license at https://huggingface.co/$HfRepo,"
            Write-Warn "then run: $VenvDir\Scripts\hf.exe auth login  (or install again with HF_TOKEN set)"
        }
        return
    }
    Write-Host ""
    Write-Host "  The MIDI-GPT models are on Hugging Face and need a free account to download:"
    Write-Host "    1. Sign in at https://huggingface.co and accept the license at"
    Write-Host "       https://huggingface.co/$HfRepo"
    Write-Host "    2. Create an access token at https://huggingface.co/settings/tokens"
    Write-Host "       (type `"Read`" is enough)"
    if ($access -eq "gated") {
        Write-Host "  (A token is saved, but its account has no access yet: accept the license,"
        Write-Host "  or paste another token.)"
    }
    while ($true) {
        $secure = Read-Host "  Paste the token (hidden), or press Enter to skip" -AsSecureString
        $tok = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
        if (-not $tok) {
            if ($access -eq "gated") { $access = Get-HfAccess }
            if ($access -eq "ok") {
                Write-OK "Hugging Face: access to $HfRepo"
            } else {
                Write-Warn "Skipped. The server will say what is missing when it starts;"
                Write-Warn "run this later: $VenvDir\Scripts\hf.exe auth login"
            }
            return
        }
        if (-not (Save-HfToken $tok)) { Write-Warn "That token was refused; try again."; continue }
        $access = Get-HfAccess
        switch ($access) {
            "ok"    { Write-OK "Token saved; access to $HfRepo"; return }
            "gated" {
                Write-Warn "Token saved, but this account has no access yet: accept the license at"
                Write-Warn "https://huggingface.co/$HfRepo, then press Enter."
            }
            default { Write-Warn "Token saved; Hugging Face couldn't be reached to check it."; return }
        }
    }
}

function Install-ArachnoSoundfont {
    $DestDir = Join-Path $RepoDir "soundfonts"
    if (Test-Path $DestDir) {
        $Existing = Get-ChildItem -Path $DestDir -Filter "*.sf2" -ErrorAction SilentlyContinue
        if ($Existing) {
            Write-OK "Arachno SoundFont already present in $DestDir"
            return $true
        }
    }

    Write-Info "Downloading Arachno SoundFont (~140MB, may take a few minutes)..."
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
    $TmpZip = Join-Path ([System.IO.Path]::GetTempPath()) "midigpt-arachno-$([System.Guid]::NewGuid()).zip"

    try {
        Invoke-WebRequest -Uri "https://www.dropbox.com/s/2rnpya9ecb9m4jh/arachno-soundfont-10-sf2.zip?dl=1" `
            -OutFile $TmpZip -UseBasicParsing -TimeoutSec 900
    } catch {
        Write-Warn "Failed to download Arachno SoundFont -- get it manually: https://www.arachnosoft.com/main/download.php?id=soundfont-sf2"
        Remove-Item $TmpZip -Force -ErrorAction SilentlyContinue
        return $false
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip = $null
    try {
        $Zip = [System.IO.Compression.ZipFile]::OpenRead($TmpZip)
        $Entry = $Zip.Entries | Where-Object { $_.Name -like "*.sf2" } | Select-Object -First 1
        if (-not $Entry) {
            Write-Warn "Downloaded archive didn't contain a .sf2 file -- get Arachno manually: https://www.arachnosoft.com/main/download.php?id=soundfont-sf2"
            return $false
        }
        $DestFile = Join-Path $DestDir $Entry.Name
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $DestFile, $true)
        Write-OK "Arachno SoundFont installed: $DestFile"
        return $true
    } catch {
        Write-Warn "Downloaded archive didn't extract cleanly -- get Arachno manually: https://www.arachnosoft.com/main/download.php?id=soundfont-sf2"
        return $false
    } finally {
        if ($Zip) { $Zip.Dispose() }
        Remove-Item $TmpZip -Force -ErrorAction SilentlyContinue
    }
}

# ── Help ────────────────────────────────────────────────────────

if ($Help) {
    Write-Host "MIDI-GPT for REAPER — Windows Installer"
    Write-Host ""
    Write-Host "Usage: .\install.ps1 [OPTIONS]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -SkipDeps            Skip system dependency check (incl. the Visual C++ Runtime)"
    Write-Host "  -SkipReaperConfig    Skip automatic REAPER Python/ReaScript configuration"
    Write-Host "  -ReaperOnly          Only do REAPER integration (Step 4/5: junction, ReaPack,"
    Write-Host "                       ReaImGui, reaper.ini) -- skips venv/backend entirely."
    Write-Host "                       Useful to redo just the REAPER side, or for testing."
    Write-Host "  -BackendOnly         Only do venv/backend (Steps 1-3, 6) -- skips REAPER"
    Write-Host "                       integration entirely, so it never needs REAPER closed."
    Write-Host "                       What update.ps1 uses to refresh the backend in place."
    Write-Host "  -TorchGpu            Install PyTorch with GPU support (CUDA)."
    Write-Host "  -MidigptSrc PATH     Path to MIDI-GPT source repo (sibling folder by default)"
    Write-Host "  -Help                Show this help"
    Write-Host ""
    Write-Host "Examples:"
    Write-Host "  .\install.ps1                              # Full installation (CPU torch)"
    Write-Host "  .\install.ps1 -TorchGpu                    # Full installation with GPU torch"
    Write-Host "  .\install.ps1 -MidigptSrc C:\path\to\MIDI-GPT  # Custom MIDI-GPT source path"
    Write-Host "  .\install.ps1 -ReaperOnly                  # Just (re)do REAPER integration"
    Write-Host "  .\install.ps1 -BackendOnly                 # Just refresh venv/backend"
    exit 0
}

# ── Banner ──────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ╔══════════════════════════════════════╗" -ForegroundColor White
Write-Host "  ║     MIDI-GPT for REAPER Installer    ║" -ForegroundColor White
Write-Host "  ╚══════════════════════════════════════╝" -ForegroundColor White
Write-Host ""
Write-Info "Platform: Windows"

if ($ReaperOnly) {
    Write-Step "Skipping system deps / venv / backend (-ReaperOnly)"
    # Still need a python to detect the ReaScript library path in Step 5.
    foreach ($cmd in @("python3", "python")) {
        if (Test-Command $cmd) {
            $PyMinorCheck = & $cmd -c "import sys; print(sys.version_info.minor)" 2>$null
            if ($LASTEXITCODE -eq 0 -and [int]$PyMinorCheck -ge 10) {
                $PythonCmd = $cmd
                break
            }
        }
    }
}

# ====================================================================
# Step 1: System Dependencies
# ====================================================================

if (-not $ReaperOnly) {

if (-not $SkipDeps) {
    Write-Step "Step 1/6: Checking system dependencies"

    $Missing = @()

    # -- Python --
    foreach ($cmd in @("python3", "python")) {
        if (Test-Command $cmd) {
            $PyVer = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            $PyMajor = & $cmd -c "import sys; print(sys.version_info.major)" 2>$null
            $PyMinor = & $cmd -c "import sys; print(sys.version_info.minor)" 2>$null
            if ([int]$PyMajor -ge 3 -and [int]$PyMinor -ge 10) {
                $PythonCmd = $cmd
                break
            }
        }
    }

    if (-not $PythonCmd) {
        $Missing += "python>=3.10"
        Write-Warn "Python >= $PythonMinVersion not found"
    } else {
        Write-OK "Python $PyVer ($PythonCmd)"
    }

    # -- git --
    if (Test-Command "git") {
        Write-OK "git found"
    } else {
        $Missing += "git"
        Write-Warn "git not found"
    }

    # -- Install missing deps --
    if ($Missing.Count -gt 0) {
        Write-Host ""
        Write-Warn "Missing dependencies: $($Missing -join ', ')"
        Write-Host ""

        $Installer = $null
        if (Test-Command "winget") { $Installer = "winget" }
        elseif (Test-Command "choco") { $Installer = "choco" }

        if ($Installer) {
            Write-Info "Installing via $Installer..."
            foreach ($dep in $Missing) {
                switch ($dep) {
                    "python>=3.10" {
                        if ($Installer -eq "winget") { winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements }
                        else { choco install python312 -y }
                    }
                    "git" {
                        if ($Installer -eq "winget") { winget install Git.Git --accept-package-agreements --accept-source-agreements }
                        else { choco install git -y }
                    }
                }
            }

            # Refresh PATH after install
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

            if (-not $PythonCmd) {
                foreach ($cmd in @("python3", "python")) {
                    if (Test-Command $cmd) {
                        $PyMinor = & $cmd -c "import sys; print(sys.version_info.minor)" 2>$null
                        if ([int]$PyMinor -ge 10) {
                            $PythonCmd = $cmd
                            break
                        }
                    }
                }
            }
        } else {
            Write-Host ""
            Write-Host "Please install the missing dependencies manually:"
            Write-Host ""
            Write-Host "  Option 1 (winget - built into Windows 11):"
            Write-Host "    winget install Python.Python.3.12"
            Write-Host "    winget install Git.Git"
            Write-Host ""
            Write-Host "  Option 2 (chocolatey - https://chocolatey.org/):"
            Write-Host "    choco install python312 git -y"
            Write-Host ""
            Write-Fail "Please install missing dependencies and re-run"
        }
    }

    if (-not $PythonCmd) { Write-Fail "Python >= $PythonMinVersion required but not found" }

    # -- Microsoft Visual C++ Runtime (see Get-VcRuntimeVersion) --
    $VcArch = Get-VcRuntimeArch -Py $PythonCmd
    $VcVer = Get-VcRuntimeVersion -Arch $VcArch
    if (Test-VcRuntime -Arch $VcArch) {
        Write-OK "Microsoft Visual C++ Runtime $VcVer"
    } else {
        if ($VcVer) {
            Write-Warn "Microsoft Visual C++ Runtime $VcVer is too old (PyTorch needs $VcRuntimeMinVersion or newer)"
        } else {
            Write-Warn "Microsoft Visual C++ Runtime not found (PyTorch needs it)"
        }

        if (Test-Interactive) {
            $InstallVc = Read-Host "  Download and install it from Microsoft now? [Y/n]"
            if ($InstallVc -notmatch "^[Nn]") {
                if ((Install-VcRuntime -Arch $VcArch) -and (Test-VcRuntime -Arch $VcArch)) {
                    Write-OK "Microsoft Visual C++ Runtime $(Get-VcRuntimeVersion -Arch $VcArch) installed"
                }
            }
        }

        if (-not (Test-VcRuntime -Arch $VcArch)) {
            Write-VcRuntimeHelp -Arch $VcArch
            Write-Fail "Microsoft Visual C++ Runtime required but not installed"
        }
    }

    Write-OK "All system dependencies satisfied"

} else {
    Write-Step "Step 1/6: Skipping dependency check (-SkipDeps)"
    foreach ($cmd in @("python3", "python")) {
        if (Test-Command $cmd) {
            $PyMinor = & $cmd -c "import sys; print(sys.version_info.minor)" 2>$null
            if ([int]$PyMinor -ge 10) {
                $PythonCmd = $cmd
                break
            }
        }
    }
    if (-not $PythonCmd) { Write-Fail "Python >= $PythonMinVersion required but not found" }
}

# ====================================================================
# Step 2: Virtual Environment + PyTorch
# ====================================================================

Write-Step "Step 2/6: Setting up Python virtual environment"

if (Test-Path $VenvDir) {
    Write-Info "Existing venv found at $VenvDir"
    & "$VenvDir\Scripts\Activate.ps1"
    Write-OK "Activated existing venv"
} else {
    Write-Info "Creating venv with $PythonCmd..."
    & $PythonCmd -m venv $VenvDir
    & "$VenvDir\Scripts\Activate.ps1"
    # `python -m pip install --upgrade pip`, not `pip install --upgrade
    # pip` -- Windows refuses to let pip.exe overwrite itself while it's
    # the running executable ("To modify pip, please run the following
    # command: ... -m pip install --upgrade pip").
    python -m pip install --upgrade pip setuptools wheel -q
    Write-OK "Created and activated venv at $VenvDir"
}

Write-Info "Checking PyTorch..."
$Torch = Get-TorchState
$TorchWasInstalled = $Torch.State -ne "missing"
if ($Torch.State -eq "missing") {
    Write-Info "Installing PyTorch (this may take a few minutes)..."
    if ($TorchGpu) {
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
    } else {
        pip install torch
    }
    $Torch = Get-TorchState
}

if ($Torch.State -eq "ok") {
    if ($TorchWasInstalled) { Write-OK "PyTorch $($Torch.Detail) already installed" }
    else { Write-OK "PyTorch $($Torch.Detail) installed" }
} elseif ($Torch.State -eq "broken") {
    # Installed fine, but fails on import -- reinstalling torch won't help,
    # so don't send the user down the "no wheel for your Python" path.
    Write-Host ""
    Write-Warn "PyTorch is installed but fails to load:"
    Write-Host "    $($Torch.Detail)"
    if (Test-TorchDllLoadError -Detail $Torch.Detail) {
        # Almost always the MSVC runtime -- e.g. when Step 1 was skipped
        # with -SkipDeps, or the runtime was removed after a previous install.
        Write-VcRuntimeHelp -Arch (Get-VcRuntimeArch -Py "python")
        Write-Fail "PyTorch can't load its DLLs -- install the Visual C++ Runtime and re-run"
    }
    Write-Host ""
    Write-Host "  Try reinstalling it with this venv activated, then re-run this installer:"
    Write-Host "    .\.venv\Scripts\Activate.ps1"
    Write-Host "    pip install --force-reinstall torch"
    Write-Host ""
    Write-Fail "PyTorch installation is broken. See instructions above."
} else {
    Write-Host ""
    Write-Warn "PyTorch could not be installed automatically."
    Write-Host ""
    Write-Host "  This usually means there is no pre-built PyTorch wheel for your"
    Write-Host "  Python version. Please install PyTorch manually:"
    Write-Host ""
    Write-Host "  1. Visit: https://pytorch.org/get-started/locally/"
    Write-Host "  2. Select your OS, package manager (pip), and Python version"
    Write-Host "  3. Run the install command it gives you WITH THIS VENV ACTIVATED:"
    Write-Host "       .\.venv\Scripts\Activate.ps1"
    Write-Host "       pip install <command-from-pytorch-org>"
    Write-Host "  4. Then re-run this installer (it will detect existing torch)"
    Write-Host ""
    Write-Fail "PyTorch installation failed. See instructions above."
}

# ====================================================================
# Step 3: Install MIDI-GPT Backend
# ====================================================================

Write-Step "Step 3/6: Installing MIDI-GPT backend"

$MidigptSibling = Join-Path (Split-Path $RepoDir -Parent) "MIDI-GPT"

if ($MidigptSrc -and (Test-Path $MidigptSrc)) {
    Write-Info "Installing midigpt[http,inference] from source: $MidigptSrc ..."
    Test-BuildTools | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Fail "Missing build tools required for source install" }
    pip install -e "${MidigptSrc}[http,inference]" 2>&1
} else {
    Write-Info "Installing midigpt[http,inference] from PyPI ..."
    pip install "midigpt[http,inference]" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "PyPI install failed — falling back to cloning MIDI-GPT from GitHub ..."
        if (-not (Test-Path (Join-Path $MidigptSibling ".git"))) {
            git clone https://github.com/Metacreation-Lab/MIDI-GPT.git $MidigptSibling
            if ($LASTEXITCODE -ne 0) { Write-Fail "Failed to clone MIDI-GPT. Check your internet connection." }
        } else {
            Write-Info "Existing MIDI-GPT clone found at $MidigptSibling"
        }
        pip install -e "${MidigptSibling}[http,inference]" 2>&1
        if ($LASTEXITCODE -ne 0) { Write-Fail "Source install from cloned MIDI-GPT also failed." }
    }
}

python -c "from midigpt.inference.engine import InferenceEngine" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-OK "midigpt backend installed successfully"
} else {
    Write-Fail "midigpt backend installation failed."
}

Invoke-HfAccess

} # ReaperOnly == false (Steps 1-3)

# $ReaperWasClosedByUs is referenced unconditionally later (the ImGui
# relaunch check) so it must be defined even under -BackendOnly, which
# skips the block below that would otherwise set it.
$ReaperWasClosedByUs = $false

if (-not $BackendOnly) {

# ====================================================================
# Step 4: REAPER Integration (Scripts junction, ReaPack, ReaImGui)
# ====================================================================

Write-Step "Step 4/6: Setting up REAPER integration"

if ($env:MIDIGPT_REAPER_DIR) {
    # Test-only override (see tests/) -- lets the REAPER integration logic
    # run against a disposable fake directory instead of the real REAPER
    # install, so different starting states (empty, ReaPack already
    # present, existing reaper.ini content, etc.) can be exercised
    # repeatably without ever touching a real machine's REAPER.
    $ReaperDir = $env:MIDIGPT_REAPER_DIR
} else {
    $ReaperDir = Join-Path $env:APPDATA "REAPER"
}

if (Test-Path $ReaperDir) {
    # Installing ReaPack and configuring reaper.ini (Step 5) both need
    # REAPER closed. Ask once, up front, so both steps can run this pass
    # instead of telling the user to re-run the installer later.
    if (Test-ReaperRunning) {
        if (Test-Interactive) {
            Write-Warn "REAPER is currently running."
            Write-Host "  Installing ReaPack and configuring REAPER (reaper.ini) both require REAPER"
            Write-Host "  to be closed. Nothing is discarded silently -- REAPER will prompt you to"
            Write-Host "  save any unsaved project first, same as quitting normally."
            $CloseReaper = Read-Host "  Close REAPER now and continue? [y/N]"
            if ($CloseReaper -match "^[Yy]$") {
                Invoke-ReaperQuitAndWait
                if (-not (Test-ReaperRunning)) {
                    $ReaperWasClosedByUs = $true
                }
            } else {
                Write-Warn "Continuing with REAPER open -- ReaPack install and reaper.ini setup will be skipped this run."
            }
        } else {
            Write-Warn "REAPER is currently running -- ReaPack install and reaper.ini setup will be skipped (non-interactive)."
            Write-Host "  Close REAPER, then re-run this installer:"
            Write-Host "    .\install.ps1"
        }
    }

    # -- Scripts junction --
    $ScriptsSrc = Join-Path $RepoDir "src\Scripts\MIDI-GPT"
    $ScriptsDst = Join-Path $ReaperDir "Scripts\MIDI-GPT"
    if (Test-Path $ScriptsSrc) {
        $DstParent = Split-Path $ScriptsDst -Parent
        if (-not (Test-Path $DstParent)) { New-Item -ItemType Directory -Path $DstParent -Force | Out-Null }
        if (Test-Path $ScriptsDst) {
            cmd /c "rmdir `"$ScriptsDst`"" 2>$null
            Remove-Item $ScriptsDst -Recurse -Force -ErrorAction SilentlyContinue
        }
        cmd /c "mklink /J `"$ScriptsDst`" `"$ScriptsSrc`"" | Out-Null
        Write-OK "REAPER Scripts junction created"
    }

    # -- ReaPack + ReaImGui --
    $ReapackReady = $false
    $UserPluginsDir = Join-Path $ReaperDir "UserPlugins"
    $ExistingReapack = $null
    if (Test-Path $UserPluginsDir) {
        $ExistingReapack = Get-ChildItem -Path $UserPluginsDir -Filter "reaper_reapack*" -ErrorAction SilentlyContinue
    }

    if ($ExistingReapack) {
        Write-OK "ReaPack already installed"
        $ReapackReady = $true
    } elseif (Test-ReaperRunning) {
        Write-Warn "ReaPack not installed, and REAPER is still open -- skipping (re-run after closing REAPER, or install manually: https://reapack.com/)"
    } else {
        Write-Info "Installing ReaPack..."
        $ReapackAsset = "reaper_reapack-x64.dll"
        $ReapackUrl = "https://github.com/cfillion/reapack/releases/latest/download/$ReapackAsset"
        New-Item -ItemType Directory -Path $UserPluginsDir -Force | Out-Null
        $ReapackDest = Join-Path $UserPluginsDir $ReapackAsset

        # ReaPack's own releases aren't code-signed, so there's no
        # signature to verify -- fetch GitHub's published SHA256 for this
        # exact asset instead, so we can at least catch a corrupted or
        # tampered-with download before trusting it.
        $ExpectedSha = $null
        try {
            # Unauthenticated API calls share a 60/hour limit per IP (CI
            # runners share IPs); a GITHUB_TOKEN in the environment (CI sets
            # one) raises that to 1000/hour.
            $ApiHeaders = @{}
            if ($env:GITHUB_TOKEN) { $ApiHeaders["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
            $Release = Invoke-RestMethod -Uri "https://api.github.com/repos/cfillion/reapack/releases/latest" -Headers $ApiHeaders -TimeoutSec 15
            $Asset = $Release.assets | Where-Object { $_.name -eq $ReapackAsset }
            if ($Asset -and $Asset.digest) {
                $ExpectedSha = ($Asset.digest -replace "^sha256:", "").ToLower()
            }
        } catch {
        }
        if (-not $ExpectedSha) {
            Write-Warn "Could not fetch an expected checksum for ReaPack -- installing unverified"
        }

        try {
            Invoke-WebRequest -Uri $ReapackUrl -OutFile $ReapackDest -UseBasicParsing -TimeoutSec 120
            $ReapackVerified = $true
            if ($ExpectedSha) {
                $ActualSha = (Get-FileHash -Path $ReapackDest -Algorithm SHA256).Hash.ToLower()
                if ($ActualSha -ne $ExpectedSha) { $ReapackVerified = $false }
            }

            if ($ReapackVerified) {
                # A downloaded, unsigned DLL can be blocked by SmartScreen
                # (the Windows equivalent of macOS quarantine) until the
                # user manually clicks through it. Clear the Mark-of-the-Web
                # zone identifier ourselves, now that the checksum above
                # confirms it's what GitHub actually published.
                Unblock-File -Path $ReapackDest -ErrorAction SilentlyContinue
                if ($ExpectedSha) {
                    Write-OK "ReaPack installed and checksum-verified ($ReapackAsset)"
                } else {
                    Write-OK "ReaPack installed, unverified ($ReapackAsset)"
                }
                $ReapackReady = $true
            } else {
                Remove-Item $ReapackDest -Force -ErrorAction SilentlyContinue
                Write-Warn "Downloaded ReaPack didn't match GitHub's published checksum -- discarded. Install manually: https://reapack.com/"
            }
        } catch {
            Write-Warn "Failed to download ReaPack -- install manually: https://reapack.com/"
        }
    }

    if (Test-ReaImGuiInstalled -ReaperDir $ReaperDir) {
        Write-OK "ReaImGui already installed"
    } else {
        if (Install-ReaImGui -ReaperDir $ReaperDir) {
            $ReapackReady = $true
        } elseif ($ReapackReady) {
            Write-Warn "ReaImGui not installed - manual installation required:"
            Write-Host "  In REAPER: Extensions > ReaPack > Browse packages > search 'ReaImGui' > install > restart REAPER"
            Write-Host "  This also installs the other packages in the 'ReaTeam Extensions' repo (ReaBlink, ReaMCULive, js_ReaScriptAPI)"
        } else {
            Write-Warn "ReaImGui extension not found - the dashboard UI needs it"
            Write-Host "  In REAPER: Extensions > ReaPack > Browse packages > search 'ReaImGui' > install > restart REAPER"
        }
    }
} else {
    Write-Warn "REAPER config directory not found — REAPER may not be installed yet"
    Write-Host "  Install REAPER: https://www.reaper.fm/download.php"
    Write-Host "  Launch REAPER once, quit it, then re-run this installer:"
    Write-Host "    .\install.ps1"
}

# ====================================================================
# Step 5: Configure REAPER for Python / ReaScript
# ====================================================================

if ($SkipReaperConfig) {
    Write-Step "Step 5/6: Skipping REAPER config (-SkipReaperConfig)"
} else {
    Write-Step "Step 5/6: Configuring REAPER (reaper.ini)"

    $ReaperIni = Join-Path $ReaperDir "reaper.ini"
    $PyCmdForDll = "python3"
    if ($PythonCmd) { $PyCmdForDll = $PythonCmd }

    # base_exec_prefix, not exec_prefix: Step 2 activated the venv, so
    # $PyCmdForDll ("python") is now the venv's interpreter, whose
    # exec_prefix is .venv -- which has no pythonXY.dll. REAPER needs the
    # base install's DLL (same thing outside a venv, e.g. -ReaperOnly).
    $PythonDll = & $PyCmdForDll -c @"
import sys, pathlib
base = pathlib.Path(sys.base_exec_prefix)
ver = f'{sys.version_info.major}{sys.version_info.minor}'
for p in base.glob(f'python{ver}.dll'):
    print(p); break
"@ 2>$null

    if (Test-Path $ReaperIni) {
        if (Test-ReaperRunning) {
            Write-Warn "REAPER is currently running!"
            Write-Host "  REAPER overwrites reaper.ini on quit, so changes would be lost."
            Write-Host "  Please quit REAPER and re-run this installer, or configure manually:"
            Write-Host "    Options > Preferences > Plug-Ins > ReaScript"
            if ($PythonDll) { Write-Host "    Python library: $PythonDll" }
        } elseif ($PythonDll -and (Test-Path $PythonDll)) {
            Copy-Item $ReaperIni "$ReaperIni.midigpt-backup" -Force
            Write-Info "Backed up reaper.ini -> reaper.ini.midigpt-backup"

            # REAPER stores reaper.ini as UTF-8 (no BOM); Get-Content/
            # Set-Content in Windows PowerShell 5.1 default to the ANSI
            # codepage. That round trip happens to be lossless on
            # Windows-1252 systems, but on a multi-byte ANSI codepage (e.g.
            # Japanese) it would mangle non-ASCII paths in the file.
            $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
            $IniContent = [System.IO.File]::ReadAllText($ReaperIni, $Utf8NoBom)

            # Same two keys as install.sh writes on macOS/Linux, matching
            # REAPER's two ReaScript preference fields: pythonlibpath64 is
            # the *directory* ("Custom path to Python dll directory") and
            # pythonlibdll64 just the *file name* ("Force ReaScript to use
            # specific Python .dll"). A full path in pythonlibdll64 alone
            # leaves REAPER with "No compatible version of Python was found".
            $PyLibDir = Split-Path $PythonDll -Parent
            $PyLibFile = Split-Path $PythonDll -Leaf
            $IniContent = Set-ReaperIniKey -Key "reascript" -Value "1" -Content $IniContent
            $IniContent = Set-ReaperIniKey -Key "pythonlibpath64" -Value $PyLibDir -Content $IniContent
            $IniContent = Set-ReaperIniKey -Key "pythonlibdll64" -Value $PyLibFile -Content $IniContent

            [System.IO.File]::WriteAllText($ReaperIni, $IniContent, $Utf8NoBom)

            if (($IniContent -match "(?m)^reascript=1") -and ($IniContent -match "(?m)^pythonlibpath64=") -and ($IniContent -match "(?m)^pythonlibdll64=")) {
                Write-OK "ReaScript enabled (reascript=1)"
                Write-OK "Python library: $PythonDll"
            } else {
                Write-Warn "Failed to write ReaScript/Python settings to reaper.ini"
                Write-Host "  Configure manually: Options > Preferences > Plug-Ins > ReaScript"
                Write-Host "    Python library: $PythonDll"
            }
        } else {
            Write-Warn "Could not detect Python DLL path"
            Write-Host "  You'll need to configure this manually in REAPER:"
            Write-Host "    Options > Preferences > Plug-Ins > ReaScript"
        }
    } else {
        if (Test-Path $ReaperDir) {
            Write-Warn "reaper.ini not found — REAPER may not have been launched yet"
            Write-Host "  Launch REAPER once, quit it, then re-run this installer to auto-configure."
        } else {
            Write-Warn "REAPER config directory not found — REAPER may not be installed"
            Write-Host "  Install REAPER: https://www.reaper.fm/download.php"
            Write-Host "  Launch REAPER once, quit it, then re-run this installer:"
            Write-Host "    .\install.ps1"
        }
        if ($PythonDll) {
            Write-Host ""
            Write-Host "  Manual REAPER configuration required:"
            Write-Host "  1. Open REAPER"
            Write-Host "  2. Options > Preferences > Plug-Ins > ReaScript"
            Write-Host "  3. Enable 'ReaScript' (checkbox)"
            Write-Host "  4. Set 'Custom path to Python dll directory' to:"
            Write-Host "       $(Split-Path $PythonDll -Parent)" -ForegroundColor Green
            Write-Host "     and 'Force ReaScript to use specific Python .dll' to:"
            Write-Host "       $(Split-Path $PythonDll -Leaf)" -ForegroundColor Green
            Write-Host "  5. Click OK, then RESTART REAPER for changes to take effect."
        }
    }
}

# Check if we need to launch REAPER for ImGui install (either we closed it, or
# ImGui bootstrap was written and REAPER isn't running)
$NeedReaperForImGui = $false
if ($ReaperWasClosedByUs -or $ImGuiBootstrapWritten) {
    if (-not (Test-ReaperRunning)) {
        $NeedReaperForImGui = $true
    }
}

if ($NeedReaperForImGui) {
    Write-Info "Launching REAPER to install ReaImGui via ReaPack..."
    if (Start-ReaperApp) {
        Write-OK "REAPER launched -- waiting for ReaImGui to install (up to 120s)..."
        # Poll for ImGui binary in UserPlugins
        $Waited = 0
        $ImGuiFound = $false
        while ($Waited -lt 120) {
            $ImGuiCheck = Get-ChildItem -Path $UserPluginsDir -Filter "*imgui*" -ErrorAction SilentlyContinue
            if ($ImGuiCheck) {
                $ImGuiFound = $true
                break
            }
            Start-Sleep -Seconds 5
            $Waited += 5
        }
        if ($ImGuiFound) {
            Write-OK "ReaImGui installed successfully"
        } else {
            Write-Warn "ReaImGui not detected yet (may still be installing in background)"
        }
        # Close REAPER gracefully so user starts fresh
        Invoke-ReaperQuitAndWait
        Write-Info "REAPER closed. Setup complete — start REAPER when ready to use MIDI-GPT."
    }
}

} # BackendOnly == false (Steps 4-5)

if (-not $ReaperOnly) {

# ====================================================================
# Step 6: Verify Backend Installation
# ====================================================================

Write-Step "Step 6/6: Verifying backend installation"

python -c "from midigpt.inference.engine import InferenceEngine" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-OK "Verification successful: midigpt is installed and functional"
} else {
    Write-Fail "Verification failed: midigpt could not be imported"
}

# ====================================================================
# Create Desktop shortcut to server launcher
# ====================================================================

$DesktopDir = [Environment]::GetFolderPath("Desktop")
if (Test-Path $DesktopDir) {
    $ShortcutPath = Join-Path $DesktopDir "Start MIDI-GPT Server.lnk"
    $ServerBat = Join-Path $RepoDir "Start Server - Windows.bat"
    if (Test-Path $ServerBat) {
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = $ServerBat
        $Shortcut.WorkingDirectory = $RepoDir
        $Shortcut.Description = "Start the MIDI-GPT inference server for REAPER"
        $Shortcut.Save()
        Write-OK "Desktop shortcut created: Start MIDI-GPT Server.lnk"
    }
} else {
    Write-Info "No Desktop folder found — skipping shortcut creation"
}

} # ReaperOnly == false (Step 6 + Desktop shortcut)

# ====================================================================
# Final: Summary and Next Steps
# ====================================================================

Write-Host ""
Write-Host ("=" * 52) -ForegroundColor White
if ($BackendOnly) {
    Write-Host "  Backend Updated!" -ForegroundColor Green
} else {
    Write-Host "  Installation Complete!" -ForegroundColor Green
}
Write-Host ("=" * 52) -ForegroundColor White
Write-Host ""

# $ReaperDir is only ever set inside the Step 4 block above, which
# -BackendOnly skips entirely -- nothing below this point may reference it
# (or anything else REAPER-side) unguarded.
if (-not $BackendOnly) {
Write-Host "Next steps in REAPER:" -ForegroundColor White
Write-Host ""
Write-Host "  1. Load the dashboard as a ReaScript action:"
Write-Host "     Actions > Show Action List > Load ReaScript"
Write-Host "     Select: $ReaperDir\Scripts\MIDI-GPT\MIDI-GPT.py"
Write-Host ""
Write-Host "  2. Run 'MIDI-GPT.py' — it's a single window for the whole"
Write-Host "     workflow (global options, per-track controls, running generation)."
Write-Host "     Needs the ReaImGui extension -- see the warning above if it's missing."
Write-Host "     Worth binding it to a toolbar button or keyboard shortcut, since"
Write-Host "     it's the only action you'll use day to day."
Write-Host ""
Write-Host "  If the MIDI-GPT server runs on a different machine, click 'Change...'"
Write-Host "  next to the server address in the dashboard and enter its IP/domain"
Write-Host "  and port (e.g. http://192.168.1.20:3456). Defaults to"
Write-Host "  http://127.0.0.1:3456."
Write-Host ""
} # BackendOnly == false (Next steps in REAPER)
Write-Host "To start the server:" -ForegroundColor White
if (Test-Path (Join-Path ([Environment]::GetFolderPath("Desktop")) "Start MIDI-GPT Server.lnk")) {
    Write-Host "  Double-click " -NoNewline
    Write-Host "Start MIDI-GPT Server" -ForegroundColor Green -NoNewline
    Write-Host " on your Desktop"
} else {
    Write-Host "  Double-click: " -NoNewline
    Write-Host "Start Server - Windows.bat" -ForegroundColor Green
}
Write-Host "  Or from terminal: cd $RepoDir; .\.venv\Scripts\Activate.ps1; midigpt-http"
Write-Host ""

# ====================================================================
# Interactive: Instrument setup (Sforzando + Arachno)
# ====================================================================

# A one-time setup question, not something a -BackendOnly refresh
# (update.ps1) should re-ask every single time it runs.
if ((Test-Interactive) -and (-not $BackendOnly)) {
    Write-Host ""
    Write-Host ("-" * 52) -ForegroundColor White
    Write-Host "  Optional: Instrument Setup (Sforzando + Arachno)" -ForegroundColor White
    Write-Host ("-" * 52) -ForegroundColor White
    Write-Host ""
    Write-Host "  MIDI-GPT tracks play through Sforzando (a free SFZ sampler) loaded"
    Write-Host "  with the Arachno General MIDI SoundFont -- see VST.md for the full"
    Write-Host "  setup."
    Write-Host ""
    Write-Host "  Sforzando is a real application installer (not just a data file),"
    Write-Host "  behind its own download page, so this installer opens that page for"
    Write-Host "  you rather than running an installer on your behalf."
    $OpenSfz = Read-Host "  Open the Sforzando download page in your browser now? [y/N]"
    if ($OpenSfz -match "^[Yy]$") {
        if (Open-Url "https://www.plogue.com/products/sforzando.html") {
            Write-OK "Opened the Sforzando download page"
        } else {
            Write-Warn "Could not open browser automatically"
            Write-Host "  Visit manually: https://www.plogue.com/products/sforzando.html"
        }
    }
    Write-Host ""
    Write-Host "  Arachno is just a SoundFont data file, so this installer can fetch"
    Write-Host "  it directly, into this repo's own soundfonts\ folder."
    $DlArachno = Read-Host "  Download the Arachno GM SoundFont (~140MB) now? [y/N]"
    if ($DlArachno -match "^[Yy]$") {
        Install-ArachnoSoundfont | Out-Null
    }
}

# ====================================================================
# Interactive: Launch server now?
# ====================================================================

# MIDIGPT_SKIP_LAUNCH_PROMPT: set by update.ps1 while it calls this script
# with -BackendOnly, so only update.ps1's own (more update-specific) copy
# of this same question runs instead of both back to back.
if ((Test-Interactive) -and (-not $ReaperOnly) -and (-not $env:MIDIGPT_SKIP_LAUNCH_PROMPT)) {
    Write-Host ""
    Write-Host ("-" * 52) -ForegroundColor White
    Write-Host "  Launch Server" -ForegroundColor White
    Write-Host ("-" * 52) -ForegroundColor White
    Write-Host ""
    Write-Host "  Would you like to start the MIDI-GPT server now?"
    Write-Host ""
    $Launch = Read-Host "  Launch server? [Y/n]"
    if (-not $Launch) { $Launch = "y" }

    if ($Launch -match "^[Yy]$") {
        Write-Host ""
        Write-Host "  Select a model:" -ForegroundColor White
        Write-Host ""
        Write-Host "    [1] Yellow     - General purpose, recommended (yellow_medium)"
        Write-Host "    [2] Prism      - Extended controls (prism_medium)"
        Write-Host "    [3] Expressive - Microtiming + velocity (expressive_medium)"
        Write-Host ""
        $ModelChoice = Read-Host "  Model [1/2/3, default=1]"

        switch ($ModelChoice) {
            "2" { $Model = "prism_medium"; $Label = "Prism" }
            "3" { $Model = "expressive_medium"; $Label = "Expressive" }
            default { $Model = "yellow_medium"; $Label = "Yellow" }
        }

        Write-Host ""
        Write-Host "  Starting MIDI-GPT server ($Label)..." -ForegroundColor White
        Write-Host "  Keep this window open while using MIDI-GPT in REAPER."
        Write-Host "  Press Ctrl+C to stop the server."
        Write-Host ""
        midigpt-http --pretrained $Model
    } else {
        Write-Host ""
        Write-Host "Next steps:" -ForegroundColor White
        Write-Host "  Start the server later with:"
        Write-Host "    cd $RepoDir; .\.venv\Scripts\Activate.ps1; midigpt-http" -ForegroundColor Green
        Write-Host ""
    }
} elseif ($env:MIDIGPT_INTERACTIVE) {
    Write-Host ""
    Read-Host "Press Enter to close this window" | Out-Null
}
