// 목록·상세 패널 사이 경계를 드래그해 상세 패널 폭을 조절한다 (데스크톱 전용 공통).
// 더블클릭 시 기본 폭으로 복원, 조절값은 브라우저에 저장되어 다음 실행 때도 유지된다.
// 레이아웃 쌍:
//  - .workspace/.detail-panel  (감정서 LIST·입금·미수·매출실적) — CSS(has-panel-resizer)가 그리드 관리
//  - .bj-workspace/.bj-detail  (반제 2종),  .dq-workspace/.dq-detail (데이터 품질)
//    — 화면별 자체 그리드라 인라인 스타일로 3열(목록|핸들|상세) 전환
(function(){
  const PAIRS=[
    {ws:'.workspace',detail:'.detail-panel',cssManaged:true,minLeft:680},
    {ws:'.bj-workspace',detail:'.bj-detail',cssManaged:false,minLeft:520},
    {ws:'.dq-workspace',detail:'.dq-detail',cssManaged:false,minLeft:520},
  ];
  for(const cfg of PAIRS){
    const workspace=document.querySelector(cfg.ws);
    if(!workspace)continue;
    const detail=workspace.querySelector(cfg.detail);
    if(!detail)continue;
    attach(workspace,detail,cfg);
    return;
  }

  function attach(workspace,detail,cfg){
    const KEY=`a10.detailPanel.width:${location.pathname}`;
    const minLeft=Number(workspace.dataset.minLeft||cfg.minLeft);
    const clamp=width=>Math.min(Math.max(width,280),Math.max(320,workspace.getBoundingClientRect().width-minLeft-28));
    const apply=width=>{
      workspace.style.setProperty('--detail-width',`${Math.round(width)}px`);
      if(!cfg.cssManaged){
        workspace.style.gridTemplateColumns='minmax(0,1fr) 10px var(--detail-width)';
        workspace.style.columnGap='4px'; // 핸들 10px + 좌우 4px ≈ 원래 gap 유지
      }
    };
    const reset=()=>{
      workspace.style.removeProperty('--detail-width');
      if(!cfg.cssManaged){
        workspace.style.removeProperty('grid-template-columns');
        workspace.style.removeProperty('column-gap');
      }
      try{localStorage.removeItem(KEY)}catch(error){}
    };
    const handle=document.createElement('div');
    handle.className='panel-resizer';
    handle.title='드래그해서 상세 패널 폭 조절 (더블클릭: 기본값)';
    workspace.insertBefore(handle,detail);
    if(cfg.cssManaged)workspace.classList.add('has-panel-resizer');
    const saved=parseInt(localStorage.getItem(KEY)||'',10);
    if(saved)apply(clamp(saved));
    else if(!cfg.cssManaged)apply(clamp(detail.getBoundingClientRect().width||360));
    handle.addEventListener('dblclick',()=>{
      reset();
      // 자체 그리드 화면은 핸들이 남으므로 기본 폭으로 다시 3열 구성
      if(!cfg.cssManaged)apply(clamp(360));
    });
    handle.addEventListener('mousedown',event=>{
      event.preventDefault();
      const startX=event.clientX;
      const startWidth=detail.getBoundingClientRect().width;
      handle.classList.add('dragging');
      document.body.style.cursor='col-resize';
      const onMove=moveEvent=>apply(clamp(startWidth+(startX-moveEvent.clientX)));
      const onUp=()=>{
        handle.classList.remove('dragging');
        document.body.style.cursor='';
        document.removeEventListener('mousemove',onMove);
        document.removeEventListener('mouseup',onUp);
        try{localStorage.setItem(KEY,String(Math.round(detail.getBoundingClientRect().width)))}catch(error){}
      };
      document.addEventListener('mousemove',onMove);
      document.addEventListener('mouseup',onUp);
    });
  }
})();
