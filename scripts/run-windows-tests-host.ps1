param(
    [Parameter(Mandatory = $true)]
    [string]$RepoPath,

    [string]$PytestArgsFile,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = 'Stop'

function Invoke-CmdWithTimeout {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [int]$TimeoutSeconds = 10
    )

    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/c", $Command) -PassThru -WindowStyle Hidden
    $completed = $proc.WaitForExit($TimeoutSeconds * 1000)
    if (-not $completed) {
        try {
            $proc.Kill()
        }
        catch {}
        return 124
    }
    return $proc.ExitCode
}

function Test-PytestAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Command
    )

    $exe = $Command[0]
    $baseArgs = @()
    if ($Command.Length -gt 1) {
        $baseArgs = $Command[1..($Command.Length - 1)]
    }

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $exe @baseArgs -c "import pytest" 1> $null 2> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

if (-not (Test-Path -Path $RepoPath)) {
    throw "Repository path not found: $RepoPath"
}

$effectivePytestArgs = @()
if ($PytestArgs) {
    $effectivePytestArgs += $PytestArgs
}
if ($PytestArgsFile) {
    if (-not (Test-Path -Path $PytestArgsFile)) {
        throw "Pytest args file not found: $PytestArgsFile"
    }
    $fileArgs = Get-Content -Path $PytestArgsFile
    if ($fileArgs) {
        $effectivePytestArgs += $fileArgs
    }
}

$mappedDriveName = $null
if ($RepoPath.StartsWith("\\\\")) {
    $candidateLetters = @("Z", "Y", "X", "W", "V", "U", "T")
    foreach ($candidate in $candidateLetters) {
        $drive = "${candidate}:"
        if (-not (Test-Path -Path $drive)) {
            $mapExit = Invoke-CmdWithTimeout -Command "net use $drive `"$RepoPath`" /persistent:no" -TimeoutSeconds 10
            if ($mapExit -eq 0) {
                $mappedDriveName = $drive
                $RepoPath = "${drive}\\"
                break
            }
        }
    }
}

if ($RepoPath.StartsWith("\\\\")) {
    throw "Failed to map UNC repo path to a temporary drive letter: $RepoPath"
}

Set-Location -Path $RepoPath

if (-not $env:DAPPER_SKIP_JS_TESTS_IN_CONFTEST) {
    $env:DAPPER_SKIP_JS_TESTS_IN_CONFTEST = "1"
}
if (-not $env:DAPPER_SKIP_JS_TESTS) {
    $env:DAPPER_SKIP_JS_TESTS = "1"
}
if (-not $env:DAPPER_PYTEST_FORCE_OS_EXIT) {
    $env:DAPPER_PYTEST_FORCE_OS_EXIT = "1"
}

try {
    if ((Get-Command py -ErrorAction SilentlyContinue) -and (Test-PytestAvailable @("py", "-3"))) {
        & py -m pytest @effectivePytestArgs
        exit $LASTEXITCODE
    }

    if ((Get-Command python -ErrorAction SilentlyContinue) -and (Test-PytestAvailable @("python"))) {
        & python -m pytest @effectivePytestArgs
        exit $LASTEXITCODE
    }

    if (Get-Command uv -ErrorAction SilentlyContinue) {
        if (-not $env:UV_PROJECT_ENVIRONMENT) {
            $env:UV_PROJECT_ENVIRONMENT = ".venv-win"
        }
        & uv run pytest @effectivePytestArgs
        exit $LASTEXITCODE
    }

    throw "No suitable Python launcher found on Windows host (uv, py, or python)."
}
finally {
    if ($mappedDriveName) {
        $null = Invoke-CmdWithTimeout -Command "net use $mappedDriveName /delete /y" -TimeoutSeconds 10
    }
}
