<#
  Three-way comparison for the AIML-2130 merge decision.

  BASE   = the pre-fix baseline, extracted from local git (default f6baf25,
           which is the reconstruction of the lead's 3ecd956)
  OURS   = the working tree at .\sell-n-tell (baseline + our 2698 fixes)
  THEIRS = the lead's new branch, imported to .\sell-n-tell-lead

  Reports, per file: who touched it, and the overlap set that needs a manual
  merge decision. Line endings are normalised before comparing (repo is CRLF,
  the reconstructed copies are LF), so only real content changes show up.

  Example:
    .\tools\compare-trees.ps1
    .\tools\compare-trees.ps1 -BaseRef f6baf25 -Theirs .\sell-n-tell-lead
#>
param(
    [string] $Root    = "C:\Personal Storage\poc\sellNtell",
    [string] $BaseRef = "f6baf25",
    [string] $Ours    = "sell-n-tell",
    [string] $Theirs  = "sell-n-tell-lead",
    [string] $Work    = "_compare"
)

$ErrorActionPreference = "Stop"
Set-Location $Root

$oursPath   = Join-Path $Root $Ours
$theirsPath = Join-Path $Root $Theirs
$basePath   = Join-Path $Root (Join-Path $Work "base")

if (-not (Test-Path $theirsPath)) {
    throw "No lead tree at $theirsPath. Import the export first."
}

# --- extract the baseline from git -----------------------------------------
if (Test-Path $basePath) { Remove-Item $basePath -Recurse -Force }
New-Item -ItemType Directory -Path $basePath -Force | Out-Null

$zip = Join-Path $Root (Join-Path $Work "base.zip")
if (Test-Path $zip) { Remove-Item $zip -Force }
git archive $BaseRef -o $zip -- sell-n-tell
if ($LASTEXITCODE -ne 0) { throw "git archive failed for $BaseRef" }
Expand-Archive -LiteralPath $zip -DestinationPath $basePath -Force
Remove-Item $zip -Force
# git archive keeps the sell-n-tell/ prefix; flatten it
$basePath = Join-Path $basePath "sell-n-tell"

# --- helpers ----------------------------------------------------------------
# Compare on normalised content: CRLF -> LF, trailing whitespace trimmed.
function Get-Norm {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    $t = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    return ($t -replace "`r`n", "`n").TrimEnd()
}

function Get-Rel {
    param([string]$Base)
    if (-not (Test-Path $Base)) { return @() }
    $skip = '\\(__pycache__|\.git|docs|_export|_compare)\\|\.pyc$'
    Get-ChildItem $Base -Recurse -File |
        Where-Object { $_.FullName -notmatch $skip } |
        ForEach-Object { $_.FullName.Substring($Base.Length).TrimStart('\') }
}

$all = @(Get-Rel $basePath) + @(Get-Rel $oursPath) + @(Get-Rel $theirsPath) |
       Sort-Object -Unique

$rows = foreach ($rel in $all) {
    $b = Get-Norm (Join-Path $basePath   $rel)
    $o = Get-Norm (Join-Path $oursPath   $rel)
    $t = Get-Norm (Join-Path $theirsPath $rel)

    $weChanged   = ($o -ne $b)
    $theyChanged = ($t -ne $b)

    $status =
        if     ($weChanged -and $theyChanged) { "BOTH" }
        elseif ($theyChanged)                 { "THEIRS" }
        elseif ($weChanged)                   { "OURS" }
        else                                  { "same" }

    [pscustomobject]@{
        Status    = $status
        File      = $rel
        BaseLines = if ($null -ne $b) { ($b -split "`n").Count } else { 0 }
        OursLines = if ($null -ne $o) { ($o -split "`n").Count } else { 0 }
        TheirLines= if ($null -ne $t) { ($t -split "`n").Count } else { 0 }
    }
}

$order = @{ "BOTH" = 0; "THEIRS" = 1; "OURS" = 2; "same" = 3 }
$rows = $rows | Sort-Object { $order[$_.Status] }, File

Write-Host ""
Write-Host "BASE   $BaseRef  ->  $basePath"
Write-Host "OURS   $oursPath"
Write-Host "THEIRS $theirsPath"
Write-Host ""
$rows | Format-Table -AutoSize | Out-String -Width 200 | Write-Host

$both = @($rows | Where-Object Status -eq "BOTH")
Write-Host ("summary: {0} both, {1} theirs-only, {2} ours-only, {3} unchanged" -f
    $both.Count,
    @($rows | Where-Object Status -eq "THEIRS").Count,
    @($rows | Where-Object Status -eq "OURS").Count,
    @($rows | Where-Object Status -eq "same").Count)

if ($both.Count -gt 0) {
    Write-Host ""
    Write-Host "CONFLICT SET - both sides touched these, decide each by hand:"
    $both | ForEach-Object { Write-Host ("  " + $_.File) }
    Write-Host ""
    Write-Host "Diff a file with:"
    Write-Host ("  git diff --no-index `"{0}\<file>`" `"{1}\<file>`"" -f $basePath, $theirsPath)
}
