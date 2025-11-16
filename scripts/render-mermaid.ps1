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

# Check for mmdc, fall back to npx if available
$mmdc = Get-Command mmdc -ErrorAction SilentlyContinue
$npx = Get-Command npx -ErrorAction SilentlyContinue

if ($mmdc) {
    $useNpx = $false
    Write-Host "Using mmdc at $($mmdc.Source)"
} elseif ($npx) {
    $useNpx = $true
    Write-Host "mmdc not found; will use npx to run @mermaid-js/mermaid-cli"
} else {
    Write-Host "Neither mmdc nor npx found in PATH. Install mermaid-cli globally (npm i -g @mermaid-js/mermaid-cli) or install Node.js to use npx." -ForegroundColor Red
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
    if ($useNpx) {
        & npx -p @mermaid-js/mermaid-cli mmdc -i $in -o $out
    } else {
        & $mmdc.Source -i $in -o $out
    }
}
