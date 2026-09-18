<#
=====================================================================
 IP_Scan.ps1  -  사내 IP 대역(10.40.0.x) 사용 여부 스캔 + MSSQL 누적 기록
=====================================================================

 동작 요약
   1) 192.0.2.10 ~ 192.0.2.10 전부에 동시에 ping을 보낸다.
      (방화벽이 ping을 막는 PC라도 ARP 응답은 하므로, 직후 ARP 캐시를 읽어
       MAC 주소가 잡힌 IP는 "사용 중"으로 판정)
   2) 결과를 MSSQL의 IP_Scan_Log 테이블에 IP별로 누적한다.
        - FirstSeen / LastSeen / SeenCount / MAC / Hostname
        - 꺼져 있는 PC도 "마지막으로 확인된 시각"이 남으므로 추적 가능
   3) 기존 관리 테이블(Seat_Userinfo, Print_Info)은 SELECT만 해서
      대조 리포트(CSV)를 만든다.  ** 기존 테이블은 절대 수정/삽입하지 않음 **

 사용법
   .\IP_Scan.ps1                 # 스캔 + DB 기록 + 대조 리포트
   .\IP_Scan.ps1 -NoDb           # DB 안 쓰고 콘솔/CSV만 (처음 테스트할 때)
   .\IP_Scan.ps1 -NoReport       # 스캔 + DB 기록만
   .\IP_Scan.ps1 -StaleDays 14   # "미확인" 기준을 14일로

 스케줄 등록 예 (1시간마다) - 관리자 PowerShell에서:
   schtasks /Create /TN "IP_Scan" /SC HOURLY /RU "DOMAIN\user" /RP * `
     /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\ipscan\IP_Scan.ps1 -NoReport"

 exe 로 만들고 싶으면:
   Install-Module ps2exe -Scope CurrentUser
   Invoke-ps2exe .\IP_Scan.ps1 .\IP_Scan.exe

 주의: 이 스크립트를 실행하는 PC가 10.40.0.x 대역 안에 있어야
       ARP(MAC) 수집이 됩니다. 다른 대역에서 돌리면 ping 결과만 사용됩니다.
=====================================================================
#>

[CmdletBinding()]
param(
    [switch]$NoDb,
    [switch]$NoReport,
    [int]$StaleDays = 30
)

# =====================================================================
#  설정  (여기만 고치면 됩니다)
# =====================================================================
$Config = @{
    # --- MSSQL 접속 ---
    SqlServer       = "DBSERVER\SQLEXPRESS"   # 예: "192.0.2.10"  또는 "DBSERVER\SQLEXPRESS"  또는 "192.0.2.10,1433"
    Database        = "YourDatabase"          # Seat_Userinfo / Print_Info 가 있는 DB 이름
    UseWindowsAuth  = $true                   # $true = 윈도우 통합 인증, $false = 아래 SQL 계정 사용
    SqlUser         = ""
    SqlPassword     = ""

    # --- 스캔 대역 ---
    SubnetPrefix    = "10.40.0"
    StartHost       = 1
    EndHost         = 254
    PingTimeoutMs   = 1000
    ResolveHostname = $true                   # 살아있는 IP의 호스트명(DNS 역조회) 시도

    # --- 스크립트가 만드는(쓰는) 테이블 ---  ※ 없으면 자동 생성
    LogTable        = "dbo.IP_Scan_Log"       # IP별 현재 상태 (1 IP = 1 row)
    RunTable        = "dbo.IP_Scan_Run"       # 실행 이력
    HistoryTable    = "dbo.IP_Scan_History"   # 실행별로 살아있던 IP 기록 (MAC 변경 추적용)

    # --- 기존 관리 테이블 (읽기 전용, SELECT 만 수행) ---
    #   IpColumn     : IP가 들어있는 컬럼명 (필수)
    #   LabelColumns : 리포트에 같이 보여줄 컬럼들 (사용자명, 좌석, 장비명 등) - 없으면 @()
    #   MacColumn    : MAC 컬럼이 있으면 이름 지정 → 실제 MAC과 불일치 검출. 없으면 ""
    SourceTables    = @(
        @{ Table = "dbo.Seat_Userinfo"; IpColumn = "IP"; LabelColumns = @(); MacColumn = "" },
        @{ Table = "dbo.Print_Info";    IpColumn = "IP"; LabelColumns = @(); MacColumn = "" }
    )

    # --- 리포트 CSV 저장 폴더 ---
    ReportDir       = (Join-Path $(if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }) "reports")
}
# =====================================================================

$ErrorActionPreference = "Stop"
$script:StartTime = Get-Date
$Now = Get-Date

function Write-Log($msg, $color = "Gray") {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg) -ForegroundColor $color
}

# ---------------------------------------------------------------------
#  1. 스캔
# ---------------------------------------------------------------------
function Get-LocalMacMap {
    # 스캔 PC 자신의 IP는 ARP 캐시에 안 나오므로 어댑터에서 직접 읽는다
    $map = @{}
    try {
        if (Get-Command Get-NetIPAddress -ErrorAction SilentlyContinue) {
            Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                Where-Object { $_.IPAddress -like "$($Config.SubnetPrefix).*" } |
                ForEach-Object {
                    $ad = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
                    if ($ad -and $ad.MacAddress) { $map[$_.IPAddress] = $ad.MacAddress.ToUpper() }
                }
        }
    } catch { }
    return $map
}

function Clear-ArpCache {
    # 스캔 전에 해당 대역 ARP 캐시를 비운다 (관리자 권한 필요. 안 되면 $false 반환 → 대기 시간을 늘려서 보정)
    # 이유: 조금 전까지 켜져 있다가 꺼진 PC가 'Stale' 상태로 캐시에 남아 있으면 살아있는 것처럼 보일 수 있음
    $prefix = "$($Config.SubnetPrefix)."
    try {
        if (Get-Command Remove-NetNeighbor -ErrorAction SilentlyContinue) {
            Get-NetNeighbor -AddressFamily IPv4 -ErrorAction Stop |
                Where-Object { $_.IPAddress -like "$prefix*" -and [string]$_.State -ne "Permanent" } |
                Remove-NetNeighbor -Confirm:$false -ErrorAction Stop
            return $true
        }
    } catch { }
    return $false
}

function Get-ArpTable {
    # 서브넷 내 IP -> MAC 맵. ping 직후 'Reachable'(ARP 응답이 실제로 확인된) 항목만 채택.
    $map = @{}
    $prefix = "$($Config.SubnetPrefix)."
    $badMac = @("00-00-00-00-00-00", "FF-FF-FF-FF-FF-FF")
    $goodStates = @("Reachable")

    if (Get-Command Get-NetNeighbor -ErrorAction SilentlyContinue) {
        Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object {
                $_.IPAddress -like "$prefix*" -and
                $_.LinkLayerAddress -and
                ($goodStates -contains [string]$_.State) -and
                ($badMac -notcontains $_.LinkLayerAddress.ToUpper())
            } |
            ForEach-Object { $map[$_.IPAddress] = $_.LinkLayerAddress.ToUpper().Replace(":", "-") }
    }
    elseif (Get-Command arp -ErrorAction SilentlyContinue) {
        # 구형 OS 대비: arp -a 파싱
        & arp -a 2>$null | ForEach-Object {
            if ($_ -match '^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F]{2}([-:][0-9a-fA-F]{2}){5})') {
                $ip = $matches[1]; $mac = $matches[2].ToUpper().Replace(":", "-")
                if ($ip -like "$prefix*" -and ($badMac -notcontains $mac)) { $map[$ip] = $mac }
            }
        }
    }
    return $map
}

function Invoke-Scan {
    $ips = @($Config.StartHost..$Config.EndHost | ForEach-Object { "$($Config.SubnetPrefix).$_" })
    $flushed = Clear-ArpCache
    if ($flushed) { Write-Log "ARP 캐시 초기화 완료" "DarkGray" }
    else { Write-Log "ARP 캐시 초기화 불가(관리자 권한 아님) → ARP 확정 대기 시간을 12초로 늘림" "DarkYellow" }
    Write-Log "ping 발송: $($ips[0]) ~ $($ips[-1]) ($($ips.Count)개, 동시 전송)" "Cyan"

    # 1) 전부 동시에 ping
    $jobs = @{}
    foreach ($ip in $ips) {
        $p = New-Object System.Net.NetworkInformation.Ping
        $jobs[$ip] = @{ Ping = $p; Task = $p.SendPingAsync($ip, $Config.PingTimeoutMs) }
    }
    try {
        [System.Threading.Tasks.Task]::WaitAll([System.Threading.Tasks.Task[]]@($jobs.Values | ForEach-Object { $_.Task }))
    } catch { }   # 일부 실패해도 개별 결과로 판단

    $pingOk = @{}
    foreach ($ip in $ips) {
        $t = $jobs[$ip].Task
        $pingOk[$ip] = ($t.Status -eq "RanToCompletion" -and $t.Result.Status -eq "Success")
        $jobs[$ip].Ping.Dispose()
    }

    # 2) ARP 상태가 확정될 때까지 대기 후 읽기
    #    캐시를 비웠으면 3초면 충분 (응답 없는 IP는 ~3초 내 Unreachable로 바뀜)
    #    못 비웠으면 기존 Stale 항목이 Delay(5초)→Probe(3초)를 거쳐 확정되므로 12초 대기
    Start-Sleep -Seconds $(if ($flushed) { 3 } else { 12 })
    $arp = Get-ArpTable
    $local = Get-LocalMacMap

    # 3) 결과 합치기
    $results = foreach ($ip in $ips) {
        $mac = $null
        if ($arp.ContainsKey($ip)) { $mac = $arp[$ip] }
        elseif ($local.ContainsKey($ip)) { $mac = $local[$ip] }
        [pscustomobject]@{
            IP       = $ip
            HostNum  = [int]($ip.Split(".")[-1])
            Ping     = [bool]$pingOk[$ip]
            MAC      = $mac
            Alive    = ([bool]$pingOk[$ip] -or [bool]$mac)
            Hostname = $null
            IsSelf   = $local.ContainsKey($ip)
        }
    }

    # 4) 호스트명 (살아있는 것만, 병렬, 최대 5초 대기)
    if ($Config.ResolveHostname) {
        $alive = @($results | Where-Object Alive)
        Write-Log "호스트명 조회: $($alive.Count)개" "Cyan"
        $dns = @{}
        foreach ($r in $alive) {
            try { $dns[$r.IP] = [System.Net.Dns]::GetHostEntryAsync($r.IP) } catch { }
        }
        if ($dns.Count -gt 0) {
            try { [void][System.Threading.Tasks.Task]::WaitAll([System.Threading.Tasks.Task[]]@($dns.Values), 5000) } catch { }
        }
        foreach ($r in $alive) {
            $t = $dns[$r.IP]
            if ($t -and $t.Status -eq "RanToCompletion" -and $t.Result.HostName) { $r.Hostname = $t.Result.HostName }
        }
    }

    return @($results)
}

# ---------------------------------------------------------------------
#  2. MSSQL
# ---------------------------------------------------------------------
function New-SqlConnection {
    if ($Config.UseWindowsAuth) {
        $cs = "Server=$($Config.SqlServer);Database=$($Config.Database);Integrated Security=True;Connection Timeout=15"
    } else {
        $cs = "Server=$($Config.SqlServer);Database=$($Config.Database);User ID=$($Config.SqlUser);Password=REDACTED_CONFIGURE_LOCALLY;Connection Timeout=15"
    }
    $conn = New-Object System.Data.SqlClient.SqlConnection $cs
    $conn.Open()
    return $conn
}

function Invoke-SqlNonQuery($conn, $sql, $params = @{}, $tx = $null) {
    $cmd = $conn.CreateCommand()
    if ($tx) { $cmd.Transaction = $tx }
    $cmd.CommandText = $sql
    foreach ($k in $params.Keys) {
        $v = $params[$k]; if ($null -eq $v) { $v = [DBNull]::Value }
        [void]$cmd.Parameters.AddWithValue("@$k", $v)
    }
    return $cmd.ExecuteNonQuery()
}

function Invoke-SqlScalar($conn, $sql, $params = @{}, $tx = $null) {
    $cmd = $conn.CreateCommand()
    if ($tx) { $cmd.Transaction = $tx }
    $cmd.CommandText = $sql
    foreach ($k in $params.Keys) {
        $v = $params[$k]; if ($null -eq $v) { $v = [DBNull]::Value }
        [void]$cmd.Parameters.AddWithValue("@$k", $v)
    }
    return $cmd.ExecuteScalar()
}

function Invoke-SqlQuery($conn, $sql) {
    $cmd = $conn.CreateCommand()
    $cmd.CommandText = $sql
    $da = New-Object System.Data.SqlClient.SqlDataAdapter $cmd
    $dt = New-Object System.Data.DataTable
    [void]$da.Fill($dt)
    return $dt
}

function Initialize-Tables($conn) {
    $log = $Config.LogTable; $run = $Config.RunTable; $his = $Config.HistoryTable
    $sql = @"
IF OBJECT_ID('$log','U') IS NULL
CREATE TABLE $log (
    IP          varchar(15)   NOT NULL PRIMARY KEY,
    HostNum     int           NOT NULL,
    MAC         varchar(17)   NULL,
    PrevMAC     varchar(17)   NULL,
    MacChangedAt datetime     NULL,
    Hostname    nvarchar(255) NULL,
    FirstSeen   datetime      NULL,
    LastSeen    datetime      NULL,
    SeenCount   int           NOT NULL DEFAULT 0,
    LastScan    datetime      NOT NULL,
    LastAlive   bit           NOT NULL,
    LastPing    bit           NOT NULL
);
IF OBJECT_ID('$run','U') IS NULL
CREATE TABLE $run (
    RunId       int IDENTITY(1,1) PRIMARY KEY,
    RunTime     datetime      NOT NULL,
    ScannerHost nvarchar(255) NULL,
    Subnet      varchar(15)   NULL,
    TotalCount  int           NOT NULL,
    AliveCount  int           NOT NULL,
    DurationSec int           NOT NULL
);
IF OBJECT_ID('$his','U') IS NULL
CREATE TABLE $his (
    Id          bigint IDENTITY(1,1) PRIMARY KEY,
    RunId       int           NOT NULL,
    IP          varchar(15)   NOT NULL,
    MAC         varchar(17)   NULL,
    Hostname    nvarchar(255) NULL,
    Ping        bit           NOT NULL,
    ScanTime    datetime      NOT NULL
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_IP_Scan_History_IP' AND object_id=OBJECT_ID('$his'))
    CREATE INDEX IX_IP_Scan_History_IP ON $his (IP, ScanTime);
"@
    [void](Invoke-SqlNonQuery $conn $sql)
}

function Save-ScanResults($conn, $results) {
    $log = $Config.LogTable; $run = $Config.RunTable; $his = $Config.HistoryTable
    $aliveCount = @($results | Where-Object Alive).Count
    $dur = [int]((Get-Date) - $script:StartTime).TotalSeconds

    $tx = $conn.BeginTransaction()
    try {
        $runId = Invoke-SqlScalar $conn "INSERT INTO $run (RunTime, ScannerHost, Subnet, TotalCount, AliveCount, DurationSec)
            OUTPUT INSERTED.RunId VALUES (@now, @host, @subnet, @total, @alive, @dur)" @{
                now = $Now; host = $env:COMPUTERNAME; subnet = "$($Config.SubnetPrefix).0"
                total = $results.Count; alive = $aliveCount; dur = $dur } $tx

        $upsert = @"
IF EXISTS (SELECT 1 FROM $log WHERE IP = @ip)
    UPDATE $log SET
        LastScan  = @now,
        LastAlive = @alive,
        LastPing  = @ping,
        LastSeen  = CASE WHEN @alive = 1 THEN @now ELSE LastSeen END,
        FirstSeen = CASE WHEN @alive = 1 AND FirstSeen IS NULL THEN @now ELSE FirstSeen END,
        SeenCount = SeenCount + CASE WHEN @alive = 1 THEN 1 ELSE 0 END,
        PrevMAC      = CASE WHEN @alive = 1 AND @mac IS NOT NULL AND MAC IS NOT NULL AND MAC <> @mac THEN MAC  ELSE PrevMAC      END,
        MacChangedAt = CASE WHEN @alive = 1 AND @mac IS NOT NULL AND MAC IS NOT NULL AND MAC <> @mac THEN @now ELSE MacChangedAt END,
        MAC       = CASE WHEN @alive = 1 AND @mac  IS NOT NULL THEN @mac  ELSE MAC      END,
        Hostname  = CASE WHEN @alive = 1 AND @host IS NOT NULL THEN @host ELSE Hostname END
    WHERE IP = @ip
ELSE
    INSERT INTO $log (IP, HostNum, MAC, Hostname, FirstSeen, LastSeen, SeenCount, LastScan, LastAlive, LastPing)
    VALUES (@ip, @hostnum, @mac, @host,
            CASE WHEN @alive = 1 THEN @now ELSE NULL END,
            CASE WHEN @alive = 1 THEN @now ELSE NULL END,
            CASE WHEN @alive = 1 THEN 1 ELSE 0 END,
            @now, @alive, @ping);
"@
        $hist = "INSERT INTO $his (RunId, IP, MAC, Hostname, Ping, ScanTime) VALUES (@runid, @ip, @mac, @host, @ping, @now)"

        foreach ($r in $results) {
            [void](Invoke-SqlNonQuery $conn $upsert @{
                ip = $r.IP; hostnum = $r.HostNum; mac = $r.MAC; host = $r.Hostname
                alive = [int]$r.Alive; ping = [int]$r.Ping; now = $Now } $tx)
            if ($r.Alive) {
                [void](Invoke-SqlNonQuery $conn $hist @{
                    runid = $runId; ip = $r.IP; mac = $r.MAC; host = $r.Hostname; ping = [int]$r.Ping; now = $Now } $tx)
            }
        }
        $tx.Commit()
        Write-Log "DB 기록 완료 (RunId=$runId, 살아있는 IP $aliveCount / $($results.Count))" "Green"
    }
    catch {
        $tx.Rollback()
        throw
    }
}

# ---------------------------------------------------------------------
#  3. 기존 관리 테이블과 대조 (읽기 전용)
# ---------------------------------------------------------------------
function Normalize-Ip([string]$raw) {
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    $v = $raw.Trim()
    if ($v -match '^\d{1,3}$') { return "$($Config.SubnetPrefix).$v" }          # 끝자리만 저장된 경우
    if ($v -match '^(\d{1,3}\.){3}\d{1,3}$') { return $v }
    return $null
}

function Get-RegisteredMap($conn) {
    # IP -> @{ Labels = "테이블:정보 | ..."; Macs = @(...) }
    $map = @{}
    foreach ($src in $Config.SourceTables) {
        $cols = @("[$($src.IpColumn)]")
        foreach ($c in $src.LabelColumns) { $cols += "[$c]" }
        if ($src.MacColumn) { $cols += "[$($src.MacColumn)]" }
        $sql = "SELECT $($cols -join ', ') FROM $($src.Table)"     # SELECT only
        $dt = Invoke-SqlQuery $conn $sql
        $shortName = ($src.Table -split '\.')[-1]
        foreach ($row in $dt.Rows) {
            $ip = Normalize-Ip ([string]$row[$src.IpColumn])
            if (-not $ip -or -not $ip.StartsWith("$($Config.SubnetPrefix).")) { continue }
            $labelParts = @()
            foreach ($c in $src.LabelColumns) { $val = [string]$row[$c]; if ($val.Trim()) { $labelParts += $val.Trim() } }
            $label = if ($labelParts.Count) { "$shortName($($labelParts -join '/'))" } else { $shortName }
            if (-not $map.ContainsKey($ip)) { $map[$ip] = @{ Labels = @(); Macs = @() } }
            $map[$ip].Labels += $label
            if ($src.MacColumn) {
                $m = ([string]$row[$src.MacColumn]).Trim().ToUpper().Replace(":", "-")
                if ($m) { $map[$ip].Macs += $m }
            }
        }
        Write-Log "$($src.Table) 읽음: $($dt.Rows.Count)행 (SELECT only)" "DarkGray"
    }
    return $map
}

function New-Report($conn, $results) {
    $reg = Get-RegisteredMap $conn
    $logDt = Invoke-SqlQuery $conn "SELECT IP, MAC, PrevMAC, Hostname, FirstSeen, LastSeen, SeenCount FROM $($Config.LogTable)"
    $logMap = @{}
    foreach ($row in $logDt.Rows) { $logMap[[string]$row.IP] = $row }

    $rows = foreach ($r in $results) {
        $l = $logMap[$r.IP]
        $lastSeen = if ($l -and $l.LastSeen -isnot [DBNull]) { [datetime]$l.LastSeen } else { $null }
        $daysUnseen = if ($lastSeen) { [int]((Get-Date) - $lastSeen).TotalDays } else { $null }
        $isReg = $reg.ContainsKey($r.IP)
        $regLabel = if ($isReg) { ($reg[$r.IP].Labels | Select-Object -Unique) -join " | " } else { "" }
        $regMac = if ($isReg) { ($reg[$r.IP].Macs | Select-Object -Unique) -join " | " } else { "" }

        $status =
            if ($isReg -and $r.Alive)                          { "정상(사용중)" }
            elseif ($isReg -and $lastSeen -and $daysUnseen -lt $StaleDays) { "정상(현재 꺼짐)" }
            elseif ($isReg -and $lastSeen)                     { "회수검토(${StaleDays}일+ 미확인)" }
            elseif ($isReg)                                    { "회수검토(한번도 안보임)" }
            elseif ($r.Alive)                                  { "미등록 사용중 !!" }
            elseif ($lastSeen -and $daysUnseen -lt $StaleDays) { "미등록(최근 사용흔적)" }
            else                                               { "빈 IP" }

        $macNote = ""
        if ($isReg -and $r.Alive -and $r.MAC -and $regMac -and ($regMac -notlike "*$($r.MAC)*")) { $macNote = "MAC 불일치" }
        if ($l -and $l.PrevMAC -isnot [DBNull] -and $l.PrevMAC) { $macNote = ($macNote, "이전MAC:$($l.PrevMAC)" | Where-Object { $_ }) -join "; " }

        [pscustomobject]@{
            IP        = $r.IP
            상태      = $status
            등록정보  = $regLabel
            현재응답  = if ($r.Alive) { if ($r.Ping) { "ping+arp" } else { "arp만" } } else { "" }
            MAC       = if ($r.MAC) { $r.MAC } elseif ($l -and $l.MAC -isnot [DBNull]) { $l.MAC } else { "" }
            등록MAC   = $regMac
            Hostname  = if ($r.Hostname) { $r.Hostname } elseif ($l -and $l.Hostname -isnot [DBNull]) { $l.Hostname } else { "" }
            LastSeen  = if ($lastSeen) { $lastSeen.ToString("yyyy-MM-dd HH:mm") } else { "" }
            미확인일수 = if ($null -ne $daysUnseen) { $daysUnseen } else { "" }
            비고      = $macNote
        }
    }
    $rows = @($rows)

    if (-not (Test-Path $Config.ReportDir)) { [void](New-Item -ItemType Directory -Path $Config.ReportDir) }
    $csv = Join-Path $Config.ReportDir ("IP_Report_{0}.csv" -f (Get-Date -Format "yyyyMMdd_HHmm"))
    $rows | Export-Csv -Path $csv -NoTypeInformation -Encoding UTF8
    Write-Log "리포트 저장: $csv" "Green"

    Write-Host ""
    Write-Host "===== 대조 결과 요약 (기준: ${StaleDays}일) =====" -ForegroundColor Yellow
    $rows | Group-Object 상태 | Sort-Object Name | ForEach-Object {
        Write-Host ("  {0,-28} {1,4}개" -f $_.Name, $_.Count)
    }
    $attention = @($rows | Where-Object { $_.상태 -like "미등록 사용중*" -or $_.상태 -like "회수검토*" -or $_.비고 -like "MAC 불일치*" })
    if ($attention.Count) {
        Write-Host ""
        Write-Host "----- 확인 필요 ($($attention.Count)건) -----" -ForegroundColor Red
        $attention | Sort-Object { [int]($_.IP.Split(".")[-1]) } |
            Format-Table IP, 상태, 등록정보, MAC, Hostname, LastSeen, 비고 -AutoSize | Out-String -Width 200 | Write-Host
    }
    return $rows
}

# ---------------------------------------------------------------------
#  실행
# ---------------------------------------------------------------------
Write-Log "IP 스캔 시작  대역=$($Config.SubnetPrefix).0/24  PC=$env:COMPUTERNAME" "Yellow"
$results = Invoke-Scan
$aliveNow = @($results | Where-Object Alive)
Write-Log "살아있는 IP: $($aliveNow.Count)개  (ping 응답 $(@($aliveNow | Where-Object Ping).Count), ARP만 $(@($aliveNow | Where-Object { -not $_.Ping }).Count))" "Green"

if ($NoDb) {
    if (-not (Test-Path $Config.ReportDir)) { [void](New-Item -ItemType Directory -Path $Config.ReportDir) }
    $csv = Join-Path $Config.ReportDir ("IP_Scan_{0}.csv" -f (Get-Date -Format "yyyyMMdd_HHmm"))
    $results | Select-Object IP, Alive, Ping, MAC, Hostname | Export-Csv -Path $csv -NoTypeInformation -Encoding UTF8
    Write-Log "(-NoDb) 스캔 결과 CSV: $csv" "Green"
    $aliveNow | Sort-Object HostNum | Format-Table IP, Ping, MAC, Hostname -AutoSize | Out-String -Width 200 | Write-Host
}
else {
    $conn = $null
    try {
        $conn = New-SqlConnection
        Write-Log "MSSQL 접속 OK: $($Config.SqlServer) / $($Config.Database)" "DarkGray"
        Initialize-Tables $conn
        Save-ScanResults $conn $results
        if (-not $NoReport) { [void](New-Report $conn $results) }
    }
    finally {
        if ($conn) { $conn.Dispose() }
    }
}

Write-Log ("완료 ({0}초)" -f [int]((Get-Date) - $script:StartTime).TotalSeconds) "Yellow"
