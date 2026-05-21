# Building a simple ZIP (Windows)

This project can be built into an EXE and zipped for distribution.

## Prerequisites
- .NET 8 SDK installed

## Fast path (recommended)
From PowerShell in the repo root:

```powershell
./build-and-zip.ps1
```

This creates:
- `dist/publish-win-x64/` (published EXE and dependencies)
- `dist/PunchPacketPageMaker-win-x64.zip` (ready-to-share ZIP)

## Manual equivalent
```powershell
dotnet publish .\PunchPacketPageMaker.csproj -c Release -r win-x64 --self-contained false -o .\dist\publish-win-x64
Compress-Archive -Path .\dist\publish-win-x64\* -DestinationPath .\dist\PunchPacketPageMaker-win-x64.zip
```

## Notes
- `--self-contained false` keeps the ZIP small, but requires .NET 8 runtime on target machines.
- If you need no runtime dependency, use `--self-contained true` (larger ZIP).
