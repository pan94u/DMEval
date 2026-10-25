param([string]$PythonPath)
$ErrorActionPreference='Stop'
$uri='http://127.0.0.1:8787/'
try {
    $request=[Net.HttpWebRequest]::Create($uri)
    $request.Proxy=$null
    $request.Timeout=2000
    $response=$request.GetResponse()
    $response.Close()
    Write-Output 'Workbench is already available at http://127.0.0.1:8787'
    exit 0
} catch {}
if (-not $PythonPath) {
    $PythonPath=Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw 'Pass a Python 3.11+ executable with -PythonPath.'
}
$parts=$PSScriptRoot.Replace('\','/').Trim('/').Split('/')
if ($parts.Length -lt 3 -or $parts[0] -notin @('wsl.localhost','wsl$')) {
    throw 'Run this launcher from the project folder inside WSL.'
}
$distribution=$parts[1]
$linuxProject='/'+($parts[2..($parts.Length-1)] -join '/')
& wsl.exe -d $distribution --exec systemctl --user stop decision-dashboard.service
$logFolder=Join-Path $PSScriptRoot 'runs'
New-Item -ItemType Directory -Path $logFolder -Force | Out-Null
$arguments=@('-X','utf8',('"'+(Join-Path $PSScriptRoot 'windows_host.py')+'"'),'--distribution',$distribution,'--project',$linuxProject)
Start-Process -FilePath $PythonPath -ArgumentList $arguments -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logFolder 'windows-host.log') -RedirectStandardError (Join-Path $logFolder 'windows-host-errors.log') | Out-Null
Write-Output 'Workbench started at http://127.0.0.1:8787'
