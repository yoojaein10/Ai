// 표 컬럼 폭 드래그 조절 공통 유틸 (데스크톱 전용).
// A10_COLUMN_RESIZE(table, storageKey): colgroup 기반 표의 헤더 경계에 드래그 핸들을 붙인다.
// - 드래그로 폭 조절, 더블클릭 시 초기 폭 복원, 조절값은 localStorage에 저장되어 유지
// - 전표·계산서처럼 다시 그려지는 표는 렌더링 후마다 호출한다 (핸들 중복 부착 방지 내장)
(function(){
  window.A10_COLUMN_RESIZE=function(table,storageKey){
    if(!table)return;
    const cols=Array.from(table.querySelectorAll('colgroup col'));
    const headers=Array.from(table.querySelectorAll('thead th'));
    if(!cols.length||!headers.length)return;
    table.classList.add('resizable');
    const defaults=cols.map(col=>col.style.width||'');
    try{
      const saved=JSON.parse(localStorage.getItem(storageKey)||'[]');
      // 저장은 열 순서(index) 기준이라, 표의 열 구성이 바뀌면 폭이 엉뚱한 열에 붙는다.
      // 열 수가 다르면 예전 값을 버리고 기본 폭으로 시작한다.
      if(saved.length===cols.length){
        saved.forEach((width,index)=>{if(cols[index]&&width)cols[index].style.width=`${width}px`;});
      }else if(saved.length){
        localStorage.removeItem(storageKey);
      }
    }catch(error){/* 저장값이 깨졌으면 기본 폭을 쓴다 */}
    const save=()=>{
      try{localStorage.setItem(storageKey,JSON.stringify(cols.map(col=>parseInt(col.style.width,10)||0)));}catch(error){}
    };
    // 2단 헤더(rowspan/colspan)도 다루기 위해 헤더 격자를 만들어 컬럼별 담당 셀을 찾는다.
    // 핸들은 그 컬럼의 오른쪽 경계를 소유한 셀(마지막 헤더 행 기준)에만 붙인다.
    const owners=headerOwners(table,cols.length)||headers;
    owners.forEach((th,index)=>{
      if(!th||!cols[index]||th.querySelector('.col-resizer'))return;
      const handle=document.createElement('span');
      handle.className='col-resizer';
      handle.title='드래그해서 폭 조절 (더블클릭: 기본값)';
      th.appendChild(handle);
      handle.addEventListener('click',event=>event.stopPropagation());
      handle.addEventListener('dblclick',event=>{
        event.stopPropagation();
        cols[index].style.width=defaults[index];save();
      });
      handle.addEventListener('mousedown',event=>{
        event.preventDefault();event.stopPropagation();
        const startX=event.clientX;
        const startWidth=cols[index].getBoundingClientRect().width;
        handle.classList.add('dragging');
        const onMove=moveEvent=>{
          cols[index].style.width=`${Math.max(50,Math.round(startWidth+moveEvent.clientX-startX))}px`;
        };
        const onUp=()=>{
          handle.classList.remove('dragging');
          document.removeEventListener('mousemove',onMove);
          document.removeEventListener('mouseup',onUp);
          save();
        };
        document.addEventListener('mousemove',onMove);
        document.addEventListener('mouseup',onUp);
      });
    });
  };

  // thead를 rowspan/colspan까지 펼친 격자로 만들어, 컬럼 index별 담당 셀을 돌려준다.
  function headerOwners(table,colCount){
    const thead=table.querySelector('thead');
    if(!thead||!thead.rows.length)return null;
    const grid=[];
    Array.from(thead.rows).forEach((row,rowIndex)=>{
      let colIndex=0;
      Array.from(row.cells).forEach(cell=>{
        while(grid[rowIndex]&&grid[rowIndex][colIndex])colIndex++;
        const colspan=cell.colSpan||1;
        const rowspan=cell.rowSpan||1;
        for(let dr=0;dr<rowspan;dr++){
          const target=rowIndex+dr;
          grid[target]=grid[target]||[];
          for(let dc=0;dc<colspan;dc++){
            grid[target][colIndex+dc]={cell,endCol:colIndex+colspan-1};
          }
        }
        colIndex+=colspan;
      });
    });
    const lastRow=grid[grid.length-1]||[];
    const owners=[];
    for(let index=0;index<colCount;index++){
      const entry=lastRow[index];
      // 병합 셀은 오른쪽 끝 컬럼에서만 조절되게 한다 (중간 경계는 조절 대상 아님)
      owners[index]=entry&&entry.endCol===index?entry.cell:null;
    }
    return owners;
  }
})();
