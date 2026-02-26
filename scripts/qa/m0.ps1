# scripts/qa/m0.ps1
# Talence QA Pack: M0 — Deterministic Core (hardened)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8001"
$RepoRoot = (Resolve-Path $PWD).Path
$DbPath  = Join-Path $RepoRoot "data\talence_dev.db"
$Email   = "m0test@example.com"
$Handle  = "m0test"
$Password = "password123"

function Write-Ok($msg)   { Write-Host "[PASS] $msg" -ForegroundColor Green }
function Write-Bad($msg)  { Write-Host "[FAIL] $msg" -ForegroundColor Red }
function Write-Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }

$failures = New-Object System.Collections.Generic.List[string]

function Fail($msg) {
  $failures.Add($msg) | Out-Null
  Write-Bad $msg
}

function Assert($cond, $msg) {
  if (-not $cond) { Fail $msg } else { Write-Ok $msg }
}

function Invoke-ApiJson($method, $url, $bodyJson = $null, $headers = $null) {
  $params = @{
    Method = $method
    Uri = $url
    ContentType = "application/json"
  }
  if ($null -ne $bodyJson) { $params.Body = $bodyJson }
  if ($null -ne $headers) { $params.Headers = $headers }

  try {
    $resp = Invoke-WebRequest @params
    if ([string]::IsNullOrWhiteSpace($resp.Content)) { return $null }
    return ($resp.Content | ConvertFrom-Json)
  } catch {
    Write-Host "[DEBUG] HTTP FAIL $method $url" -ForegroundColor Yellow
    if ($_.Exception.Response) {
      try {
        $status = [int]$_.Exception.Response.StatusCode
        Write-Host "[DEBUG] Status: $status" -ForegroundColor Yellow
      } catch {}
      try {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $respBody = $reader.ReadToEnd()
        Write-Host "[DEBUG] HTTP body: $respBody" -ForegroundColor Yellow
      } catch {
        Write-Host "[DEBUG] Could not read response body" -ForegroundColor Yellow
      }
    } else {
      Write-Host "[DEBUG] Exception: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    throw
  }
}

function Try-ApiExpectFail($method, $url, $bodyJson) {
  try {
    Invoke-WebRequest -Method $method -Uri $url -ContentType "application/json" -Body $bodyJson | Out-Null
    return $false
  } catch {
    return $true
  }
}

# -------- Python enforcement --------
$VenvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPy) {
  $PyExe = $VenvPy
} else {
  # last resort: whatever python resolves to
  $PyExe = (Get-Command python -ErrorAction Stop).Source
}

function Py($code) {
  $out = & $PyExe -c $code 2>$null
  return ($out | Out-String).Trim()
}

# Run python in a way that PowerShell cannot "NativeCommandError" us to death.
# We shell through cmd.exe, force CWD, and force PYTHONPATH to repo root.
function Run-PythonFile-Deterministic([string]$scriptPath) {
  $scriptAbs = (Resolve-Path $scriptPath).Path

  # cmd.exe quoting is cursed; keep it simple and explicit.
  $cmd = "cd /d `"$RepoRoot`" && set `PYTHONPATH=$RepoRoot`&& `"$PyExe`" `"$scriptAbs`""
  # Capture both streams without PS native error translation
  $out = & cmd.exe /c $cmd 2>&1 | Out-String
  return $out.Trim()
}

Write-Info "=== Talence M0 QA Pack ==="

# -------------------------
# M0-0: Preconditions
# -------------------------
if (-not $env:TALENCE_JWT_SECRET) {
  Fail "Precondition: TALENCE_JWT_SECRET must be set in the environment"
} else {
  Write-Ok "Precondition: TALENCE_JWT_SECRET is set"
}

try {
  $s = Invoke-WebRequest -Method GET -Uri "$BaseUrl/status"
  Assert ($s.StatusCode -eq 200) "Precondition: server reachable at $BaseUrl"
} catch {
  Fail "Precondition: server not reachable at $BaseUrl (start it with .\dev.ps1)"
}

if (Test-Path $DbPath) {
  Write-Ok "DB present: $DbPath"
} else {
  Write-Info "DB not found yet at $DbPath (may be created on first request)"
}

# -------------------------
# M0-1: Register/Login + tokens
# -------------------------
Write-Info "M0-1: auth issuance (register-or-login)"

