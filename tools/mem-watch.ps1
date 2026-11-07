# Records speed.exe's memory every 2 seconds while it runs: address space used (VirtualMB: the 32-bit game's limit is
# 4096 with large-address-aware), memory it owns (PrivateMB) and in RAM (WorkingSetMB), with the peaks Windows keeps;
# and the whole laptop's: free RAM (SysFreeMB), memory promised to all programs against the limit (CommitMB of
# CommitLimitMB), and the graphics card's memory in use and busy share (GpuMemMB, GpuBusy, from nvidia-smi).
# Read-only: it only asks Windows and the NVIDIA driver for figures. Each line is written straight to the file, so a
# hang loses at most the last 2 seconds. Waits up to WaitMinutes for the game to start, stops when it exits.
#   powershell -File tools\mem-watch.ps1 [-Out telemetry\mem\mem-<time>.csv] [-WaitMinutes 30]
param([string]$Out = "", [int]$WaitMinutes = 30)
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $Out) { $Out = Join-Path $root ("telemetry\mem\mem-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".csv") }
New-Item -ItemType Directory -Force (Split-Path -Parent $Out) | Out-Null
$smi = Join-Path $env:SystemRoot "System32\nvidia-smi.exe"
$deadline = (Get-Date).AddMinutes($WaitMinutes)
$p = $null
while (-not $p -and (Get-Date) -lt $deadline) {
    $p = Get-Process speed -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $p) { Start-Sleep -Seconds 2 }
}
if (-not $p) { "no speed.exe within $WaitMinutes minutes"; exit 1 }
"time,seconds,VirtualMB,PrivateMB,WorkingSetMB,PeakVirtualMB,PeakWorkingSetMB,SysFreeMB,CommitMB,CommitLimitMB,GpuMemMB,GpuBusy" |
    Out-File -Encoding ascii $Out
$start = Get-Date
$mb = 1MB
while (-not $p.HasExited) {
    $p.Refresh()
    $os = Get-CimInstance Win32_OperatingSystem
    $perf = Get-CimInstance Win32_PerfRawData_PerfOS_Memory
    $gpu = "", ""
    if (Test-Path $smi) {
        $q = & $smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits 2>$null
        if ($q) { $gpu = ($q | Select-Object -First 1) -split ",\s*" }
    }
    $line = "{0},{1:F0},{2:F0},{3:F0},{4:F0},{5:F0},{6:F0},{7:F0},{8:F0},{9:F0},{10},{11}" -f (Get-Date -Format "HH:mm:ss"),
        ((Get-Date) - $start).TotalSeconds, ($p.VirtualMemorySize64 / $mb), ($p.PrivateMemorySize64 / $mb),
        ($p.WorkingSet64 / $mb), ($p.PeakVirtualMemorySize64 / $mb), ($p.PeakWorkingSet64 / $mb),
        ($os.FreePhysicalMemory / 1KB), ($perf.CommittedBytes / $mb), ($perf.CommitLimit / $mb), $gpu[0], $gpu[1]
    $line | Out-File -Encoding ascii -Append $Out
    Start-Sleep -Seconds 2
}
"speed.exe exited; recorded in $Out"
