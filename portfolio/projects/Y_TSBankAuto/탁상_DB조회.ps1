# ============================================================
#  탁상자문 PDF <-> APW_TS_Master 조회 (읽기 전용 / SELECT 만)
#  결과 CSV + 실행 로그를 같은 폴더에 저장하고 자동 종료.
# ============================================================
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log = Join-Path $here "탁상_DB조회_$stamp.log"
function W($m){ $m | Tee-Object -FilePath $log -Append | Out-Null; Write-Host $m }

$server   = "192.0.2.10,1433"
$database = "apworksdw"
$connStr  = "Server=$server;Database=$database;User Id=dh;Password=REDACTED_CONFIGURE_LOCALLY;TrustServerCertificate=True;Connect Timeout=10;"

$advisory = @(
 "01-20260629-103","01-20260629-100","01-20260629-082","01-20260629-085",
 "01-20260629-080","01-20260629-069","01-20260629-068","01-20260629-050",
 "01-20260629-039","01-20260629-037","01-20260629-027","01-20260629-016",
 "01-20260626-104","01-20260626-099","01-20260626-085","01-20260626-082")
$request = @(
 "T260613250","T260613210","T260613118","T260613110","T260613069",
 "T260613011","T260612997","T260612953","T260612916","T260612902",
 "T260612837","T260612783","T260612709","T260612689","T260612647","T260612635")

function Assert-Safe($arr){ foreach($v in $arr){ if($v -notmatch '^[0-9A-Za-z\-]+$'){ throw "비정상 키: $v" } } }
Assert-Safe $advisory; Assert-Safe $request

function Run-Query([string]$sql){
    $conn = New-Object System.Data.SqlClient.SqlConnection $connStr
    $conn.Open()
    $cmd = $conn.CreateCommand(); $cmd.CommandText = $sql
    $da = New-Object System.Data.SqlClient.SqlDataAdapter $cmd
    $dt = New-Object System.Data.DataTable
    [void]$da.Fill($dt); $conn.Close(); return $dt
}

W "[*] 시작 $stamp  서버=$server DB=$database (읽기전용)"
try {
    $inA = ($advisory | ForEach-Object { "'$_'" }) -join ","
    $inR = ($request  | ForEach-Object { "'$_'" }) -join ","
    $cntA = (Run-Query "SELECT COUNT(*) AS c FROM APW_TS_Master WHERE MasterID IN ($inA)").Rows[0].c
    $cntR = (Run-Query "SELECT COUNT(*) AS c FROM APW_TS_Master WHERE MasterID IN ($inR)").Rows[0].c
    W ("[*] 자문번호 매칭 {0}건 / 의뢰번호 매칭 {1}건" -f $cntA, $cntR)
    if ($cntA -ge $cntR) { $useIn = $inA; W "[*] 매칭기준 = 자문번호" }
    else                 { $useIn = $inR; W "[*] 매칭기준 = 의뢰번호" }

    $dt = Run-Query "SELECT * FROM APW_TS_Master WHERE MasterID IN ($useIn)"
    W ("[*] 조회 행수={0} 컬럼수={1}" -f $dt.Rows.Count, $dt.Columns.Count)
    W ("[*] 컬럼: " + (($dt.Columns | ForEach-Object { $_.ColumnName }) -join ", "))
    $outCsv = Join-Path $here "APW_TS_Master_조회_$stamp.csv"
    $dt | Export-Csv -Path $outCsv -NoTypeInformation -Encoding UTF8
    W "[완료] CSV 저장: $outCsv"
}
catch { W "[!] 오류: $($_.Exception.Message)" }
W "[*] 종료"
