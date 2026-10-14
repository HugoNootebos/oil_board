# Installs (or updates) the OIL relay on this Windows computer: it starts at
# every login and keeps running. The Windows counterpart of install.sh; see
# README.md in this folder for the rest of the setup. In PowerShell, in the
# game folder:
#
#   powershell -ExecutionPolicy Bypass -File packaging\relay\install.ps1                the relay only
#   powershell -ExecutionPolicy Bypass -File packaging\relay\install.ps1 NAME TOKEN     + keep NAME.duckdns.org pointing here
#   powershell -ExecutionPolicy Bypass -File packaging\relay\install.ps1 -Remove        stop it and take it out again
param([string]$Name, [string]$Token, [switch]$Remove)

$ErrorActionPreference = "Stop"
$Dir = Join-Path $env:LOCALAPPDATA "OIL-relay"
$Log = Join-Path $Dir "oil-relay.log"
$Shortcut = Join-Path ([Environment]::GetFolderPath("Startup")) "OIL relay.lnk"
$Port = 47800

function Stop-Relay {
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
        Where-Object { $_.CommandLine -like "*OIL-relay*oil_relay.pyw*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}

# Not as administrator: the relay would run as administrator too, and an
# ordinary PowerShell could no longer see or stop it.
$Me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if ($Me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Run this in an ordinary PowerShell, not as administrator." -ForegroundColor Red
    exit 1
}

if ($Remove) {
    Stop-Relay
    Remove-Item $Shortcut -ErrorAction SilentlyContinue
    Write-Host "The OIL relay is stopped and removed ($Dir is left in place)."
    exit 0
}

# pythonw.exe: Python without a console window. Not "python3": on Windows
# that's usually the Microsoft Store's stand-in.
$Python = $null
foreach ($Command in "py", "python") {
    try { $Found = & $Command -c "import sys; print(sys.executable)" } catch { continue }
    if ($LASTEXITCODE -eq 0 -and $Found) { $Python = "$Found".Trim(); break }
}
$Pythonw = if ($Python) { Join-Path (Split-Path $Python) "pythonw.exe" } else { "" }
if (-not $Python -or -not (Test-Path $Pythonw)) {
    Write-Host "No Python found: install Python 3 first (python.org)." -ForegroundColor Red
    exit 1
}

# The firewall first: without a rule for this pythonw, Windows asks the first
# time the relay starts, and a "Cancel" there blocks it for good. netsh, as
# the NetSecurity cmdlets see no rules without administrator rights.
$Rule = (netsh advfirewall firewall show rule name="OIL relay" verbose) -join "`n"
if ($Rule -notmatch [regex]::Escape($Pythonw)) {
    Write-Host "First let the relay through Windows' firewall. In PowerShell as administrator, run:" -ForegroundColor Yellow
    if ($Rule -match "OIL relay") { Write-Host "  Remove-NetFirewallRule -DisplayName `"OIL relay`"" }
    Write-Host "  New-NetFirewallRule -DisplayName `"OIL relay`" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Program `"$Pythonw`""
    Write-Host "Then run this again."
    exit 1
}
# A block rule for the same program wins over it.
foreach ($Entry in ((netsh advfirewall firewall show rule name=all dir=in verbose) -join "`n") -split "`n\s*`n") {
    if ($Entry -match [regex]::Escape($Pythonw) -and $Entry -match ":\s+(Block|Blok)") {
        Write-Host "This firewall rule blocks $Pythonw, remove it (Windows Defender Firewall, Advanced settings, Inbound Rules):" -ForegroundColor Yellow
        Write-Host "  $(($Entry.Trim() -split "`n")[0])"
    }
}

# A copy of its own, so the running relay doesn't change with this folder.
New-Item -ItemType Directory -Force $Dir | Out-Null
Stop-Relay
Copy-Item (Join-Path $PSScriptRoot "..\..\relay.py") $Dir -Force
Copy-Item (Join-Path $PSScriptRoot "oil_relay.pyw") $Dir -Force
if ($Name -and $Token) {
    $Name = $Name -replace "\.duckdns\.org$", ""
    @{ name = $Name; token = $Token } | ConvertTo-Json | Set-Content -Encoding Ascii (Join-Path $Dir "duckdns.json")
}

$Link = (New-Object -ComObject WScript.Shell).CreateShortcut($Shortcut)
$Link.TargetPath = $Pythonw
$Link.Arguments = "`"$Dir\oil_relay.pyw`" --port $Port"
$Link.WorkingDirectory = $Dir
$Link.Description = "The OIL relay for online games"
$Link.Save()
Start-Process $Shortcut

$Up = $false
for ($i = 0; $i -lt 20 -and -not $Up; $i++) {
    Start-Sleep -Milliseconds 250
    try { (New-Object Net.Sockets.TcpClient("127.0.0.1", $Port)).Close(); $Up = $true } catch {}
}
if ($Up) {
    Write-Host "The OIL relay runs now (and at every login) on port $Port, with $Pythonw."
} else {
    Write-Host "The OIL relay didn't start: see its log." -ForegroundColor Red
}
Write-Host "Its log: $Log"
if (Test-Path (Join-Path $Dir "duckdns.json")) {
    Write-Host "It keeps the DuckDNS name in $Dir\duckdns.json pointing at this home's address."
}
