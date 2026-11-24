param([switch]$Stop)

$ErrorActionPreference = "Stop"

# Sin este bloque param el script no tenia forma de parar nada: el supervisor
# lo invocaba como `start-windows.ps1 -Stop`, PowerShell ignoraba el argumento
# suelto y el cuerpo arrancaba el servidor en primer plano. `db stop` se quedaba
# colgado para siempre en el paso 1/7 y, de paso, ARRANCABA este proyecto en vez
# de detenerlo (2026-08-16).
function Get-ListeningPidsOnPort($TargetPort) {
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        return @(Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique)
    }
    # pwsh 7 no trae el modulo NetTCPIP: sin este respaldo el puerto se lee
    # siempre como libre y la parada seria un falso verde.
    # Without -p: `-p tcp` lists IPv4 only and missed a server bound to [::].
    $matchesFound = @(netstat -ano 2>$null | Select-String ":$TargetPort\s+\S+\s+LISTENING\s+(\d+)")
    return @($matchesFound | ForEach-Object { [int]$_.Matches.Groups[1].Value } | Select-Object -Unique)
}

# Only processes of THIS project are stopped: python running wsgi.py whose
# executable lives under this folder (venv) or whose parent does (the venv
# launcher spawns the base interpreter). The Werkzeug reloader parent is
# returned too, otherwise it survives the child. Foreign owners of the port
# are reported and left untouched.
$script:ForeignPortOwners = @()
function Get-ProjectServerPids($TargetPort) {
    $script:ForeignPortOwners = @()
    $root = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') + '\'
    $procs = @{}
    foreach ($proc in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
        $procs[[int]$proc.ProcessId] = $proc
    }
    $isProject = {
        param($proc)
        if (-not $proc -or $proc.Name -ne 'python.exe' -or $proc.CommandLine -notmatch 'wsgi\.py') { return $false }
        $candidates = @($proc)
        if ($procs.ContainsKey([int]$proc.ParentProcessId)) { $candidates += $procs[[int]$proc.ParentProcessId] }
        foreach ($c in $candidates) {
            if ($c.ExecutablePath -and $c.ExecutablePath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { return $true }
        }
        return $false
    }
    $result = @()
    foreach ($ownerPid in (Get-ListeningPidsOnPort $TargetPort)) {
        $proc = $procs[[int]$ownerPid]
        if (& $isProject $proc) {
            $result += [int]$ownerPid
            $parent = $procs[[int]$proc.ParentProcessId]
            if ($parent -and $parent.Name -eq 'python.exe' -and $parent.CommandLine -match 'wsgi\.py') {
                $result += [int]$parent.ProcessId
            }
        } elseif ([int]$ownerPid -gt 4) {
            $name = if ($proc) { $proc.Name } else { 'desconocido' }
            $script:ForeignPortOwners += "$ownerPid ($name)"
        }
    }
    return @($result | Select-Object -Unique)
}

$port = 8158

if ($Stop) {
    Write-Host "Deteniendo Panel de Instructores (:$port)..." -ForegroundColor Yellow
    $detenidos = 0
    foreach ($projectPid in (Get-ProjectServerPids $port)) {
        try { Stop-Process -Id $projectPid -Force -ErrorAction Stop; $detenidos++ } catch {
            Write-Warning "No se pudo detener el proceso $projectPid."
        }
    }
    foreach ($owner in $script:ForeignPortOwners) {
        Write-Warning "El puerto $port lo ocupa el proceso $owner, que no es de este proyecto; no se detuvo."
    }
    Write-Host "Detenido(s): $detenidos proceso(s) del proyecto en el puerto $port." -ForegroundColor Green
    return
}

# El reloader de Werkzeug usa watchdog y excluye el entorno virtual,
# uploads, logs y caches desde wsgi.py para evitar reinicios espurios.
Remove-Item Env:WERKZEUG_SERVER_FD -ErrorAction SilentlyContinue
Remove-Item Env:WERKZEUG_RUN_MAIN -ErrorAction SilentlyContinue
# Limpiar vars DevBrain que puedan contaminar la conexion
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:POSTGRES_USER -ErrorAction SilentlyContinue
Remove-Item Env:POSTGRES_PASSWORD -ErrorAction SilentlyContinue
Remove-Item Env:POSTGRES_DB -ErrorAction SilentlyContinue
Remove-Item Env:DEVBRAIN_PG_DSN -ErrorAction SilentlyContinue
Remove-Item Env:PGUSER -ErrorAction SilentlyContinue
Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue

# Inyectar credenciales desde WCM (requiere PowerShell 7+)
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $wcmInjector = "$PSScriptRoot\..\..\_infrastructure\devbraind\scripts\Import-ProjectCredentials.ps1"
    if (Test-Path $wcmInjector) {
        try {
            . $wcmInjector
            Import-ProjectCredentials -Project adso
        } catch {}
    }
} else {
    Write-Verbose "[WARN] PowerShell 7+ requerido para importar credenciales WCM. Usando vars .env por defecto."
}

Write-Host "Limpiando instancias previas del proyecto en el puerto $port..." -ForegroundColor Yellow
$previos = 0
foreach ($projectPid in (Get-ProjectServerPids $port)) {
    Write-Host "Deteniendo instancia previa (PID $projectPid)..." -ForegroundColor Yellow
    try { Stop-Process -Id $projectPid -Force -ErrorAction Stop; $previos++ } catch {
        Write-Warning "No se pudo detener el proceso $projectPid."
    }
}
if ($script:ForeignPortOwners.Count -gt 0) {
    throw "El puerto $port lo ocupa otro programa: $($script:ForeignPortOwners -join ', '). Libérelo o detenga ese programa antes de iniciar el panel."
}
if ($previos -gt 0) { Start-Sleep -Seconds 2 }

Write-Host "=== SENA Control Academico - Inicio ===" -ForegroundColor Green

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

$venvDir = if (Test-Path "venv_win\Scripts\Activate.ps1") { "venv_win" } elseif (Test-Path "venv\Scripts\Activate.ps1") { "venv" } else { "venv" }
if (-not (Test-Path "$venvDir\Scripts\Activate.ps1")) {
    Write-Host "Creando entorno virtual ($venvDir)..." -ForegroundColor Yellow
    python -m venv $venvDir
}

& ".\$venvDir\Scripts\Activate.ps1"

Write-Host "Instalando dependencias..." -ForegroundColor Yellow
pip install -r requirements.txt -q

Write-Host "Verificando base de datos..." -ForegroundColor Yellow
python -c "
from app import create_app, db
app = create_app()
with app.app_context():
    try:
        db.engine.connect()
        print('Conexion OK')
    except Exception as e:
        print(f'Error BD: {e}')
        print('Creando base de datos...')
"

Write-Host "Aplicando migraciones..." -ForegroundColor Yellow
flask db upgrade
if ($LASTEXITCODE -ne 0) {
    throw "No se pudieron aplicar las migraciones. La aplicación no se iniciará para proteger los datos existentes."
}

Write-Host "Verificando cuenta admin..." -ForegroundColor Yellow
python seed_admin.py
if ($LASTEXITCODE -ne 0) {
    throw "Fallo la verificacion/creacion del admin. Revise ADSO_ADMIN_EMAIL / ADSO_ADMIN_PASSWORD."
}

Write-Host ""
$env:PORT = "$port"
$env:HOST = '127.0.0.1'
Write-Host "=== Iniciando servidor en http://127.0.0.1:8158 ===" -ForegroundColor Green
python wsgi.py
