# gamexport.exe 재빌드 (Delphi 7, 정적 링크 = 런타임 BPL 불필요한 자체완결 exe)
#
# 배경: dcc32 단독 실행은 IDE 의 전역 라이브러리 경로를 모르고, 런타임 패키지(-LU)
# 방식은 .dcp 를 못 찾는다. 그래서 패키지 없이 정적 링크한다.
# gamexport 의 uses 는 SysUtils/Classes/DB/EasyTable 뿐이라 정적 링크로 충분하다.
#
# 사용: powershell -ExecutionPolicy Bypass -File delphi\build.ps1

$ErrorActionPreference = 'Stop'
$DCC = 'C:\Delphi7\Bin\dcc32.exe'
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 정적 링크에 필요한 .dcu 검색 경로(VCL 런타임 + EasyTable 및 그 의존).
$U = @(
  'C:\Delphi7\Lib',
  'C:\FRM7\Lib\DB\EasyTable',
  'C:\FRM7\Lib\DB\DacCore',
  'C:\FRM7\Lib\DB\SQLDac'
) -join ';'

$cfg = Join-Path $Dir 'gamexport.cfg'
@(
  '-$A8','-$B-','-$C+','-$D-','-$E-','-$F-','-$G+','-$H+','-$I+','-$J-','-$K-','-$L-',
  '-$M-','-$N+','-$O+','-$P+','-$Q-','-$R-','-$S-','-$T-','-$U-','-$V+','-$W-','-$X+','-$YD','-$Z1',
  '-cg','-H+','-W+','-M','-$M16384,1048576','-K$00400000',
  "-E`"$Dir`"",
  "-U`"$U`"",
  '-w-UNSAFE_TYPE','-w-UNSAFE_CODE','-w-UNSAFE_CAST'
) | Set-Content -Path $cfg -Encoding Ascii

Push-Location $Dir
try {
  & $DCC 'gamexport.dpr' | Select-Object -Last 2
  if ($LASTEXITCODE -ne 0) { throw "dcc32 failed ($LASTEXITCODE)" }
  Get-ChildItem 'gamexport.exe' | Select-Object Name, Length, LastWriteTime
} finally {
  Pop-Location
}