$auth = $null
try {
  $auth = Invoke-ApiJson "POST" "$BaseUrl/auth/register" (("{""email"":""$Email"",""password"":""$Password"",""handle"":""$Handle""}"))
  Write-Ok "Register succeeded"
} catch {
  Write-Info "Register failed (likely exists). Trying login..."
  try {
    $auth = Invoke-ApiJson "POST" "$BaseUrl/auth/login" (("{""email"":""$Email"",""password"":""$Password""}"))
    Write-Ok "Login succeeded"
  } catch {
    Fail "Auth: unable to register or login as $Email"
  }
}

$access = $null
$refresh1 = $null
if ($null -ne $auth) {
  $access = $auth.access_token
  $refresh1 = $auth.refresh_token
}

Assert ([string]::IsNullOrWhiteSpace($access) -eq $false) "Auth: access_token returned"
Assert ([string]::IsNullOrWhiteSpace($refresh1) -eq $false) "Auth: refresh_token returned"

$Authz = @{ Authorization = "Bearer $access" }

# -------------------------
# M0-2: Refresh rotation
# -------------------------
Write-Info "M0-2: refresh rotation"

$refResp = $null
try {
  $refResp = Invoke-ApiJson "POST" "$BaseUrl/auth/refresh" (("{""refresh_token"":""$refresh1""}"))
  Write-Ok "Refresh using R1 returned 200"
} catch {
  Fail "Refresh using R1 failed unexpectedly"
}

$refresh2 = $null
if ($null -ne $refResp) {
  $refresh2 = $refResp.refresh_token
  if ($null -ne $refResp.access_token -and -not [string]::IsNullOrWhiteSpace($refResp.access_token)) {
    $access = $refResp.access_token
    $Authz = @{ Authorization = "Bearer $access" }
  }
}

Assert ([string]::IsNullOrWhiteSpace($refresh2) -eq $false) "Refresh: new refresh_token (R2) returned"

$reuseFailed = Try-ApiExpectFail "POST" "$BaseUrl/auth/refresh" (("{""refresh_token"":""$refresh1""}"))
Assert ($reuseFailed -eq $true) "Refresh: reusing R1 is rejected"

# -------------------------
# M0-3: Run → Plan → Persist
# -------------------------
Write-Info "M0-3: run creation + plan persistence"

$run = $null
try {
  $run = Invoke-ApiJson "POST" "$BaseUrl/runs/create_local" `
    '{ "input_bin":1, "unrecognized_bin":35, "bins":[2,3,35], "capacities":{"2":200,"3":200,"35":200}, "operators":[{"op":"color_identity","order":0}] }' `
    $Authz
  Write-Ok "Run created"
} catch {
  Fail "Run creation failed"
}

$run_id = $null
if ($null -ne $run) { $run_id = $run.run_id }
Assert ([string]::IsNullOrWhiteSpace($run_id) -eq $false) "Run: run_id returned"

function Add-Card([string]$name, [string]$oid, [string]$printId) {
  $body = "{""name"":""$name"",""oracle_id"":""$oid"",""print_id"":""$printId"",""identified"":true,""current_bin"":1,""attrs"":{}}"
  $resp = Invoke-ApiJson "POST" "$BaseUrl/runs/$run_id/debug_add_card" $body $Authz
  if ($null -eq $resp -or [string]::IsNullOrWhiteSpace($resp.instance_id)) {
    throw "debug_add_card: instance_id missing"
  }
}

try {
  Add-Card "A" "o1" "p1"
  Add-Card "B" "o2" "p2"
  Add-Card "C" "o3" "p3"
  Write-Ok "Added 3 cards"
} catch {
  Fail "Failed adding debug cards"
}

$plan = $null
try {
  $plan = Invoke-ApiJson "POST" "$BaseUrl/runs/$run_id/plan" $null $Authz
  Write-Ok "Plan generated"
} catch {
  Fail "Plan generation failed"
}

Assert ($null -ne $plan.plan_id) "Plan: plan_id returned"
Assert (Test-Path $DbPath) "DB file exists after operations ($DbPath)"

# -------------------------
# M0-4: Foreign keys enforced + deterministic negative test
# -------------------------
Write-Info "M0-4: sqlite foreign_keys=ON (via robot.app.db.connect)"

