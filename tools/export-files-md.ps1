<#
  Exports the named files, exactly as they are, into one Markdown file:
  each file's path, SHA-256 and full content. Nothing is masked or trimmed,
  so the files can be restored byte for byte (the checksum proves it).
  Run from the repository root.

  Examples:
    .\export-files-md.ps1 -Files app/main.py, tests/test_x.py
    .\export-files-md.ps1 -Out C:\tmp\bundle\files.md -Files app/a.py, app/b.py
#>
param(
    [Parameter(Mandatory = $true)]
    [string[]] $Files,
    [string]   $Root = ".",
    [string]   $Out  = "./_export/files.md"
)

$ErrorActionPreference = "Stop"
Set-Location $Root

# PS 5.1's -Encoding utf8 emits a BOM; write UTF-8 without one.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
function Write-Utf8 {
    param([string]$Path, [string]$Text)
    if (-not [System.IO.Path]::IsPathRooted($Path)) { $Path = Join-Path (Get-Location).Path $Path }
    $dir = Split-Path ([System.IO.Path]::GetFullPath($Path)) -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    [System.IO.File]::WriteAllText([System.IO.Path]::GetFullPath($Path), $Text, $utf8NoBom)
}

# Six backticks, so a file that itself contains ``` or ```` can't end a block.
$fence  = '``````'
$branch = (git rev-parse --abbrev-ref HEAD)
$sha    = (git rev-parse --short HEAD)
$sha256 = [System.Security.Cryptography.SHA256]::Create()
$sb     = New-Object System.Text.StringBuilder

[void]$sb.AppendLine("# files")
[void]$sb.AppendLine()
[void]$sb.AppendLine("branch: ``$branch``  commit: ``$sha``  files: $($Files.Count)")
[void]$sb.AppendLine()

foreach ($f in $Files) {
    $full = $f
    if (-not [System.IO.Path]::IsPathRooted($full)) { $full = Join-Path (Get-Location) $full }
    if (-not (Test-Path $full)) { throw "Not found: $f" }

    # Bytes first: the checksum is of the file exactly as it is on disk.
    $bytes = [System.IO.File]::ReadAllBytes($full)
    $hash  = ($sha256.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join ""
    $text  = [System.Text.Encoding]::UTF8.GetString($bytes)
    $path  = $f.Replace("\", "/")

    [void]$sb.AppendLine("<!-- FILE: $path -->")
    [void]$sb.AppendLine("sha256: $hash")
    [void]$sb.AppendLine($fence)
    # Exact content: no trimming. The newline before the closing fence is the
    # block's own and is removed again when the file is restored.
    [void]$sb.Append($text)
    [void]$sb.Append("`n")
    [void]$sb.AppendLine($fence)
    [void]$sb.AppendLine("<!-- END: $path -->")
    [void]$sb.AppendLine()

    Write-Host ("added {0}  ({1} bytes)" -f $path, $bytes.Length)
}

Write-Utf8 -Path $Out -Text $sb.ToString()
Write-Host ("`ndone -> {0}  ({1} files)" -f (Resolve-Path $Out), $Files.Count)
