"use client";

import { FormEvent, useMemo, useState } from "react";

type Tab = "code" | "performance" | "dependency" | "history";

const procedures = [
  { name: "usp_GetOrderSummary", status: "warning", time: "2.84s" },
  { name: "usp_CreateShipment", status: "ok", time: "184ms" },
  { name: "usp_UpdateInventory", status: "ok", time: "92ms" },
  { name: "usp_CloseDailySales", status: "idle", time: "미사용 94일" },
  { name: "usp_GetCustomerGrade", status: "ok", time: "41ms" },
  { name: "usp_SyncPaymentStatus", status: "danger", time: "LOCK" },
];

const sqlLines = [
  { no: 1, text: "ALTER PROCEDURE [sales].[usp_GetOrderSummary]" },
  { no: 2, text: "    @CustomerId INT," },
  { no: 3, text: "    @StartDate DATETIME2," },
  { no: 4, text: "    @EndDate DATETIME2" },
  { no: 5, text: "AS" },
  { no: 6, text: "BEGIN" },
  { no: 7, text: "    SET NOCOUNT ON;" },
  { no: 8, text: "" },
  { no: 9, text: "    SELECT  o.OrderId," },
  { no: 10, text: "            o.OrderDate," },
  { no: 11, text: "            SUM(oi.Quantity * oi.UnitPrice) AS TotalAmount," },
  { no: 12, text: "            s.StatusName" },
  { no: 13, text: "    FROM sales.Orders o" },
  { no: 14, text: "    INNER JOIN sales.OrderItems oi ON oi.OrderId = o.OrderId" },
  { no: 15, text: "    LEFT JOIN common.OrderStatus s ON s.StatusId = o.StatusId" },
  { no: 16, text: "    WHERE o.CustomerId = @CustomerId" },
  { no: 17, text: "      AND CONVERT(VARCHAR(10), o.OrderDate, 120) >= @StartDate", hot: true },
  { no: 18, text: "      AND o.OrderDate < @EndDate" },
  { no: 19, text: "    GROUP BY o.OrderId, o.OrderDate, s.StatusName" },
  { no: 20, text: "    ORDER BY o.OrderDate DESC;" },
  { no: 21, text: "END" },
];

const navItems = ["대시보드", "데이터베이스", "성능 분석", "변경 승인", "알림 센터"];

function StatusDot({ status }: { status: string }) {
  return <span className={`status-dot ${status}`} aria-hidden="true" />;
}

