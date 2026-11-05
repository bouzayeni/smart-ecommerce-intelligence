<#
.SYNOPSIS
    Evaluate every measure of the open Power BI Desktop model and compare it with the SQL
    reconciliation targets.

.DESCRIPTION
    1. Finds the Analysis Services instance started by Power BI Desktop (port file in
       %LOCALAPPDATA%\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces).
    2. Reports any measure whose DAX does not compile ($SYSTEM.TMSCHEMA_MEASURES).
    3. Runs EVALUATE ROW(...) for each target in reconciliation_targets.json and compares.
    Exit code 0 = all checks pass, 1 = at least one failure.

.EXAMPLE
    powershell -NoProfile -File powerbi\tools\Invoke-DaxChecks.ps1
#>
param(
    [string]$TargetsPath = (Join-Path $PSScriptRoot "..\documentation\reconciliation_targets.json"),
    [string]$AdomdPath = "C:\Program Files\Microsoft Power BI Desktop\bin\Microsoft.PowerBI.AdomdClient.dll",
    [string]$ResultsPath = (Join-Path $PSScriptRoot "..\documentation\dax_check_results.json")
)
$ErrorActionPreference = "Stop"

$workspaces = Join-Path $env:LOCALAPPDATA "Microsoft\Power BI Desktop\AnalysisServicesWorkspaces"
$portFile = Get-ChildItem $workspaces -Recurse -Filter "msmdsrv.port.txt" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $portFile) { throw "No running Power BI Desktop model found (open the .pbip first)." }
$port = ([System.IO.File]::ReadAllText($portFile.FullName) -replace "[^\d]", "")

Add-Type -Path $AdomdPath
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port")
$conn.Open()

function Invoke-Query([string]$query) {
    $cmd = $conn.CreateCommand()
    $cmd.CommandText = $query
    $reader = $cmd.ExecuteReader()
    $rows = @()
    while ($reader.Read()) {
        $row = @{}
        for ($i = 0; $i -lt $reader.FieldCount; $i++) { $row[$reader.GetName($i)] = $reader.GetValue($i) }
        $rows += $row
    }
    $reader.Close()
    return $rows
}

$failures = 0
$broken = Invoke-Query "SELECT [Name], [State], [ErrorMessage] FROM `$SYSTEM.TMSCHEMA_MEASURES WHERE [State] <> 1"
foreach ($m in $broken) {
    Write-Host ("DAX ERROR  {0}: {1}" -f $m["Name"], $m["ErrorMessage"]) -ForegroundColor Red
    $failures++
}
$measureCount = (Invoke-Query "SELECT [Name] FROM `$SYSTEM.TMSCHEMA_MEASURES").Count
Write-Host ("{0} measures in model, {1} with DAX errors" -f $measureCount, $broken.Count)

$targets = (Get-Content $TargetsPath -Raw -Encoding UTF8 | ConvertFrom-Json).targets
$results = @()
foreach ($t in $targets) {
    $status = "PASS"; $actual = $null; $err = $null
    try {
        $actual = (Invoke-Query ("EVALUATE ROW ( ""v"", {0} )" -f $t.dax))[0].Values | Select-Object -First 1
        if ($null -eq $t.expected) {
            if (-not ($null -eq $actual -or $actual -is [System.DBNull])) { $status = "FAIL" }
        } elseif ($null -eq $actual -or $actual -is [System.DBNull]) {
            $status = "FAIL"
        } elseif ([math]::Abs([double]$actual - [double]$t.expected) -gt [double]$t.tolerance) {
            $status = "FAIL"
        }
    } catch {
        $status = "ERROR"; $err = $_.Exception.Message
    }
    if ($status -ne "PASS") { $failures++ }
    $color = @{ PASS = "Green"; FAIL = "Red"; ERROR = "Red" }[$status]
    Write-Host ("{0,-5} {1,-62} expected={2,-18} actual={3}" -f $status, $t.check, $t.expected, $(if ($err) { $err } else { $actual })) -ForegroundColor $color
    $results += [pscustomobject]@{ check = $t.check; status = $status; expected = $t.expected; actual = $actual; error = $err }
}
$conn.Close()

$summary = [pscustomobject]@{
    checked_at = (Get-Date).ToUniversalTime().ToString("s") + "Z"
    measures = $measureCount; dax_errors = $broken.Count
    checks = $results.Count; failures = $failures; results = $results
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -Path $ResultsPath -Encoding UTF8
Write-Host ("{0} checks, {1} failures. Results: {2}" -f $results.Count, $failures, $ResultsPath)
exit $(if ($failures -eq 0) { 0 } else { 1 })
