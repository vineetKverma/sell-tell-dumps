<#
  Reconstructs a source tree from the Markdown files produced by export-repo-md.ps1.

  Examples:
    .\import-repo-md.ps1 -In .\_export -Dest .\sell-n-tell
    .\import-repo-md.ps1 -In .\_export -Dest .\sell-n-tell -WhatIfOnly
#>
param(
    [string] $In          = "./_export",
    [string] $Dest        = "./sell-n-tell",
    [switch] $WhatIfOnly
)

$ErrorActionPreference = "Stop"

# PS 5.1's -Encoding utf8 emits a BOM; write UTF-8 without one.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$mdFiles = Get-ChildItem -LiteralPath $In -Filter *.md | Where-Object { $_.Name -ne "_manifest.md" }
if (-not $mdFiles) { throw "No markdown files found in $In" }

$written = 0
foreach ($md in $mdFiles) {
    # -Encoding UTF8 is NOT optional. PS 5.1's Get-Content defaults to the
    # ANSI codepage, which decoded the UTF-8 export as Windows-1252 and turned
    # every emoji into mojibake on the way back in (🎙️ -> ðŸŽ™ï¸). The export
    # side already reads and writes UTF-8 explicitly; this was the one hop that
    # didn't. Repair an affected tree with scripts/pr5/fix_mojibake.py.
    $lines = Get-Content -LiteralPath $md.FullName -Encoding UTF8
    $i = 0
    while ($i -lt $lines.Count) {
        if ($lines[$i] -match '^<!--\s*FILE:\s*(.+?)\s*-->$') {
            $relPath = $Matches[1]
            $i++
            # opening fence
            if ($i -lt $lines.Count -and $lines[$i] -match '^`{3,}') { $i++ }

            $body = New-Object System.Collections.ArrayList
            while ($i -lt $lines.Count -and $lines[$i] -notmatch ('^<!--\s*END:\s*' + [regex]::Escape($relPath) + '\s*-->$')) {
                [void]$body.Add($lines[$i])
                $i++
            }
            # drop trailing closing fence
            while ($body.Count -gt 0 -and $body[$body.Count - 1] -match '^`{3,}\s*$') {
                $body.RemoveAt($body.Count - 1)
            }

            $target = Join-Path $Dest ($relPath -replace '/', '\')
            $parent = Split-Path $target -Parent

            if ($WhatIfOnly) {
                Write-Host ("would write {0,6} lines -> {1}" -f $body.Count, $relPath)
            } else {
                if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
                $full = $target
                if (-not [System.IO.Path]::IsPathRooted($full)) { $full = Join-Path (Get-Location) $full }
                [System.IO.File]::WriteAllText($full, (($body -join "`n") + "`n"), $utf8NoBom)
                Write-Host ("wrote {0,6} lines -> {1}" -f $body.Count, $relPath)
            }
            $written++
        }
        $i++
    }
}

Write-Host ("`n{0} file(s) processed from {1}" -f $written, (Resolve-Path $In))
