# Dnevna objava: dohvat -> obrada -> provjera -> deploy na Cloudflare.
#
# Pokrece ga Windows Task Scheduler (zadatak "Prilika dnevna objava", ~09:00;
# ako je racunalo bilo ugaseno, pokrece se pri sljedecem paljenju).
# Redoslijed je ugovor: deploy se NE izvrsava ako run.py ili validate.py
# vrate gresku - radije jucerasnja objava nego netocna.
#
# Dnevnik: cache\deploy\YYYY-MM-DD.log (cache/ je izvan gita).
#
# Namjerno bez dijakritika: PowerShell 5.1 cita .ps1 bez BOM-a kao ANSI,
# pa ne-ASCII znak u kodu razbije parser.

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDir = Join-Path $root "cache\deploy"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ((Get-Date -Format "yyyy-MM-dd") + ".log")

function Step($name, $cmd, $cmdArgs) {
    Add-Content $log ("`n=== {0} - {1} ===" -f (Get-Date -Format "HH:mm:ss"), $name)
    & $cmd @cmdArgs 2>&1 | Out-File -Append -Encoding utf8 $log
    return $LASTEXITCODE
}

$env:PYTHONIOENCODING = "utf-8"

# Wrangler u neinteraktivnom okruzenju (Task Scheduler) trazi API token -
# OAuth prijava iz preglednika tu ne vrijedi. Token se cita iz .env
# (CLOUDFLARE_API_TOKEN=...), gdje vec stanuju i ostale tajne.
if (-not $env:CLOUDFLARE_API_TOKEN) {
    $envFile = Join-Path $root ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*CLOUDFLARE_API_TOKEN\s*=\s*(.+)$') {
                $env:CLOUDFLARE_API_TOKEN = $Matches[1].Trim()
            }
        }
    }
}
if (-not $env:CLOUDFLARE_API_TOKEN) {
    Add-Content $log "PREKID: CLOUDFLARE_API_TOKEN nije u .env - deploy preskocen (stranice su izgradene i provjerene)."
    exit 4
}

$code = Step "pipeline (run.py)" "python" @("run.py")
if ($code -ne 0) {
    Add-Content $log "PREKID: run.py izlazni kod $code - deploy se ne izvrsava."
    exit $code
}

$code = Step "provjere (validate.py)" "python" @("validate.py")
if ($code -ne 0) {
    Add-Content $log "PREKID: validate.py izlazni kod $code - deploy se ne izvrsava."
    exit $code
}

$code = Step "objava (wrangler deploy)" "npx" @("--yes", "wrangler", "deploy")
if ($code -ne 0) {
    Add-Content $log "GRESKA: wrangler deploy izlazni kod $code."
    exit $code
}

Add-Content $log ("GOTOVO {0} - objavljeno na prilika.net" -f (Get-Date -Format "HH:mm:ss"))
exit 0