try {
  $fk = Py "from robot.app.db import connect; con=connect(); print(con.execute('PRAGMA foreign_keys').fetchone()[0])"
  Assert ($fk -eq "1") "SQLite: PRAGMA foreign_keys == 1"
} catch {
  Fail "SQLite: could not read PRAGMA foreign_keys via app connection"
}

# Create FK test script that self-reports environment and never crashes silently.
$tmp = Join-Path $env:TEMP "talence_fk_neg_test.py"
@"
import os, sys, sqlite3
print("PY_EXE=" + sys.executable)
print("CWD=" + os.getcwd())
print("PYTHONPATH=" + str(os.environ.get("PYTHONPATH")))
print("SYSPATH0=" + (sys.path[0] if sys.path else "<none>"))

try:
    from robot.app.db import connect
except Exception as e:
    print("IMPORT_ERROR=" + repr(e))
    raise

con = connect()
try:
    cur = con.cursor()
    # should violate planned_moves.plan_id -> movement_plans.id
    cur.execute(
        "INSERT INTO planned_moves (id, plan_id, step_no, from_bin, to_bin, instance_id, move_type, notes) "
        "VALUES ('x', 'nope-plan-id', 0, 1, 2, 'inst', 'transfer', NULL)"
    )
    con.commit()
    print("FK_RESULT=BAD")
except sqlite3.IntegrityError as e:
    print("FK_RESULT=OK")
except Exception as e:
    print("FK_RESULT=ERROR:" + repr(e))
finally:
    try:
        con.close()
    except Exception:
        pass
"@ | Set-Content -Encoding UTF8 $tmp

$fkOut = Run-PythonFile-Deterministic $tmp
Remove-Item $tmp -Force -ErrorAction SilentlyContinue

Write-Host "[DEBUG] FK neg test python output:" -ForegroundColor Yellow
Write-Host $fkOut -ForegroundColor Yellow

if ($fkOut -match "FK_RESULT=OK") {
  Write-Ok "SQLite: FK enforcement rejects invalid child row"
} elseif ($fkOut -match "FK_RESULT=BAD") {
  Fail "SQLite: FK enforcement did NOT reject invalid child row (FK missing/undefined?)"
} else {
  Fail "SQLite: FK negative test errored (see debug output above)"
}

# -------------------------
# M0-5: WAL enabled (via app connection)
# -------------------------
Write-Info "M0-5: sqlite WAL mode (via robot.app.db.connect)"

try {
  $jm = Py "from robot.app.db import connect; con=connect(); print(con.execute('PRAGMA journal_mode').fetchone()[0])"
  Assert ($jm.ToLower() -eq "wal") "SQLite: PRAGMA journal_mode == wal"
} catch {
  Fail "SQLite: could not read PRAGMA journal_mode via app connection"
}

# -------------------------
# M0-6: Persistence presence check
# -------------------------
Write-Info "M0-6: persistence presence check (proxy for no in-memory state)"

try {
  $runs = Py "import sqlite3; con=sqlite3.connect(r'$DbPath'); print(con.execute('SELECT COUNT(*) FROM runs').fetchone()[0])"
  Assert ([int]$runs -ge 1) "DB: runs table has >= 1 row"
} catch {
  Fail "DB: could not query runs count"
}

try {
  $plans = Py "import sqlite3; con=sqlite3.connect(r'$DbPath'); print(con.execute('SELECT COUNT(*) FROM movement_plans').fetchone()[0])"
  Assert ([int]$plans -ge 1) "DB: movement_plans table has >= 1 row"
} catch {
  Fail "DB: could not query movement_plans count"
}

try {
  $moves = Py "from robot.app.db import connect; con=connect(); print(con.execute('SELECT COUNT(*) FROM planned_moves').fetchone()[0])"
  Assert ([int]$moves -ge 1) "DB: planned_moves table has >= 1 row"
} catch {
  Fail "DB: could not query planned_moves count"
}

# -------------------------
# Summary / Exit
# -------------------------
Write-Host ""
Write-Info "=== Summary ==="
if ($failures.Count -eq 0) {
  Write-Ok "M0 QA Pack PASSED (all checks green)"
  exit 0
} else {
  Write-Bad "M0 QA Pack FAILED ($($failures.Count) failure(s))"
  $failures | ForEach-Object { Write-Host " - $_" -ForegroundColor Red }
  exit 1
}