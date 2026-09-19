param([string]$Source = '', [string]$CodexHome = '', [string]$BinDir = '', [string]$Codex = 'codex', [switch]$NoTrust, [switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$Python = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { throw 'Python 3.11+ must be available as python on PATH for native hooks.' }
& $Python -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'
if ($LASTEXITCODE -ne 0) { throw 'Python check failed.' }
$Temp = $null
try {
    if ($Source) { $Installer = Join-Path $Source 'scripts/install.py' }
    else {
        $Temp = Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString())
        New-Item -ItemType Directory -Path $Temp | Out-Null
        $Installer = Join-Path $Temp 'install.py'
        Invoke-WebRequest 'https://raw.githubusercontent.com/lmtlssss/JustMyType/v0.3.0/scripts/install.py' -OutFile $Installer
    }
    $Arguments = @($Installer, '--codex', $Codex)
    if ($Source) { $Arguments += @('--source', $Source) }
    if ($CodexHome) { $Arguments += @('--codex-home', $CodexHome) }
    if ($BinDir) { $Arguments += @('--bin-dir', $BinDir) }
    if ($NoTrust) { $Arguments += '--no-trust' }
    if ($Uninstall) { $Arguments += '--uninstall' }
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'JustMyType installer stopped.' }
} finally {
    if ($Temp) { Remove-Item -Recurse -Force -LiteralPath $Temp }
}
