# Records a SHA-256 checksum of every game file in game-manifest.txt. The game data itself
# can't go to GitHub, but the manifest can, so git shows whenever a game file changes.
#   .\tools\game-manifest.ps1           update the manifest
#   .\tools\game-manifest.ps1 -Verify   list files that differ from the manifest
param([switch]$Verify)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$game = Join-Path $root 'Need For Speed Most Wanted Black Edition'
$manifest = Join-Path $root 'game-manifest.txt'

# Logs and saves change on every play session.
$saves = Join-Path $game 'SAVE\'
$files = Get-ChildItem $game -Recurse -File |
    Where-Object { $_.Extension -ne '.log' -and -not $_.FullName.StartsWith($saves) } |
    Sort-Object FullName
$current = foreach ($f in $files) {
    $rel = $f.FullName.Substring($game.Length + 1).Replace('\', '/')
    '{0}  {1}' -f (Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower(), $rel
}

if ($Verify) {
    $diff = Compare-Object (Get-Content $manifest) $current
    if (-not $diff) { Write-Output 'All game files match the manifest.'; return }
    foreach ($d in $diff) {
        $side = if ($d.SideIndicator -eq '=>') { 'now   ' } else { 'before' }
        Write-Output "$side $($d.InputObject)"
    }
    exit 1
}

$current | Out-File $manifest -Encoding utf8
Write-Output "Wrote $($current.Count) entries to $manifest"
