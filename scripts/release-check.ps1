param(
  [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $root
try {
  function Invoke-Checked([string]$Label, [scriptblock]$Command) {
    Write-Host $Label
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Label failed" }
  }

  Write-Host "Checking submodules..."
  $submoduleStatus = @(git submodule status --recursive)
  if ($LASTEXITCODE -ne 0) { throw "Submodule check failed" }
  $uninitialized = @($submoduleStatus | Where-Object { $_ -match '^-' })
  if ($uninitialized.Count -gt 0) {
    $uninitialized | ForEach-Object { Write-Host "UNINITIALIZED: $_" }
    throw "Initialize all submodules before running release checks"
  }

  Invoke-Checked "Auditing release-candidate files..." {
    python scripts/repository-audit.py
  }

  $repositories = @(".", "core/AutoRealize", "core/MLEvolve-Alter", "core/AutoReport")
  foreach ($repository in $repositories) {
    Invoke-Checked "Checking whitespace in $repository..." {
      git -C $repository diff --check
      if ($LASTEXITCODE -eq 0) { git -C $repository diff --cached --check }
    }
  }

  Write-Host "Checking required release files..."
  $required = @(
    "README.md", "docs/THIRD_PARTY_NOTICES.md", "docs/release-checklist.md",
    "core/AutoRealize/config/config.yaml", "core/MLEvolve-Alter/config/config.yaml",
    "core/AutoReport/config/config.yaml"
  )
  foreach ($file in $required) {
    if (-not (Test-Path -LiteralPath $file)) { throw "missing required file: $file" }
  }

  if (-not $SkipTests) {
    Invoke-Checked "Running Gateway tests..." {
      python -m pytest frontend/backend/tests -q
    }
    Invoke-Checked "Checking Gateway Python syntax..." {
      python -m ruff check frontend/backend --select E9,F63,F7,F82
    }

    Push-Location core/AutoRealize
    try {
      Invoke-Checked "Running AutoRealize tests..." { python -m pytest -q }
      Invoke-Checked "Checking AutoRealize Python syntax..." {
        python -m ruff check autorealize tests --select E9,F63,F7,F82
      }
    } finally {
      Pop-Location
    }

    Push-Location core/MLEvolve-Alter
    try {
      Invoke-Checked "Running MLEvolve tests..." { python -m pytest -q }
      Invoke-Checked "Checking MLEvolve Python syntax..." {
        python -m ruff check agents config engine llm utils run.py service_api.py tests --select E9,F63,F7,F82
      }
    } finally {
      Pop-Location
    }

    Push-Location core/AutoReport
    try {
      Invoke-Checked "Running AutoReport tests..." { python -m pytest -q }
      Invoke-Checked "Checking AutoReport Python syntax..." {
        python -m ruff check autoreport service_api.py tests --select E9,F63,F7,F82
      }
    } finally {
      Pop-Location
    }

    Push-Location frontend/ui
    try {
      Invoke-Checked "Running frontend tests..." { npm run test }
      Invoke-Checked "Building frontend..." { npm run build }
    } finally {
      Pop-Location
    }
  }

  if (-not (Test-Path -LiteralPath "LICENSE")) {
    Write-Warning "BLOCKER: LICENSE is missing. Upstream MLEvolve permission must be resolved before public release."
  }
  Write-Host "Local checks completed. Full-history secret cleanup remains a manual release blocker."
} finally {
  Pop-Location
}
