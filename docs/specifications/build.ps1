[CmdletBinding()]
param(
    [string]$PlantUmlJar = $env:PLANTUML_JAR,
    [string]$Tectonic = "tectonic",
    [string]$Python = "python",
    [string]$Java = "java"
)

$ErrorActionPreference = "Stop"
if (-not $PlantUmlJar -or -not (Test-Path -LiteralPath $PlantUmlJar -PathType Leaf)) {
    throw "Pass -PlantUmlJar with a local PlantUML JAR path (tested: 1.2025.4)."
}
$PlantUmlJar = (Resolve-Path -LiteralPath $PlantUmlJar).Path
foreach ($tool in @($Tectonic, $Python, $Java)) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "Required documentation tool not found: $tool"
    }
}

Push-Location $PSScriptRoot
try {
    New-Item -ItemType Directory -Force -Path "generated", "output", "diagrams\rendered" | Out-Null
    & $Python "inventory.py"
    if ($LASTEXITCODE -ne 0) { throw "Source inventory generation failed." }

    $diagrams = @(Get-ChildItem -LiteralPath "diagrams" -Filter "*.puml" |
        Where-Object { $_.Name -ne "theme.puml" } | Sort-Object Name)
    foreach ($format in @("png", "svg")) {
        foreach ($diagram in $diagrams) {
            $renderPath = Join-Path "diagrams\rendered" "$($diagram.BaseName).$format"
            if (Test-Path -LiteralPath $renderPath) {
                Remove-Item -LiteralPath $renderPath
            }
            & $Java "-DPLANTUML_LIMIT_SIZE=16384" "-Djava.awt.headless=true" `
                -jar $PlantUmlJar "-t$format" -charset UTF-8 -failfast2 -o rendered $diagram.FullName
            if ($LASTEXITCODE -ne 0) { throw "PlantUML failed: $($diagram.Name) ($format)." }
            if (-not (Test-Path -LiteralPath $renderPath -PathType Leaf) -or
                (Get-Item -LiteralPath $renderPath).Length -eq 0) {
                throw "PlantUML produced no output: $($diagram.Name) ($format)."
            }
        }
    }
    foreach ($document in @("srs", "sdd")) {
        & $Tectonic --keep-logs --keep-intermediates --outdir output "$document.tex"
        if ($LASTEXITCODE -ne 0) { throw "LaTeX compilation failed: $document.tex" }
        $log = Get-Content -LiteralPath "output\$document.log" -Raw
        if ($log -match "There were undefined references|Citation .* undefined|Reference .* undefined|Overfull \\[hv]box") {
            throw "Unresolved references or overflowing content in output\$document.log"
        }
    }
    Write-Host "Built both PDFs and $($diagrams.Count) diagrams (PNG and SVG) locally."
}
finally {
    Pop-Location
}
