<#
  Exports git-tracked source files into one Markdown file per folder.
  Run from the repository root.

  Examples:
    .\export-repo-md.ps1
    .\export-repo-md.ps1 -Out C:\temp\export
    .\export-repo-md.ps1 -Include "app/voice_notes_agent"
#>
param(
    [string]   $Root    = ".",
    [string]   $Out     = "./_export",
    [string[]] $Include = @(),
    [string[]] $Skip    = @("uv.lock", "*.png", "*.jpg", "*.gif", "*.ico", "*.woff*", "*.pdf")
)

$ErrorActionPreference = "Stop"
Set-Location $Root

# PS 5.1's -Encoding utf8 emits a BOM; write UTF-8 without one.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
function Write-Utf8 {
    param([string]$Path, [string]$Text)
    if (-not [System.IO.Path]::IsPathRooted($Path)) { $Path = Join-Path (Get-Location).Path $Path }
    [System.IO.File]::WriteAllText([System.IO.Path]::GetFullPath($Path), $Text, $utf8NoBom)
}

$langMap = @{
    ".py" = "python"; ".js" = "javascript"; ".ts" = "typescript"; ".json" = "json"
    ".html" = "html"; ".css" = "css"; ".sql" = "sql"; ".toml" = "toml"
    ".yml" = "yaml"; ".yaml" = "yaml"; ".sh" = "bash"; ".ps1" = "powershell"
    ".md" = "markdown"; ".env" = "ini"; ".cfg" = "ini"; ".ini" = "ini"
}

# Mask values of anything that looks like a credential.
$secretKey = '(?i)(key|secret|token|password|passwd|credential|conn|dsn|sa_|private)'

function Get-Redacted {
    param([string]$Path, [string]$Text)
    $name = Split-Path $Path -Leaf
    if ($name -notmatch '^\.env' -and $name -notmatch '\.env$') { return $Text }
    $lines = $Text -split "`r?`n"
    $outLines = foreach ($line in $lines) {
        if ($line -match '^\s*([A-Za-z0-9_]+)\s*=(.*)$') {
            $k = $Matches[1]; $v = $Matches[2]
            if ($k -match $secretKey -and $v.Trim().Length -gt 0) { "$k=<redacted>" } else { $line }
        } else { $line }
    }
    return ($outLines -join "`n")
}

$files = git ls-files
if ($LASTEXITCODE -ne 0) { throw "Not a git repository: $Root" }

$files = $files | Where-Object {
    $f = $_
    $skipIt = $false
    foreach ($pat in $Skip) { if ($f -like $pat -or (Split-Path $f -Leaf) -like $pat) { $skipIt = $true } }
    if ($Include.Count -gt 0) {
        $inIt = $false
        foreach ($inc in $Include) { if ($f -like "$inc*") { $inIt = $true } }
        if (-not $inIt) { $skipIt = $true }
    }
    -not $skipIt
}

if (-not (Test-Path $Out)) { New-Item -ItemType Directory -Path $Out | Out-Null }

$groups = $files | Group-Object { $d = Split-Path $_ -Parent; if ([string]::IsNullOrEmpty($d)) { "_root" } else { $d.Replace("\", "/") } }

$branch = (git rev-parse --abbrev-ref HEAD)
$sha    = (git rev-parse --short HEAD)
$manifest = New-Object System.Collections.ArrayList

foreach ($g in $groups) {
    $folder  = $g.Name
    $mdName  = ($folder -replace '[\\/]', '-') + ".md"
    $mdPath  = Join-Path $Out $mdName
    $sb      = New-Object System.Text.StringBuilder

    [void]$sb.AppendLine("# $folder")
    [void]$sb.AppendLine()
    [void]$sb.AppendLine("branch: ``$branch``  commit: ``$sha``  files: $($g.Count)")
    [void]$sb.AppendLine()

    foreach ($f in ($g.Group | Sort-Object)) {
        # Read as UTF-8 explicitly. PS 5.1's Get-Content defaults to the ANSI
        # codepage, which mangles every non-ASCII byte (emoji in index.html
        # came through as mojibake before this).
        $full = $f
        if (-not [System.IO.Path]::IsPathRooted($full)) {
            $full = Join-Path (Get-Location) $full
        }
        $text = [System.IO.File]::ReadAllText($full, [System.Text.Encoding]::UTF8)
        if ($null -eq $text) { $text = "" }
        $text = Get-Redacted -Path $f -Text $text
        $ext  = [System.IO.Path]::GetExtension($f).ToLower()
        $lang = $langMap[$ext]
        if (-not $lang) { $lang = "text" }
        $lineCount = ($text -split "`r?`n").Count

        [void]$sb.AppendLine("<!-- FILE: $f -->")
        [void]$sb.AppendLine('````' + $lang)
        [void]$sb.AppendLine($text.TrimEnd())
        [void]$sb.AppendLine('````')
        [void]$sb.AppendLine("<!-- END: $f -->")
        [void]$sb.AppendLine()

        [void]$manifest.Add(("{0,6}  {1}" -f $lineCount, $f))
    }

    Write-Utf8 -Path $mdPath -Text $sb.ToString()
    Write-Host ("wrote {0}  ({1} files)" -f $mdName, $g.Count)
}

$mf = @("# manifest", "", "branch: ``$branch``  commit: ``$sha``", "", '```') + $manifest + @('```')
Write-Utf8 -Path (Join-Path $Out "_manifest.md") -Text ($mf -join "`n")
Write-Host ("`ndone -> {0}" -f (Resolve-Path $Out))