export default function Home() {
  const [activeNav, setActiveNav] = useState("데이터베이스");
  const [activeProcedure, setActiveProcedure] = useState(procedures[0].name);
  const [tab, setTab] = useState<Tab>("code");
  const [query, setQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [notice, setNotice] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [approvalState, setApprovalState] = useState<"ready" | "requested">("ready");
  const [chatLog, setChatLog] = useState([
    { from: "ai", text: "usp_GetOrderSummary의 지연 원인을 찾았습니다. 17번째 줄에서 인덱스가 무효화되고 있습니다." },
  ]);

  const filteredProcedures = useMemo(
    () => procedures.filter((procedure) => procedure.name.toLowerCase().includes(query.toLowerCase())),
    [query],
  );

  function sendChat(event?: FormEvent) {
    event?.preventDefault();
    const message = chatInput.trim();
    if (!message) return;
    setChatLog((current) => [
      ...current,
      { from: "user", text: message },
      { from: "ai", text: "분석했습니다. 운영 반영 전 테스트 DB에서 결과 동일성과 실행 계획을 먼저 검증하겠습니다." },
    ]);
    setChatInput("");
  }

  function runQuickAction(label: string) {
    setChatLog((current) => [
      ...current,
      { from: "user", text: label },
      {
        from: "ai",
        text:
          label === "수정안 만들기"
            ? "날짜 컬럼의 CONVERT를 제거하는 수정안을 만들었습니다. 예상 논리 읽기는 128,340에서 2,140으로 감소합니다."
            : "최근 24시간 기준 평균 실행시간이 평소보다 4.7배 증가했습니다. 실행 계획 변경은 없고 테이블 스캔이 원인입니다.",
      },
    ]);
  }

  function requestApproval() {
    setApprovalState("requested");
    setNotice("운영 반영 승인 요청을 등록했습니다.");
    window.setTimeout(() => setNotice(""), 2800);
  }

  return (
    <main className="app-shell">
      <aside className="rail" aria-label="주 메뉴">
        <div className="brand-mark">D</div>
        <nav>
          {navItems.map((item, index) => (
            <button
              className={`rail-item ${activeNav === item ? "active" : ""}`}
              key={item}
              onClick={() => setActiveNav(item)}
              aria-label={item}
              title={item}
            >
              <span>{["⌂", "◫", "⌁", "✓", "!"][index]}</span>
            </button>
          ))}
        </nav>
        <div className="rail-spacer" />
        <button className="rail-item" title="설정" aria-label="설정">⚙</button>
        <div className="avatar">YJ</div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="product-title">
            <strong>DBA ONE</strong>
            <span>AI DATABASE OPERATOR</span>
          </div>
          <div className="connection-pill">
            <StatusDot status="ok" />
            <span className="engine-logo">MS</span>
            <span><b>ERP-PROD-01</b><small>Microsoft SQL Server 2022</small></span>
            <button aria-label="연결 서버 변경">⌄</button>
          </div>
          <div className="top-actions">
            <span className="environment-tag">PRODUCTION</span>
            <button className="icon-button" aria-label="알림">♢<i>3</i></button>
            <button className="help-button">?</button>
          </div>
        </header>

        <section className="health-strip" aria-label="서버 상태 요약">
          <div className="health-title"><StatusDot status="ok" /><span>서버 정상</span><small>방금 전 확인</small></div>
          <div className="health-stat"><span>CPU</span><b>38%</b><div className="meter"><i style={{ width: "38%" }} /></div></div>
          <div className="health-stat"><span>메모리</span><b>71%</b><div className="meter amber"><i style={{ width: "71%" }} /></div></div>
          <div className="health-stat"><span>활성 세션</span><b>42</b><small>/ 200</small></div>
          <div className="health-stat alert"><span>주의 필요</span><b>2</b><small>느린 쿼리 1 · Lock 1</small></div>
          <button className="text-button">전체 상태 보기 →</button>
        </section>

        <div className="main-grid">
          <aside className="object-panel">
            <div className="panel-heading">
              <div><span className="eyebrow">OBJECT EXPLORER</span><h2>ERP_MAIN</h2></div>
              <button className="square-button" title="새로고침" aria-label="객체 새로고침">↻</button>
            </div>
            <label className="search-box">
              <span>⌕</span>
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="객체 검색" />
              <kbd>⌘ K</kbd>
            </label>
            <div className="tree-group">
              <button className="tree-parent"><span>⌄</span><b>▱</b> sales <small>48</small></button>
              <button className="tree-child"><span>›</span><b>▦</b> 테이블 <small>18</small></button>
              <button className="tree-child"><span>›</span><b>▤</b> 뷰 <small>7</small></button>
              <button className="tree-child open"><span>⌄</span><b>ƒ</b> 프로시저 <small>14</small></button>
              <div className="procedure-list">
                {filteredProcedures.map((procedure) => (
                  <button
                    key={procedure.name}
                    className={activeProcedure === procedure.name ? "selected" : ""}
                    onClick={() => setActiveProcedure(procedure.name)}
                  >
                    <StatusDot status={procedure.status} />
                    <span>{procedure.name}</span>
                    <small>{procedure.time}</small>
                  </button>
                ))}
              </div>
              <button className="tree-parent collapsed"><span>›</span><b>▱</b> common <small>23</small></button>
              <button className="tree-parent collapsed"><span>›</span><b>▱</b> finance <small>31</small></button>
            </div>
            <button className="create-object" onClick={() => setShowCreate(true)}>＋ 새 프로시저</button>
          </aside>

          <section className="editor-panel">
            <div className="editor-header">
              <div>
                <div className="breadcrumb">ERP_MAIN / sales / 프로시저</div>
                <h1>{activeProcedure} <span className="badge warning">성능 주의</span></h1>
              </div>
              <div className="editor-actions">
                <button className="secondary-button" onClick={() => setNotice("테스트 실행을 시작했습니다.")}>▷ 테스트 실행</button>
                <button className="secondary-button">⋯</button>
                <button className="danger-outline" onClick={() => setShowDelete(true)}>삭제</button>
              </div>
            </div>

            <div className="tabs" role="tablist">
              {([
                ["code", "코드"],
                ["performance", "성능 분석"],
                ["dependency", "의존성"],
                ["history", "변경 이력"],
              ] as [Tab, string][]).map(([id, label]) => (
                <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)} role="tab">
                  {label}{id === "performance" && <i>1</i>}
                </button>
              ))}
            </div>

            {tab === "code" && (
              <>
                <div className="editor-toolbar">
                  <span className="file-state"><i /> 변경사항 없음</span>
                  <div><button>SQL 포맷</button><button>문법 검사</button><button>실행 계획</button></div>
                </div>
                <div className="code-editor" aria-label="프로시저 SQL 코드">
                  {sqlLines.map((line) => (
                    <div className={`code-line ${line.hot ? "hot" : ""}`} key={line.no}>
                      <span className="line-number">{line.no}</span>
                      <code>{line.text || " "}</code>
                      {line.hot && <button className="issue-marker" onClick={() => runQuickAction("수정안 만들기")}>AI 제안</button>}
                    </div>
                  ))}
                </div>
                <div className="analysis-banner">
                  <div className="analysis-icon">AI</div>
                  <div><strong>인덱스를 사용할 수 없는 조건이 발견되었습니다</strong><p>17번째 줄의 컬럼 변환으로 <code>IX_Orders_Customer_Date</code> 인덱스가 무시됩니다.</p></div>
                  <div className="impact-number"><span>예상 개선</span><b>6.4×</b></div>
                  <button className="primary-button" onClick={() => runQuickAction("수정안 만들기")}>수정안 보기</button>
                </div>
              </>
            )}

            {tab === "performance" && (
              <div className="tab-content">
                <div className="metric-cards">
                  <article><span>평균 실행시간</span><b>2.84s</b><small className="down">▲ 371% 증가</small></article>
                  <article><span>P95 실행시간</span><b>4.21s</b><small>기준 800ms</small></article>
                  <article><span>24시간 실행</span><b>18,420</b><small>분당 평균 12.8회</small></article>
                </div>
                <div className="chart-card">
                  <div><strong>최근 24시간 실행시간</strong><span>기준선 800ms</span></div>
                  <div className="bar-chart">{[18, 22, 17, 25, 29, 35, 42, 74, 49, 87, 64, 93, 58, 47, 39, 31].map((height, i) => <i key={i} style={{ height: `${height}%` }} />)}</div>
                </div>
              </div>
            )}

            {tab === "dependency" && (
              <div className="tab-content dependency-view">
                <div className="dependency-node main">{activeProcedure}</div>
                <div className="connector-row"><span>참조</span><span>호출</span></div>
                <div className="dependency-row"><div>sales.Orders</div><div>sales.OrderItems</div><div>Order API</div><div>Backoffice</div></div>
                <p>수정 시 영향 예상: API 1개, 화면 2개, 배치 1개</p>
              </div>
            )}

            {tab === "history" && (
              <div className="tab-content history-list">
                <article><span className="history-dot" /><div><b>v18 · 인덱스 힌트 제거</b><p>김DBA · 2026.07.12 14:22</p></div><button>비교</button></article>
                <article><span className="history-dot" /><div><b>v17 · 주문 상태 컬럼 추가</b><p>박개발 · 2026.06.28 09:41</p></div><button>비교</button></article>
                <article><span className="history-dot" /><div><b>v16 · 운영 배포</b><p>AI DBA 승인 작업 · 2026.06.02 18:05</p></div><button>복원</button></article>
              </div>
            )}
          </section>

          <aside className="ai-panel">
            <div className="ai-heading">
              <div className="ai-orb">AI</div>
              <div><h2>AI DBA</h2><span><StatusDot status="ok" /> 분석 준비됨</span></div>
              <button aria-label="AI 패널 닫기">×</button>
            </div>
            <div className="context-card">
              <span>현재 분석 대상</span>
              <strong>{activeProcedure}</strong>
              <small>sales · 운영 DB · 읽기 전용 분석</small>
            </div>
            <div className="chat-log">
              {chatLog.map((message, index) => (
                <div className={`chat-message ${message.from}`} key={`${message.from}-${index}`}>
                  {message.from === "ai" && <span className="mini-ai">AI</span>}
                  <p>{message.text}</p>
                </div>
              ))}
            </div>
            <div className="quick-actions">
              <button onClick={() => runQuickAction("왜 느려졌어?")}>왜 느려졌어?</button>
              <button onClick={() => runQuickAction("수정안 만들기")}>수정안 만들기</button>
            </div>
            <div className="approval-card">
              <div><span className="approval-icon">✓</span><strong>안전 검증 단계</strong></div>
              <ul><li className="done">문법 검사 완료</li><li className="done">영향 객체 4개 확인</li><li>테스트 DB 성능 비교 대기</li></ul>
              <button className="primary-button full" onClick={requestApproval} disabled={approvalState === "requested"}>
                {approvalState === "requested" ? "승인 요청됨" : "테스트 후 승인 요청"}
              </button>
            </div>
            <form className="chat-input" onSubmit={sendChat}>
              <textarea value={chatInput} onChange={(event) => setChatInput(event.target.value)} placeholder="AI DBA에게 요청하세요..." rows={2} />
              <div><span>운영 변경은 승인 후 실행됩니다</span><button aria-label="메시지 보내기">↑</button></div>
            </form>
          </aside>
        </div>
      </section>

      {notice && <div className="toast"><span>✓</span>{notice}</div>}

      {showCreate && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setShowCreate(false)}>
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="create-title" onMouseDown={(e) => e.stopPropagation()}>
            <div className="modal-title"><div><span>NEW PROCEDURE</span><h2 id="create-title">새 프로시저 만들기</h2></div><button onClick={() => setShowCreate(false)}>×</button></div>
            <label>스키마<select defaultValue="sales"><option>sales</option><option>common</option><option>finance</option></select></label>
            <label>프로시저 이름<input placeholder="usp_프로시저명" autoFocus /></label>
            <div className="template-choice"><button className="selected"><b>⌨</b>빈 코드로 시작<small>직접 SQL을 작성합니다</small></button><button><b>AI</b>AI로 생성<small>요구사항을 설명합니다</small></button></div>
            <div className="modal-actions"><button className="secondary-button" onClick={() => setShowCreate(false)}>취소</button><button className="primary-button" onClick={() => { setShowCreate(false); setNotice("새 프로시저 편집기를 열었습니다."); }}>편집기 열기</button></div>
          </section>
        </div>
      )}

      {showDelete && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setShowDelete(false)}>
          <section className="modal delete-modal" role="dialog" aria-modal="true" aria-labelledby="delete-title" onMouseDown={(e) => e.stopPropagation()}>
            <div className="delete-symbol">!</div>
            <h2 id="delete-title">프로시저를 삭제할까요?</h2>
            <p><b>{activeProcedure}</b>을 호출하는 API와 화면이 있습니다. 삭제 전 원본 DDL은 자동 백업됩니다.</p>
            <div className="risk-row"><span>영향 객체</span><b>4개</b><span>최근 실행</span><b>2분 전</b></div>
            <label>확인을 위해 프로시저 이름을 입력하세요<input placeholder={activeProcedure} /></label>
            <div className="modal-actions"><button className="secondary-button" onClick={() => setShowDelete(false)}>취소</button><button className="danger-button">삭제 승인 요청</button></div>
          </section>
        </div>
      )}
    </main>
  );
}
