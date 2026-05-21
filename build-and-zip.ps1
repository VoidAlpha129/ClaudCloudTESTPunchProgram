param(
  [string]$Runtime = "win-x64",
  [string]$Configuration = "Release",
  [string]$OutputRoot = "dist"
)

$ErrorActionPreference = "Stop"

$publishDir = Join-Path $OutputRoot "publish-$Runtime"
$zipPath = Join-Path $OutputRoot "PunchPacketPageMaker-$Runtime.zip"

if (Test-Path $publishDir) { Remove-Item -Recurse -Force $publishDir }
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }

# Framework-dependent build keeps output small; requires .NET runtime on target machine.
dotnet publish .\PunchPacketPageMaker.csproj `
  -c $Configuration `
  -r $Runtime `
  --self-contained false `
  -o $publishDir

Compress-Archive -Path (Join-Path $publishDir '*') -DestinationPath $zipPath

Write-Host "Created: $zipPath"
