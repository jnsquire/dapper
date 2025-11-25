param(
    [string]$InputDir = "doc/reference/diagrams",
    [string]$OutputDir = "doc/reference/images",
    [switch]$Force
)

if (-not (Test-Path $InputDir)) {
    Write-Error "Input directory '$InputDir' not found."
    exit 1
}
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$npx = Get-Command npx -ErrorAction SilentlyContinue
if (-not $npx) {
    Write-Host "npx not found in PATH. Install Node.js / npm to use npx and render diagrams (npm i -g npm)." -ForegroundColor Red
    exit 2
}

Get-ChildItem -Path $InputDir -Filter "*.mmd" | ForEach-Object {
    $in = $_.FullName
    $out = Join-Path $OutputDir ($_.BaseName + ".svg")

    $render = $false
    if ($Force) { $render = $true }
    elseif (-not (Test-Path $out)) { $render = $true }
    else {
        $inTime = (Get-Item $in).LastWriteTimeUtc
        $outTime = (Get-Item $out).LastWriteTimeUtc
        if ($inTime -gt $outTime) { $render = $true }
    }

    if (-not $render) {
        Write-Host "Skipping up-to-date: $in -> $out"
        return
    }

    Write-Host "Rendering $in -> $out"
    & npx -p @mermaid-js/mermaid-cli mmdc -i $in -o $out
}
