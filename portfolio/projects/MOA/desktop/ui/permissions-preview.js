// 권한관리 개편 화면의 프런트 시안.
// 조직은 읽기 전용 API에서 가져오고 모든 권한 선택은 브라우저 메모리에서만 바뀐다.
let offices = [];
// 일괄권한(2026-08-13). 부서 줄의 선택칸과 개인 편집칸이 같이 쓴다.
let roleCatalog = [];                 // [{role_id,name,...}]
let rolesLoadFailed = false;          // 일괄권한 목록 fetch 실패 — '비었음' 과 구분(2026-08-19 감사)
const deptRoleMap = new Map();        // 'office|dept' -> role_id
// 부서 권한을 **안 따라가는** 사람들. 개인 일괄권한이나 개인 예외가 부서를
// 이기기 때문이다(2026-08-17 인사이동 확인: 지인자는 본사로 옮긴 뒤에도
// 옛 8종을 그대로 들고 있었다). 화면이 이걸 안 그리면 담당자는 '적용
// 했습니다'를 믿게 되는데, 그중 몇 명은 실제로 안 바뀐다.
const userRoleMap = new Map();        // usr_seq -> role_id (개인 일괄권한)
const personalOverrides = new Set();  // usr_seq (개인 예외)


const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
}[char]));

let selectedEmployee = null;
let expanded = new Set();
const menuPermissionOverrides = new Map();
const viewAllOverrides = new Map();
const viewOtherUsersOverrides = new Map();

// 메뉴 목록의 **원본은 사이드바**(context.js 의 A10_MENU)다. 이 화면은 그 이름과
// 순서를 그대로 따라간다 — 담당자는 사이드바에서 본 이름으로 권한을 찾는다.
// 2026-08-15 대조에서 이 표가 사이드바와 어긋나 있었다:
//   이름 4건이 옛 이름('매출 입력'·'내 매출실적'·'…반제리스트')으로 남아 있었고,
//   실제 있는 메뉴 셋(보수기준 점검·입금 대사·수수료 검토)이 **아예 빠져** 있어
//   그 권한은 이 화면에서 켜고 끌 방법이 없었다.
// 이름을 고칠 일이 생기면 context.js 를 먼저 고치고 여기를 맞춘다
// (tests/test_permission_menu_names.py 가 둘이 같은지 지킨다).
//
// access 는 '누구에게 토글을 보여 줄까'이고, 서버 정책이 오면 그쪽이 이긴다
// (availableMenuKeys 가 serverPolicy 를 먼저 본다). 값은 access_policy.py 의
// SHARED/HEAD_OFFICE*/BRANCH_FINANCE 집합과 맞춘 것이다.
const menuGroups = [
  {
    name: '업무',
    items: [
      {key: 'appraisals', name: '감정서 LIST', short: '감', description: '감정서 조회 및 진행상태 확인', access: 'shared'},
    ],
  },
  {
    name: '입금·미수',
    items: [
      {key: 'payments', name: '입금 현황', short: '입', description: '입금 내역과 수금 현황 조회', access: 'shared'},
      // 서버는 paymentSms 를 본사 재무와 '지사 재무담당 개인지정'에게만 준다
      // (HEAD_OFFICE_FINANCE + BRANCH_FINANCE). shared 로 적혀 있어 지사 일반
      // 직원에게도 토글이 보였다 — 켜도 서버가 막는 헛 토글이었다.
      {key: 'paymentSms', name: '입금발송내역', short: '문', description: '입금 알림톡 발송 내역(본사 재무·지사 재무담당). 발송은 본사만', access: 'financeOrBranchFinance'},
      {key: 'receivables', name: '미수금 현황', short: '미', description: '미수금 잔액과 경과 현황 조회', access: 'shared'},
      {key: 'allocation', name: '배분 수금 진행', short: '배', description: '배분과 수금 진행상태 확인', access: 'shared'},
      {key: 'bankReconcile', name: '일계표 대사', short: '계', description: '사이버브랜치 입·출금과 아마란스 보통예금 전표 대사(본사 재무 개별권한)', access: 'headOfficePrivileged'},
      {key: 'shinhanDelay', name: '신한 발송기한', short: '신', description: '신한은행 발송기한(접수 후 4영업일) 관리 — 메뉴 밖 독립 화면(/desktop/shinhan-delay), 개인 예외로만', access: 'headOfficePrivileged'},
      {key: 'taxBulk', name: '계산서 등록', short: '등', description: '외부 발행·국세청 매출 자료 엑셀을 발급 원장에 등록(본사 재무·집행부)', access: 'headOfficeOperations'},
    ],
  },
  {
    name: '매출·실적',
    items: [
      {key: 'salesStats', name: '기간별 매출실적', short: '실', description: '기간·부서별 매출 집계(본·지사, 기본 ON은 재무담당)', access: 'shared'},
      {key: 'workReport', name: '업무실적 보고', short: '업', description: '업무실적 집계 보고(본·지사, 기본 ON은 재무담당)', access: 'shared'},
      // 빠져 있던 메뉴 ①. 사이드바에는 있는데 여기 없어서 권한을 줄 수 없었다.
      {key: 'feeBasis', name: '보수기준 점검', short: '보', description: '보수기준 적용 점검(본사 재무·지사 재무담당). 지사는 자기 지사 건', access: 'financeOrBranchFinance'},
      // 2026-08-10 '매출 입력' → '유치실적' 으로 바뀌었는데 여기만 옛 이름이었다.
      {key: 'salesInput', name: '유치실적', short: '유', description: '유치실적 배분·승인 입력(본사 재무·집행부)', access: 'headOfficeOperations'},
      {key: 'bonus', name: '상여', short: '상', description: '상여 산정·조정 입력(본사 재무·집행부)', access: 'headOfficeOperations'},
      {key: 'travelExpense', name: '출장비', short: '출', description: '출장비 입력·결재·월별 현황 — APWorks 출장비프로그램 이식(본사 전 직원, 결재자는 APWorks 결재자 명단)', access: 'headOffice'},
      // 사이드바 이름은 '개인별 매출실적' 이다. 서버도 본사 재무 집합에만 있다.
      {key: 'mySales', name: '개인별 매출실적', short: '개', description: '평가사 본인 매출 대시보드(본인 것만, 본사 재무는 지정 조회)', access: 'financeOnly'},
    ],
  },
  {
    name: '카드·반제',
    items: [
      {key: 'cardVouchers', name: '카드전표', short: '카', description: '카드 명세서로 전표 생성·전송(본사 재무)', access: 'headOfficeOperations'},
      {key: 'receivableReconcile', name: '외상매출금 반제', short: '외', description: '외상매출금 반제 내역 확인', access: 'headOffice'},
      {key: 'advanceReconcile', name: '선수금 반제', short: '선', description: '선수금 반제 내역 확인', access: 'headOffice'},
    ],
  },
  {
    name: '관리·점검',
    items: [
      {key: 'accountLedger', name: '지사별원장', short: '원', description: '지사 계정 원장 조회·메일 발송', access: 'headOfficePrivileged'},
      {key: 'dataQuality', name: '데이터 품질 점검', short: '품', description: '누락·불일치 데이터 점검', access: 'headOfficePrivileged'},
      // 빠져 있던 메뉴 ②.
      {key: 'depositMatch', name: '입금 대사', short: '대', description: '입금 건을 감정서에 맞춰 보는 대사(본사 재무)', access: 'financeOnly'},
      {key: 'reconcile', name: '엑셀 대사', short: '엑', description: '회계 자료와 전표 엑셀 대사', access: 'headOfficePrivileged'},
      // 이 키 하나가 '권한 관리'와 '일괄권한' 두 화면을 함께 연다 — 키를 나누면
      // 한쪽만 열린 사람이 생긴다(context.js A10_MENU 주석과 같은 판단).
      {key: 'permissionManage', name: '권한 관리', short: '권', description: '사용자별 조회범위와 메뉴 권한 관리 (일괄권한 화면도 이 키로 열립니다)', access: 'individualAdmin'},
    ],
  },
];

const allMenuItems = menuGroups.flatMap(group => group.items);
const allMenuKeys = allMenuItems.map(item => item.key);
const branchAppraiserDefaultMenus = new Set([
  'appraisals',
  'payments', 'receivables', 'mySales',
]);
// 본사 평가사도 지사 평가사와 동일하게 감정서·입금현황·미수금현황 3종만 기본.
const headOfficeAppraiserDefaultMenus = new Set(branchAppraiserDefaultMenus);
// 본사 집행부 기본 노출 메뉴(사용자 지정): 감정서·입금·미수금·기간별매출실적·매출입력·상여.
// 화면 통일로 다른 본사 토글도 보이지만 기본은 이 6개만 켠다.
const headOfficeExecutiveDefaultMenus = new Set([
  'appraisals', 'payments', 'receivables', 'salesStats', 'salesInput', 'bonus',
  'allocation',
]);
const headOfficeFinanceDefaultMenus = new Set(allMenuKeys);
const branchFinanceDefaultMenus = new Set([
  'appraisals', 'payments', 'receivables',
  'workReport', 'salesStats', 'allocation',
  // 입금발송내역: 지사 재무담당자도 본다(조회 범위는 서버가 자기 지사로 강제).
  'paymentSms',
]);
const appraiserDepartments = new Set([
  '감사부', '심사부', '주주평가사', '명예평가사',
  '예비주주평가사', '소속평가사', '수습평가사', '평가사',
]);

function allEmployees() {
  return offices.flatMap(office => office.departments.flatMap(department =>
    department.employees.map(employee => ({...employee, office, department}))
  ));
}

function selectedEmployeeKey() {
  return `${selectedEmployee.office.id}:${selectedEmployee.id}`;
}

function isBranchGeneralEmployee(employee = selectedEmployee) {
  return employee.office.id !== '10' && !employee.is_appraiser;
}

function isHeadOfficeExecutiveOrFinance(employee = selectedEmployee) {
  // 본사에서 조회 범위 기본값이 '전체'인 부서 — 집행부(묶음이 Y·Y) + 관리팀(재무팀·
  // 전산정보팀, access_policy.HEAD_OFFICE_FULL_ACCESS_DEPARTMENTS 와 일치시킨다).
  // 전산정보팀이 빠져 있어, 그 부서 사람의 스코프 토글이 실제(ON)와 달리 OFF 로
  // 잘못 표시됐다(2026-08-19 원동하 사례). 백엔드 상수와 맞춘다.
  return employee.office.id === '10'
    && (employee.department.name === '집행부'
        || employee.department.name === '재무팀'
        || employee.department.name === '전산정보팀');
}

function isBranchFinanceEmployee(employee = selectedEmployee) {
  if (!isBranchGeneralEmployee(employee)) return false;
  const permissions = menuPermissionOverrides.get(
    `${employee.office.id}:${employee.id}`
  );
  return Boolean(permissions && permissions.size);
}

function menuPolicy(item, employee = selectedEmployee) {
  const isHeadOffice = employee.office.id === '10';
  if (item.access === 'shared') {
    return {
      available: true,
      badge: isHeadOffice ? '본·지사' : '소속지사',
    };
  }
  if (item.access === 'headOffice') {
    return {available: isHeadOffice, badge: '본사 전용'};
  }
  if (item.access === 'headOfficePrivileged') {
    return {available: isHeadOffice, badge: '본사 · 개별권한'};
  }
  if (item.access === 'financeOnly') {
    // 본사 재무 업무. 본사는 전 직원에게 토글을 보여 준다(역할상 기본 off).
    return {available: isHeadOffice, badge: '본사'};
  }
  if (item.access === 'financeOrBranchFinance') {
    // 본사 재무 + **지사 재무담당(개인 지정 18명)**. 서버는 이 둘에게 주는데
    // (BRANCH_FINANCE_MENU_KEYS) 화면이 financeOnly 로 묶어 지사에서 토글을
    // 통째로 감췄다 — 서버는 주는데 권한 담당자가 끄고 켤 수가 없었다
    // (2026-08-17 전수조사). 서버 정책이 오면 그쪽이 최종 판정이다.
    return {available: true, badge: isHeadOffice ? '본사' : '지사 재무담당'};
  }
  if (item.access === 'headOfficeOperations') {
    // 본사 데이터 입력 화면(매출입력·상여). 본사는 전 직원에게 토글 노출(역할상 기본 off),
    // 지사는 미노출(본사 데이터 전용).
    const available = isHeadOffice;
    return {available, badge: '본사'};
  }
  return {available: true, badge: isHeadOffice ? '본사 · 개별권한' : '소속 지사 · 개별권한'};
}

function availableMenuKeys(employee = selectedEmployee) {
  // 서버 정책이 로드됐으면 백엔드 available을 신뢰한다(지사 재무담당자 등 개인 지정 반영).
  const serverMenus = employee && employee.serverPolicy && employee.serverPolicy.menus;
  if (Array.isArray(serverMenus)) {
    return new Set(serverMenus.filter(m => m.available).map(m => m.key));
  }
  return new Set(
    allMenuItems
      .filter(item => menuPolicy(item, employee).available)
      .map(item => item.key)
  );
}

function departmentDefaultMenus(employee = selectedEmployee) {
  // 서버 정책이 로드됐으면 백엔드 기본값을 신뢰한다(부서 휴리스틱 대신 개인 지정까지 반영).
  const serverMenus = employee && employee.serverPolicy && employee.serverPolicy.menus;
  if (Array.isArray(serverMenus)) {
    return new Set(serverMenus.filter(m => m.default).map(m => m.key));
  }
  const departmentName = employee.department.name || '';
  const isHeadOffice = employee.office.id === '10';
  if (isHeadOffice) {
    if (departmentName === '재무팀') return new Set(headOfficeFinanceDefaultMenus);
    if (departmentName === '집행부') return new Set(headOfficeExecutiveDefaultMenus);
    if (appraiserDepartments.has(departmentName)) return new Set(headOfficeAppraiserDefaultMenus);
    return new Set();  // 본사 일반직원
  }
  // 지사: 집행부·평가사만 감정서·입금·미수금 3종, 나머지(재무·일반)는 권한 없음.
  if (departmentName === '집행부' || employee.is_appraiser || appraiserDepartments.has(departmentName)) {
    return new Set(branchAppraiserDefaultMenus);
  }
  return new Set();
}

function effectiveMenuPermissions() {
  const override = menuPermissionOverrides.get(selectedEmployeeKey());
  const available = availableMenuKeys();
  return new Set(
    [...(override || departmentDefaultMenus())].filter(key => available.has(key))
  );
}

function setsEqual(left, right) {
  return left.size === right.size && [...left].every(value => right.has(value));
}

function saveMenuOverride(nextPermissions) {
  const defaults = departmentDefaultMenus();
  const available = availableMenuKeys();
  const sanitizedPermissions = new Set(
    [...nextPermissions].filter(key => available.has(key))
  );
  const key = selectedEmployeeKey();
  if (setsEqual(sanitizedPermissions, defaults)) {
    menuPermissionOverrides.delete(key);
  } else {
    menuPermissionOverrides.set(key, sanitizedPermissions);
  }
}

// 조회 범위 기본값은 **서버가 준 값**(serverPolicy.defaults, 묶음에서 계산)을 쓴다.
// 부서이름 추정(isHeadOfficeExecutiveOrFinance)은 클린모델 서버 기본값과 어긋나,
// 저장 시 전지사/남열람을 몰래 부여·회수했다(2026-08-19 감사: 총무팀 회수·집행부
// 부여·지사재무 남열람 상향). 서버정책이 로드되기 전 잠깐만 부서추정으로 그린다.
function defaultViewAll() {
  const sp = selectedEmployee && selectedEmployee.serverPolicy;
  if (sp && sp.defaults) return Boolean(sp.defaults.view_all_offices);
  return isHeadOfficeExecutiveOrFinance();
}
function defaultViewOther() {
  const sp = selectedEmployee && selectedEmployee.serverPolicy;
  if (sp && sp.defaults) return Boolean(sp.defaults.view_other_users);
  return isHeadOfficeExecutiveOrFinance() || isBranchFinanceEmployee();
}

function effectiveViewAll() {
  const key = selectedEmployeeKey();
  return viewAllOverrides.has(key)
    ? viewAllOverrides.get(key)
    : defaultViewAll();
}

function effectiveViewOtherUsers() {
  const key = selectedEmployeeKey();
  return viewOtherUsersOverrides.has(key)
    ? viewOtherUsersOverrides.get(key)
    : defaultViewOther();
}

function renderTree() {
  const officeFilter = $('officeFilter').value;
  const query = $('employeeSearch').value.trim().toLocaleLowerCase('ko');
  const filteredOffices = offices
    .filter(office => officeFilter === 'all' || office.id === officeFilter)
    .map(office => ({
      ...office,
      departments: office.departments.map(department => ({
        ...department,
        employees: department.employees.filter(employee => {
          if (!query) return true;
          return [employee.name, employee.title, department.name, department.category, office.name]
            .filter(Boolean)
            .some(value => value.toLocaleLowerCase('ko').includes(query));
        }),
      })).filter(department => department.employees.length),
    })).filter(office => office.departments.length);

  const count = filteredOffices.reduce((total, office) =>
    total + office.departments.reduce((sum, department) => sum + department.employees.length, 0), 0);
  $('employeeCount').textContent = query
    ? `검색 결과 ${count}명`
    : officeFilter !== 'all'
      ? `${offices.find(office => office.id === officeFilter).name} ${count}명`
      : `재직 사용자 ${allEmployees().length}명`;

  if (officeFilter !== 'all') expanded.add(`office-${officeFilter}`);
  if (!filteredOffices.length) {
    $('organizationTree').innerHTML = '<div class="tree-empty">조건에 맞는 직원이 없습니다.</div>';
    return;
  }

  if (query) {
    filteredOffices.forEach(office => {
      expanded.add(`office-${office.id}`);
      office.departments.forEach(department => expanded.add(`dept-${office.id}-${department.name}`));
    });
  }

  $('organizationTree').innerHTML = filteredOffices.map(office => {
    const officeKey = `office-${office.id}`;
    const officeCount = office.departments.reduce((sum, department) => sum + department.employees.length, 0);
    return `<div class="tree-node tree-office ${expanded.has(officeKey) ? '' : 'collapsed'}" data-key="${escapeHtml(officeKey)}">
      <button class="tree-row office" type="button" role="treeitem" aria-expanded="${expanded.has(officeKey)}">
        <span class="tree-caret">▼</span><span class="tree-icon">지</span>
        <span>${escapeHtml(office.name)}</span><span class="tree-count">${officeCount}</span>
      </button>
      <div class="tree-children" role="group">
        ${office.departments.map(department => renderDepartment(office, department)).join('')}
      </div>
    </div>`;
  }).join('');

  // 지사 줄은 종전대로 줄 전체가 접기/펴기다.
  document.querySelectorAll('.tree-node>.tree-row.office').forEach(button => {
    button.addEventListener('click', () => toggleNode(button.parentElement, button));
  });
  // 부서 줄은 캐럿만 접기/펴기를 맡는다 — 부서명은 권한 화면을 연다.
  document.querySelectorAll('.tree-caret-button').forEach(button => {
    button.addEventListener('click', event => {
      event.stopPropagation();
      toggleNode(button.closest('.tree-node'), button);
    });
  });
  document.querySelectorAll('.tree-row.department').forEach(button => {
    button.addEventListener('click', () => {
      // 부서명을 누르면 사람 이름을 누른 것과 같은 화면이 열린다. 접힌 부서는
      // 함께 펴 준다 — 권한을 보러 왔는데 소속이 안 보이면 확인이 안 된다.
      const node = button.closest('.tree-node');
      if (node.classList.contains('collapsed')) {
        toggleNode(node, node.querySelector('.tree-caret-button'));
      }
      openDepartment(button.dataset.office, button.dataset.dept);
    });
  });
  document.querySelectorAll('.employee-row').forEach(button => {
    button.addEventListener('click', () => selectEmployee(
      button.dataset.office,
      button.dataset.department,
      button.dataset.employee,
    ));
  });
}

// ── 부서 권한 (2026-08-16 요청) ──────────────────────────────────────────
//
// 부서명을 누르면 **사람을 누른 것과 같은 화면**이 열린다. 같은 토글로 권한을
// 주고, 다른 점은 대상이 사람 하나가 아니라 그 부서 전원이라는 것뿐이다.
//
// 저장은 일괄권한(a10_access_role)으로 나간다 — 서버에는 '부서에 메뉴를 직접
// 박는' 길이 없고, 있어서도 안 된다. 부서 여러 곳에 같은 권한을 주려면 일괄권한
// 하나를 공유해야 나중에 한 곳만 고쳐도 전부 따라온다.
//   · 켠 조합과 **똑같은 일괄권한이 이미 있으면 그걸 붙인다**(재사용)
//   · 없으면 그 부서 이름으로 일괄권한을 만들어 붙인다
// 담당자는 일괄권한을 몰라도 되지만, 무엇이 붙었는지는 요약에 늘 보여 준다.
let selectedDepartment = null;      // {office, department} — 열려 있으면 값이 있다
let deptDraft = null;               // {menus:Set, viewAll:'Y'|'N'|'', viewOther:...}

const roleKeyOf = (menuKeys, viewAll, viewOther) =>
  [...menuKeys].sort().join(',') + '|' + viewAll + '|' + viewOther;

const flagToChar = value => (value === true ? 'Y' : value === false ? 'N' : '');
const charToFlag = value => (value === 'Y' ? true : value === 'N' ? false : null);

/** 부서 권한을 볼 때 쓰는 가짜 직원. menuPolicy 가 소속만 보므로 그것만 채운다. */
function deptStandIn() {
  const {office, department} = selectedDepartment;
  return {office, department, is_appraiser: false, id: '', serverPolicy: null};
}

function deptAvailableKeys() {
  const stand = deptStandIn();
  return allMenuItems.filter(item => menuPolicy(item, stand).available).map(item => item.key);
}

function openDepartment(officeId, departmentName) {
  const office = offices.find(item => item.id === officeId);
  if (!office) return;
  const department = office.departments.find(item => item.name === departmentName);
  if (!department) return;
  selectedDepartment = {office, department};

  // 지금 이 부서에 붙어 있는 일괄권한을 초안으로 삼는다 — 빈 화면에서 시작하면
  // 이미 준 권한을 모른 채 처음부터 다시 찍게 된다.
  const roleId = deptRoleMap.get(office.id + '|' + department.name);
  const role = roleCatalog.find(item => item.role_id === roleId) || null;
  deptDraft = {
    menus: new Set(role ? role.menu_keys : []),
    viewAll: role ? flagToChar(role.view_all_offices) : '',
    viewOther: role ? flagToChar(role.view_other_users) : '',
    baseKey: role
      ? roleKeyOf(role.menu_keys, flagToChar(role.view_all_offices),
                  flagToChar(role.view_other_users))
      : roleKeyOf([], '', ''),
  };

  $('employeePanel').hidden = true;
  $('departmentPanel').hidden = false;
  renderDepartmentPanel();
  renderTree();
}

function closeDepartment() {
  selectedDepartment = null;
  deptDraft = null;
  $('departmentPanel').hidden = true;
  $('employeePanel').hidden = false;
  renderTree();
}

function renderDepartmentPanel() {
  if (!selectedDepartment || !deptDraft) return;
  const {office, department} = selectedDepartment;
  const stand = deptStandIn();
  const available = new Set(deptAvailableKeys());
  const on = [...deptDraft.menus].filter(key => available.has(key));

  $('deptName').textContent = department.name;
  $('deptMeta').textContent = office.name + ' · ' + department.employees.length + '명';
  $('deptSummaryOffice').textContent = office.name;
  $('deptSummaryPeople').textContent = department.employees.length + '명';
  // 조회 범위 토글(2026-08-18 부서 패널에 되살림). 전체지사조회는 본사 전용이라
  // 지사 부서에는 섹션을 숨긴다(백엔드도 지사엔 강제로 끈다). 개인내역조회는 모두.
  const isHeadOfficeDept = office.id === '10';
  $('deptViewAllSection').classList.toggle('hidden', !isHeadOfficeDept);
  $('deptViewAllToggle').checked = isHeadOfficeDept && deptDraft.viewAll === 'Y';
  $('deptViewOtherToggle').checked = deptDraft.viewOther === 'Y';
  $('deptSummaryScope').textContent =
    (isHeadOfficeDept && deptDraft.viewAll === 'Y' ? '전체지사 · ' : '')
    + (deptDraft.viewOther === 'Y' ? '다른 직원까지' : '자기 데이터만');
  $('deptSummaryMenus').textContent = on.length + ' / ' + available.size;
  $('deptMenuCount').textContent = on.length + ' / ' + available.size + ' 허용';

  const currentId = deptRoleMap.get(office.id + '|' + department.name);
  const current = roleCatalog.find(item => item.role_id === currentId);
  // '일괄권한'은 구현 사정이다 — 담당자에게는 세트 이름이거나 '기본값'이면 된다.
  $('deptSummaryRole').textContent = current
    ? (current.memo === AUTO_ROLE_MEMO ? '이 부서 전용' : current.name)
    : '기본값';

  // 조회 범위(전지사·남의실적)는 2026-08-17 부터 일괄권한이 정한다 — 부서 화면에
  // 토글을 두지 않는다. deptDraft.viewAll/viewOther 는 붙어 있는 일괄권한의 값을
  // 그대로 나르고(읽기 전용), 요약 카드에만 결과가 보인다.

  // 이름 붙인 세트를 프리셋으로 — 누르면 토글이 채워지고, 저장하면 정확히
  // 일치하는 그 세트가 붙어 나중에 세트를 고치면 부서도 따라온다.
  paintPresetMenu('deptPresets', 'deptPresetPick', 'deptPresetMenu',
                  new Set(deptAvailableKeys()), 'dept', selectedDepartment.office.id);

  // 본사 재무팀·전산정보팀(관리팀)은 권한관리를 부서로 줄 수 있다(2026-08-18 사용자
  // 지정) — 이 부서에서는 권한관리 토글을 잠그지 않는다. 나머지 부서는 그대로 잠근다.
  const adminDept = office.id === '10'
    && (department.name === '재무팀' || department.name === '전산정보팀');

  // 메뉴 토글 — 사람 화면(renderMenuPermissions)과 **같은 마크업**을 쓴다.
  // 부서를 눌렀는데 다른 모양이 나오면 같은 일을 하는 화면으로 안 읽힌다.
  $('deptMenuGroups').innerHTML = menuGroups.map(group => {
    const visibleItems = group.items.filter(item => menuPolicy(item, stand).available);
    if (!visibleItems.length) return '';
    const groupAllowed = visibleItems.filter(item => deptDraft.menus.has(item.key)).length;
    const rows = visibleItems.map(item => {
      const policy = menuPolicy(item, stand);
      const allowed = deptDraft.menus.has(item.key);
      // 권한관리(permissionManage)는 **부서로 줄 수 없다** — 부서 전원이 관리자가 되고,
      // 인원이 늘면 자동으로 관리자가 늘어난다. 토글을 잠가 실수로 켜서 저장 때 거절
      // 에러를 만나는 일을 원천 차단한다. 이 권한은 권한관리 화면에서 개인에게 지정한다.
      // 예외: 본사 재무팀·전산정보팀(관리팀)은 부서로도 권한관리를 줄 수 있다(2026-08-18).
      const locked = item.key === 'permissionManage' && !adminDept;
      return '<label class="menu-permission-row ' + (allowed ? 'allowed ' : '')
        + (locked ? 'locked' : '') + '"'
        + (locked ? ' title="권한 관리는 부서로 줄 수 없습니다 — 개인에게 지정하세요"' : '') + '>'
        + '<span class="menu-row-icon">' + escapeHtml(item.short) + '</span>'
        + '<span class="menu-row-copy"><span class="menu-row-title">'
        + '<strong>' + escapeHtml(item.name) + '</strong>'
        + ''
        + '</span></span>'
        + '<span class="inline-switch"><input class="dept-menu-toggle" type="checkbox"'
        + ' data-menu-key="' + escapeHtml(item.key) + '"' + (allowed ? ' checked' : '')
        + (locked ? ' disabled' : '') + '>'
        + '<i class="switch-control"></i></span></label>';
    }).join('');
    return '<section class="menu-permission-group"><header class="menu-group-heading">'
      + '<h4>' + escapeHtml(group.name) + '</h4>'
      + '<span>' + groupAllowed + ' / ' + visibleItems.length + ' 허용</span>'
      + '</header><div>' + rows + '</div></section>';
  }).join('');

  document.querySelectorAll('.dept-menu-toggle').forEach(toggle => {
    toggle.addEventListener('change', () => {
      if (toggle.checked) deptDraft.menus.add(toggle.dataset.menuKey);
      else deptDraft.menus.delete(toggle.dataset.menuKey);
      renderDepartmentPanel();
    });
  });

  const dirty = roleKeyOf(on, deptDraft.viewAll, deptDraft.viewOther) !== deptDraft.baseKey;
  // 개인 설정(개인 일괄권한·예외)이 걸린 사람 수 — 부서 저장이 이들을 부서값으로 되돌린다.
  const held = department.employees.filter(personalSettingOf).length;
  $('deptImpact').textContent = dirty
    ? '이 부서 ' + department.employees.length + '명에게 바로 적용됩니다'
    : held
      ? '개인 설정 ' + held + '명을 부서값으로 되돌립니다'
      : '부서 권한';
  $('deptChangeStatus').textContent = !on.length
    ? '메뉴가 하나도 없습니다 — 저장하면 이 부서 사람은 로그인 자체가 거절됩니다.'
    : dirty
      ? '변경 있음'
      : held
        ? '개인 설정 ' + held + '명 있음 — 저장하면 부서값으로 초기화됩니다'
        : '적용 중';
  // 부서 저장은 '이 부서를 이 일괄권한으로 통일'이다 — 일괄권한이 그대로여도 개인 설정을
  // 되돌리는 초기화 역할이 있으므로, 되돌릴 사람이 있으면 버튼을 연다(2026-08-19 신고).
  $('deptApply').disabled = !dirty && held === 0;
}

function deptAllowAll() {
  if (!deptDraft) return;
  deptDraft.menus = new Set(deptAvailableKeys());
  renderDepartmentPanel();
}

function deptDenyAll() {
  if (!deptDraft) return;
  deptDraft.menus = new Set();
  renderDepartmentPanel();
}

/** 부서 저장이 만든 자동 일괄권한의 표식. memo 가 이 값이면 화면이 '이 부서 전용'
 *  으로 다루고, 프리셋 목록에서도 뺀다 — 자동 일괄권한까지 버튼으로 늘어놓으면
 *  부서 수만큼 쌓인다. */
const AUTO_ROLE_MEMO = '부서 권한 화면에서 만든 묶음';

/** 확인창에 넣을 세트 요약 — 이름만 보고 적용하지 않게, 무엇이 열리는지 적는다. */
function presetSummary(role, keys) {
  const names = keys.map(key => {
    const item = allMenuItems.find(entry => entry.key === key);
    return item ? item.name : key;
  });
  const menuLine = names.length
    ? names.slice(0, 8).join(' · ') + (names.length > 8 ? ' 외 ' + (names.length - 8) + '개' : '')
    : '없음 — 로그인 자체가 거절됩니다!';
  return "'" + role.name + "' 일괄권한 — 메뉴 " + keys.length + '개' + '\n' + menuLine;
}

/** 세트 한 줄. 이름만 있는 칩과 달리 **무엇을 주는지**를 함께 보여 준다 —
 *  이름만 보고 부서 전원을 바꾸지 않게 하려는 것이 이 화면의 원칙이다.
 *
 *  개수는 반드시 **이 대상에게 실제로 열릴 것**으로 센다(available 교집합).
 *  세트 원본으로 세면, 본사 전용만 든 세트가 지사 대상에게 '메뉴 8개'라고
 *  초록으로 말해 놓고 적용하면 0개 = 로그인 거절이 된다 — 새로 넣은 경고색이
 *  정확히 필요한 자리에서 반대로 말한다(2026-08-17 적대 검증).
 */
function presetRow(role, available, kind) {
  const all = role.menu_keys || [];
  const keys = available ? all.filter(key => available.has(key)) : all.slice();
  const cut = all.length - keys.length;
  const head = keys.length
    ? '메뉴 ' + keys.length + '개'
      + (cut ? ' (일괄권한 ' + all.length + '개 중 이 대상에 ' + keys.length + '개)' : '')
    : '메뉴 없음 — 로그인 거절';
  // 부서는 세트가 붙어 따라오고, 사람은 지금 값만 복사된다 — 결정적 차이라
  // 확인창에만 두지 않고 행에도 남긴다.
  const note = kind === 'person' ? ' · 값만 복사' : '';
  return '<button type="button" class="preset-row' + (keys.length ? '' : ' danger')
    + '" data-preset="' + role.role_id + '">'
    + '<b>' + escapeHtml(role.name) + '</b>'
    + '<span>' + head + note + '</span></button>';
}

/** 세트 드롭다운을 채운다. 세트가 없으면 통째로 감춘다 — 빈 메뉴는 소음이다.
 *
 *  **매 렌더마다 닫는다.** 대상이 바뀐 뒤에도 열려 있으면 그건 남의 대상에서
 *  연 팝오버다 — 사용자가 열지 않은 목록이 새 대상 위에 펼쳐진 채 나타나
 *  '열고→고르고→확인' 의 첫 걸음이 사라진다(2026-08-17 적대 검증).
 */
function paintPresetMenu(listId, pickId, menuId, available, kind, officeId) {
  const box = $(listId);
  if (!box) return;
  const sets = namedPresets(officeId);   // 대상 소속의 일괄권한만(공용 없는 지사별)
  const menu = $(menuId);
  // 세트가 0개여도 드롭다운을 숨기지 않는다 — 그 안의 '일괄권한 만들기·관리' 가 권한
  // 일괄권한 화면으로 가는 **유일한 문**이라, 숨기면 세트를 다 지운 담당자가 새로 만들
  // 길이 없어 갇힌다(2026-08-18). 빈 목록엔 안내만 둔다.
  if (menu) menu.open = false;
  // 대상이 다시 그려질 때 고른 세트 표시를 지운다 — 다른 사람/부서로 넘어가면
  // 남의 선택이 요약에 남지 않게. 세트를 누르면 클릭 핸들러가 이 뒤에 채운다.
  if ($(pickId)) $(pickId).textContent = '';
  box.innerHTML = sets.length
    ? sets.map(role => presetRow(role, available, kind)).join('')
    : (rolesLoadFailed
        ? '<p class="preset-empty">일괄권한을 불러오지 못했습니다. 새로고침해 주세요.</p>'
        : '<p class="preset-empty">아직 만든 일괄권한이 없습니다.</p>');
}

/** 열려 있는 세트 목록을 모두 닫는다. */
function closePresetMenus() {
  document.querySelectorAll('details.preset-menu[open]')
    .forEach(menu => { menu.open = false; });
}

/** 이름을 사람이 붙인 세트만 — 프리셋 버튼감. officeId 를 주면 **그 소속 일괄권한만**
 *  (공용 없는 지사별 일괄권한, 2026-08-18): 21지사 사람을 편집하면 21지사 일괄권한만 뜨고
 *  타지사 건 안 뜬다. officeId 가 없으면(과도기 등) 소속 필터를 걸지 않는다. */
function namedPresets(officeId) {
  return roleCatalog.filter(role =>
    role.memo !== AUTO_ROLE_MEMO
    && (officeId == null || String(role.office_id) === String(officeId)));
}

/** 일괄권한 저장 한 번. 잠금(409)이면 사람에게 묻고 다시 보낸다 — 붙어 있는 일괄권한을
 *  고치는 것도 부서 전원을 바꾸는 일이라 서버가 되묻는다(save_role, 2026-08-16). */
async function postRole(body) {
  const send = confirmed => fetch('/api/permissions/roles', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({...body, confirm_lockout: Boolean(confirmed)}),
  });
  let res = await send(false);
  let payload = await res.json().catch(() => null);
  if (res.status === 409 && payload && payload.code === 'ROLE_LOCKOUT_CONFIRM') {
    if (!window.confirm(payload.message + '\n\n계속할까요?')) {
      throw new Error('저장하지 않았습니다.');
    }
    res = await send(true);
    payload = await res.json().catch(() => null);
  }
  return {ok: Boolean(res.ok && payload && payload.success !== false), payload};
}

/** 초안을 일괄권한으로 옮긴다. 재사용 → 제자리 갱신 → 새로 만들기 순서다. */
async function resolveDraftRole() {
  const available = new Set(deptAvailableKeys());
  const keys = [...deptDraft.menus].filter(key => available.has(key));
  // 세트(이름 붙은 일괄권한)를 부서에 걸어도 **참조하지 않고 그 부서 전용 자동일괄권한으로
  // 복사**한다 (2026-08-18 사용자 결정: "부서도 개인처럼 복사로"). 개인 편집기가
  // 세트를 개인 예외로 복사하는 것과 같은 뜻이다. 이렇게 해야 이름 붙은 세트는
  // 아무도 '쓰는 곳'으로 참조하지 않아, 일괄권한 화면에서 언제든 지울 수 있다.
  // 대신 세트를 나중에 고쳐도 이미 적용해 둔 부서는 안 따라온다 — 공유가 아니라
  // 복사이기 때문이다. 종전엔 조합이 같은 일괄권한을 찾아 재사용(참조)했고, 그래서
  // 세트가 '쓰는 곳'에 걸려 삭제가 막혔다. 그 ①단계를 걷어냈다.
  const {office, department} = selectedDepartment;
  const currentId = deptRoleMap.get(office.id + '|' + department.name);
  const current = roleCatalog.find(item => item.role_id === currentId);
  const base = {
    menu_keys: keys,
    view_all_offices: charToFlag(deptDraft.viewAll),
    view_other_users: charToFlag(deptDraft.viewOther),
    memo: AUTO_ROLE_MEMO,
  };

  // ② 이 부서 1곳만 쓰는 자동 일괄권한이면 새로 만들지 않고 제자리에서 고친다.
  //    종전에는 두 번째 저장마다 같은 이름으로 새 일괄권한을 만들려다 중복 이름
  //    거절에 걸렸다 — 담당자가 두 번째 사용에서 반드시 만나는 막다른길이었다
  //    (2026-08-16 감사). 다른 부서·사람도 쓰는 일괄권한은 여기서 고치면 그쪽까지
  //    바뀌므로 손대지 않는다.
  const used = (current && current.used_by) || {departments: 0, users: 0};
  if (current && current.memo === AUTO_ROLE_MEMO
      && used.departments === 1 && !used.users) {
    const {ok, payload} = await postRole({...base, role_id: current.role_id, name: current.name});
    if (!ok) throw new Error((payload && payload.message) || '부서 권한을 고치지 못했습니다.');
    await loadRoles();
    return current.role_id;
  }

  // ③ 새 자동 일괄권한. 이름이 이미 있으면(예전 조합이 차지) 번호를 붙여 다시 본다.
  for (let n = 0; n < 5; n += 1) {
    const name = '자동 · ' + office.name + ' ' + department.name + (n ? ' (' + (n + 1) + ')' : '');
    const {ok, payload} = await postRole({...base, name});
    if (ok) {
      await loadRoles();
      return payload.data.role_id;
    }
    const message = (payload && payload.message) || '';
    if (!message.includes('이미 있는')) {
      throw new Error(message || '일괄권한을 만들지 못했습니다.');
    }
  }
  throw new Error('같은 이름의 자동 일괄권한이 너무 많습니다. 일괄권한 화면에서 정리해 주세요.');
}

/** 부서에 저장. 잠금이 생기면 서버가 409 로 되묻는다. */
async function applyDepartment() {
  if (!selectedDepartment || !deptDraft) return;
  const {office, department} = selectedDepartment;
  const button = $('deptApply');
  const msg = $('deptMsg');
  msg.className = 'msg';
  msg.textContent = '저장 중…';
  button.disabled = true;
  try {
    const roleId = await resolveDraftRole();
    const send = confirmed => fetch('/api/permissions/departments', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        office_id: office.id, department_name: department.name,
        role_id: roleId, confirm_lockout: Boolean(confirmed),
      }),
    });
    let res = await send(false);
    let body = await res.json().catch(() => null);
    // 메뉴 0개는 빈 화면이 아니라 로그인 거절이다 — 부서 전원을 조용히 잠그면 안 된다.
    if (res.status === 409 && body && body.code === 'ROLE_LOCKOUT_CONFIRM') {
      if (!window.confirm(body.message + '\n\n계속할까요?')) {
        msg.textContent = '저장하지 않았습니다.';
        return;
      }
      res = await send(true);
      body = await res.json().catch(() => null);
    }
    if (!res.ok || (body && body.success === false)) {
      msg.textContent = (body && body.message) || '저장하지 못했습니다.';
      msg.className = 'msg bad';
      return;
    }
    deptRoleMap.set(office.id + '|' + department.name, roleId);
    const kept = [...deptDraft.menus].filter(key => new Set(deptAvailableKeys()).has(key));
    deptDraft.baseKey = roleKeyOf(kept, deptDraft.viewAll, deptDraft.viewOther);
    // 이 부서 사람들에게 남아 있던 옛 화면 시드를 비운다 — 부서 권한이
    // 바뀌었으니 예전 기준으로 계산해 둔 값은 더는 사실이 아니다.
    // 다음 클릭에서 서버값으로 다시 시드된다(loadServerPolicy 가 매번 재조회).
    // 부서 저장 = 복사/덮어쓰기라 이 부서 개인 일괄권한·예외는 서버에서 전부 내려갔다 —
    // 개인 설정 표식(userRoleMap·personalOverrides)도 함께 비워, 트리의 '개인' 표시와
    // held 계산이 즉시 맞게 한다(안 비우면 이미 초기화됐는데도 버튼이 계속 열려 있다).
    department.employees.forEach(emp => {
      const seq = Number(emp.usr_seq);
      if (seq) { userRoleMap.delete(seq); personalOverrides.delete(seq); }
      const staleKey = office.id + ':' + emp.id;
      menuPermissionOverrides.delete(staleKey);
      viewAllOverrides.delete(staleKey);
      viewOtherUsersOverrides.delete(staleKey);
    });
    // 서버가 실제로 한 일을 사실대로 알린다. skipped=되돌릴 개인 설정도 없고 일괄권한도
    // 그대로였다(진짜 no-op) — '적용했습니다'라고 하면 안 바뀐 걸 바꿨다고 오해시킨다.
    const data = (body && body.data) || {};
    if (data.skipped) {
      msg.textContent = '이미 부서값입니다 — 되돌릴 개인 설정이 없습니다.';
    } else {
      const resetCount = data.reset_count || 0;
      msg.textContent = department.employees.length + '명에게 적용했습니다.'
        + (resetCount ? ' 개인 설정 ' + resetCount + '명을 부서값으로 초기화했습니다.' : '');
    }
    msg.className = 'msg good';
    renderTree();
  } catch (error) {
    msg.textContent = error.message || '서버에 연결하지 못했습니다.';
    msg.className = 'msg bad';
  } finally {
    // 저장이 끝나면 baseKey·userRoleMap 이 갱신됐으니 여기서 다시 그린다 — 그러면
    // 버튼이 '!dirty && held===0' 규칙대로 스스로 잠긴다. 예전엔 disabled=false 로 강제로
    // 열어, 초기화가 끝났는데도 버튼이 계속 열려 헛클릭·오해 문구를 불렀다(2026-08-19 리뷰).
    renderDepartmentPanel();
  }
}

/** 트리 마디를 접거나 편다. 지사 줄과 부서 캐럿이 함께 쓴다. */
function toggleNode(node, button) {
  const key = node.dataset.key;
  if (node.classList.toggle('collapsed')) expanded.delete(key);
  else expanded.add(key);
  if (button) button.setAttribute('aria-expanded', String(!node.classList.contains('collapsed')));
}

function renderDepartment(office, department) {
  const key = `dept-${office.id}-${department.name}`;
  // 지금 오른쪽에 열려 있는 부서를 트리에서도 표시한다 — 어느 부서를 보고
  // 있는지 모른 채 저장하면 엉뚱한 부서가 바뀐다.
  const open = Boolean(selectedDepartment
    && selectedDepartment.office.id === office.id
    && selectedDepartment.department.name === department.name);
  return `<div class="tree-node ${expanded.has(key) ? '' : 'collapsed'}" data-key="${escapeHtml(key)}">
    <div class="dept-row-wrap">
      <!-- 캐럿만 접기/펴기를 맡는다. 부서명은 **사람 이름과 같이** 권한 화면을
           연다 (2026-08-16 요청) — 한 버튼이 둘 다 하면 권한을 열려다 접힌다. -->
      <button class="tree-caret-button" type="button"
        aria-expanded="${expanded.has(key)}"
        aria-label="${escapeHtml(department.name)} 펼치기/접기"><span class="tree-caret">▼</span></button>
      <button class="tree-row department ${open ? 'selected' : ''}" type="button" role="treeitem"
        aria-selected="${open}"
        data-office="${escapeHtml(office.id)}" data-dept="${escapeHtml(department.name)}">
        <span class="tree-icon">부</span>
        <span>${escapeHtml(department.name)}</span>
        <span class="tree-count">${department.employees.length}</span>
      </button>
    </div>
    <div class="tree-children" role="group">
      ${department.employees.map(employee => {
        const selected = selectedEmployee && selectedEmployee.id === employee.id
          && !selectedDepartment;
        // 이름 옆 '개인' 딱지는 2026-08-18 뺐다(사용자 요청).
        return `<button class="tree-row employee-row ${selected ? 'selected' : ''}" type="button"
          data-office="${escapeHtml(office.id)}" data-department="${escapeHtml(department.name)}"
          data-employee="${escapeHtml(employee.id)}" role="treeitem" aria-selected="${selected}">
          <span class="employee-dot">${escapeHtml(employee.name.slice(0, 1))}</span>
          <span class="employee-copy"><strong>${escapeHtml(employee.name)}</strong>${employee.title ? `<small>${escapeHtml(employee.title)}</small>` : ''}</span>
        </button>`;
      }).join('')}
    </div>
  </div>`;
}

function selectEmployee(officeId, departmentName, employeeId) {
  // 사람을 고르면 부서 패널은 닫는다 — 둘이 같은 자리를 쓴다.
  if (selectedDepartment) {
    selectedDepartment = null;
    $('departmentPanel').hidden = true;
    $('employeePanel').hidden = false;
  }
  const office = offices.find(item => item.id === officeId);
  const department = office.departments.find(item => item.name === departmentName);
  const employee = department.employees.find(item => item.id === employeeId);
  selectedEmployee = {...employee, office, department};
  renderSelectedEmployee();
  renderTree();
  loadServerPolicy();
}

function renderMenuPermissions() {
  // account_linked 사람은 loadServerPolicy 가 서버값(진짜 권한)을 곧 가져온다. 그 전에
  // 폴백(부서 휴리스틱)값으로 토글을 그리면, 서버값이 오며 **몇 개가 왔다갔다** 한다
  // (2026-08-18 사용자 지적). 서버값이 아직이면(그리고 실패도 아직 아니면) 토글을 안
  // 그리고 로딩만 둔다 — loadServerPolicy 가 값을 채운 뒤 다시 부르면서 한 번에 그린다.
  if (selectedEmployee.account_linked && selectedEmployee.usr_seq
      && !selectedEmployee.serverPolicy && !selectedEmployee.serverPolicyFailed) {
    $('menuPermissionGroups').innerHTML =
      '<p class="preset-empty">현재 권한을 불러오는 중…</p>';
    $('summaryMenus').textContent = '…';
    $('menuPermissionCount').textContent = '불러오는 중…';
    $('previewChangeStatus').textContent = '이 직원의 현재 권한을 불러오는 중입니다…';
    return;
  }
  const permissions = effectiveMenuPermissions();
  const defaults = departmentDefaultMenus();
  const available = availableMenuKeys();
  const hasCustomMenus = menuPermissionOverrides.has(selectedEmployeeKey());
  const isHeadOffice = selectedEmployee.office.id === '10';
  const changedMenuCount = allMenuKeys.filter(key =>
    permissions.has(key) !== defaults.has(key)
  ).length;

  $('summaryMenus').textContent = `${permissions.size} / ${available.size}`;
  $('menuPermissionCount').textContent = `${permissions.size} / ${available.size} 허용`;
  // 메뉴 출처 배지(menuSourceBadge)는 2026-08-18 걷어냈다(자잘한 표시 정리 —
  // 사용자 요청). 권한 값은 토글이 그대로 보여 주므로 출처 문구는 없어도 된다.
  // 사람에게는 세트 값을 **복사**만 한다 — 세트를 나중에 고쳐도 이 사람은 안
  // 따라온다(부서와 다른 점). 행의 '값만 복사' 표시와 확인창이 그걸 말한다.
  paintPresetMenu('personPresets', 'personPresetPick', 'personPresetMenu',
                  available, 'person', selectedEmployee.office.id);
  $('allowAllMenus').classList.toggle('hidden', !isHeadOffice);
  $('denyAllMenus').classList.toggle('hidden', !isHeadOffice);
  $('previewChangeStatus').textContent = hasCustomMenus
    || viewAllOverrides.has(selectedEmployeeKey())
    || viewOtherUsersOverrides.has(selectedEmployeeKey())
    ? '개인 설정 있음'
    : '부서 권한 적용 중';

  $('menuPermissionGroups').innerHTML = menuGroups.map(group => {
    // 부여할 수 없는 메뉴는 감춘다 — 지사 직원에게는 본사 전용 메뉴가 아예 안 보인다.
    const visibleItems = group.items.filter(item => menuPolicy(item).available);
    if (!visibleItems.length) return '';  // 그룹 전체가 본사 전용이면 그룹째 숨긴다.
    const groupAllowed = visibleItems.filter(item => permissions.has(item.key)).length;
    return `<section class="menu-permission-group">
      <header class="menu-group-heading">
        <h4>${escapeHtml(group.name)}</h4>
        <span>${groupAllowed} / ${visibleItems.length} 허용</span>
      </header>
      <div>
        ${visibleItems.map(item => {
          const policy = menuPolicy(item);
          const allowed = policy.available && permissions.has(item.key);
          const individuallyChanged = allowed !== defaults.has(item.key);
          return `<label class="menu-permission-row ${allowed ? 'allowed' : ''} ${individuallyChanged ? 'custom' : ''} ${policy.available ? '' : 'locked'}">
            <span class="menu-row-icon">${escapeHtml(item.short)}</span>
            <span class="menu-row-copy">
              <span class="menu-row-title">
                <strong>${escapeHtml(item.name)}</strong>
              </span>
            </span>
            <span class="inline-switch">
              <input class="menu-permission-toggle" type="checkbox"
                data-menu-key="${escapeHtml(item.key)}" ${allowed ? 'checked' : ''} ${policy.available ? '' : 'disabled'}>
              <i class="switch-control"></i>
            </span>
          </label>`;
        }).join('')}
      </div>
    </section>`;
  }).join('');

  document.querySelectorAll('.menu-permission-toggle').forEach(toggle => {
    toggle.addEventListener('change', () => {
      const nextPermissions = effectiveMenuPermissions();
      if (toggle.checked) nextPermissions.add(toggle.dataset.menuKey);
      else nextPermissions.delete(toggle.dataset.menuKey);
      saveMenuOverride(nextPermissions);
      renderSelectedEmployee();
    });
  });
}

function renderSelectedEmployee() {
  const {employeeOffice, employeeDepartment} = {
    employeeOffice: selectedEmployee.office,
    employeeDepartment: selectedEmployee.department,
  };
  const isHeadOffice = employeeOffice.id === '10';
  const category = isBranchFinanceEmployee()
    ? '지사 재무 담당'
    : selectedEmployee.is_appraiser
      ? '평가사'
      : isHeadOffice
        ? employeeDepartment.category
        : '일반직원';

  $('selectedAvatar').textContent = selectedEmployee.name.slice(0, 1);
  $('selectedName').textContent = selectedEmployee.name;
  $('selectedStatus').textContent = category;
  $('selectedMeta').textContent = [...new Set([
    employeeOffice.name, employeeDepartment.name, selectedEmployee.title,
  ].filter(Boolean))].join(' · ');
  $('summaryCategory').textContent = category;
  $('summaryOffice').textContent = employeeOffice.name;

  // 조회 범위 토글(2026-08-18 사람별로 되살림). 전지사는 본사만(지사는 숨김),
  // 개인내역은 본사·지사 모두. 기본값(server.defaults)과 다르게 켠 것만 저장된다.
  // serverPolicy 로딩 중엔 토글을 잠그고 '불러오는 중' 으로 둔다 — 메뉴 패널과 같은
  // 가드다. 안 그러면 로딩 동안 부서추정값을 보였다가 실값으로 튕긴다(2026-08-19 감사).
  const scopeLoading = selectedEmployee.account_linked && selectedEmployee.usr_seq
    && !selectedEmployee.serverPolicy && !selectedEmployee.serverPolicyFailed;
  $('viewAllSection').classList.toggle('hidden', !isHeadOffice);
  $('viewAllToggle').disabled = !isHeadOffice || scopeLoading;
  $('viewAllToggle').checked = isHeadOffice && effectiveViewAll();
  $('scopePolicyCard').classList.toggle('locked', !isHeadOffice);
  $('scopeTitle').textContent = isHeadOffice ? '다른 지사 데이터 조회 허용' : `${employeeOffice.name}만 조회`;
  $('summaryScope').textContent = scopeLoading ? '불러오는 중…'
    : (isHeadOffice && effectiveViewAll()) ? '전체지사' : employeeOffice.name;
  // 개인내역(남의실적)은 모든 직원에게 조정 가능 — 지사 재무 담당도 켠다.
  const viewOtherUsers = effectiveViewOtherUsers();
  const officeScopeText = (isHeadOffice && effectiveViewAll()) ? '전체지사' : employeeOffice.name;
  $('viewOtherUsersToggle').disabled = scopeLoading;
  $('viewOtherUsersToggle').checked = viewOtherUsers;
  $('peopleScopeCard').classList.toggle('enabled', viewOtherUsers);
  $('peopleScopeTitle').textContent = viewOtherUsers ? '다른 직원 데이터 조회 허용' : '자기 데이터만 조회';
  $('summaryPeopleScope').textContent = scopeLoading ? '불러오는 중…'
    : viewOtherUsers ? '다른 직원까지' : '자기 데이터만';
  renderMenuPermissions();

}

// 토글을 만지면 기본값과 다를 때만 개인 예외(override 맵)에 남긴다 — 같으면 지운다.
function updatePreviewPermission() {
  const isHeadOffice = selectedEmployee.office.id === '10';
  const key = selectedEmployeeKey();
  const nextValue = isHeadOffice && $('viewAllToggle').checked;
  if (nextValue === defaultViewAll()) {
    viewAllOverrides.delete(key);
  } else {
    viewAllOverrides.set(key, nextValue);
  }
  renderSelectedEmployee();
}

function updatePeopleScopePermission() {
  // 2026-08-18: 평가사 전용 제한을 걷어냈다 — 개인내역은 본사·지사 모두 조정한다.
  const key = selectedEmployeeKey();
  const nextValue = $('viewOtherUsersToggle').checked;
  const defaultValue = defaultViewOther();
  if (nextValue === defaultValue) {
    viewOtherUsersOverrides.delete(key);
  } else {
    viewOtherUsersOverrides.set(key, nextValue);
  }
  renderSelectedEmployee();
}

function resetPreviewPermission() {
  menuPermissionOverrides.delete(selectedEmployeeKey());
  viewAllOverrides.delete(selectedEmployeeKey());
  viewOtherUsersOverrides.delete(selectedEmployeeKey());
  renderSelectedEmployee();
  showToast('부서 권한으로 되돌렸습니다 — "변경사항 저장"을 눌러야 적용됩니다.');
}

// '부서 기본값' 빠른 설정 버튼은 걷어냈다 (2026-08-16 요청). 이 화면의 '부서
// 기본값' 은 사람마다 코드에서 계산되는 값이라 담당자가 손댈 수 없는 것이었는데,
// 버튼으로 서 있으니 '부서 권한을 여기서 정한다' 는 오해를 샀다. 부서 권한은
// 이제 부서 패널(openDepartment)에서 일괄권한으로 정한다.
// 개인의 예외를 지우는 일은 헤더의 '초기화'(resetPreviewPermission)가 그대로 한다.

// applyBranchFinanceMenus(지사 재무 권한 적용 버튼)는 2026-08-18 걷어냈다 — 이제
// 지사마다 자기 재무 일괄권한을 따로 만들어 붙인다(공용 없는 지사별 일괄권한).

function allowAllMenus() {
  saveMenuOverride(availableMenuKeys());
  renderSelectedEmployee();
  showToast('메뉴를 모두 허용했습니다 — "변경사항 저장"을 눌러야 적용됩니다.');
}

function denyAllMenus() {
  saveMenuOverride(new Set());
  renderSelectedEmployee();
  showToast('모든 메뉴를 해제했습니다. "변경사항 저장"을 눌러야 적용됩니다.');
}

function showToast(message) {
  const toast = $('previewToast');
  toast.textContent = message;
  toast.classList.remove('hidden');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add('hidden'), 2800);
}

// 선택한 직원의 실제 정책(기본값·현재 적용값)을 서버에서 불러와 토글을 초기화한다.
// 서버 effective로 시드하므로 기존에 저장된 개인 예외도 화면에 그대로 나타난다.
async function loadServerPolicy() {
  const emp = selectedEmployee;
  if (!emp || !emp.account_linked || !emp.usr_seq) return;
  const usrSeq = emp.usr_seq;
  try {
    const response = await fetch(`/api/permissions/users/${encodeURIComponent(usrSeq)}`);
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      // 종전에는 조용히 return 해서, 담당자 본인이 '권한 관리' 를 잃어 403
      // (MENU_ACCESS_DENIED)이 나도 화면이 아무 말 없이 옛 값을 그대로 보여 줬다 —
      // '권한이 안 먹었다' 로 오해된다(2026-08-18 실측). 이유를 알린다.
      // 401 은 context.js 재로그인 래퍼가 이미 처리하므로 건드리지 않는다.
      if (response.status === 403) {
        showToast('이 직원의 현재 권한을 불러올 수 없습니다 — 내 「권한 관리」 권한이 '
          + '바뀌었을 수 있습니다. 화면을 새로고침해 확인해 주세요.');
      } else if (response.status !== 401) {
        showToast('현재 권한을 불러오지 못했습니다. 잠시 뒤 다시 눌러 주세요.');
      }
      // 서버값을 못 받았으면 로딩에 멈추지 않게 폴백값으로 그린다(왔다갔다 방지용
      // 로딩 가드가 영원히 로딩만 두지 않도록).
      if (selectedEmployee && String(selectedEmployee.usr_seq) === String(usrSeq)) {
        selectedEmployee.serverPolicyFailed = true;
        renderSelectedEmployee();
      }
      return;
    }
    // 조회 도중 다른 직원으로 바뀌었으면 반영하지 않는다.
    if (!selectedEmployee || String(selectedEmployee.usr_seq) !== String(usrSeq)) return;
    const policy = payload.data;
    selectedEmployee.serverPolicy = policy;
    const key = selectedEmployeeKey();
    const effectiveMenus = new Set(
      policy.menus.filter(item => item.available && item.effective).map(item => item.key)
    );
    saveMenuOverride(effectiveMenus);
    if (selectedEmployee.office.id === '10'
        && policy.effective.view_all_offices !== policy.defaults.view_all_offices) {
      viewAllOverrides.set(key, policy.effective.view_all_offices);
    } else {
      viewAllOverrides.delete(key);
    }
    if (policy.effective.view_other_users !== policy.defaults.view_other_users) {
      viewOtherUsersOverrides.set(key, policy.effective.view_other_users);
    } else {
      viewOtherUsersOverrides.delete(key);
    }
    renderSelectedEmployee();
  } catch (_error) {
    // 서버 조회 실패(네트워크 등) — 로딩에 멈추지 않게 폴백값으로 그린다.
    if (selectedEmployee && String(selectedEmployee.usr_seq) === String(usrSeq)) {
      selectedEmployee.serverPolicyFailed = true;
      renderSelectedEmployee();
    }
  }
}

// 현재 화면의 토글을 개인 예외로 저장한다 — 서버가 준 기본값(일괄권한 반영)과 다른
// 항목만 override 로 보낸다. 기준이 서버값이어야 일괄권한 메뉴가 예외로 안 굳는다.
async function savePermission() {
  if (!selectedEmployee || !selectedEmployee.account_linked || !selectedEmployee.usr_seq) {
    showToast('APWorks 로그인 계정이 연결된 직원만 저장할 수 있습니다.');
    return;
  }
  if (!window.A10_CTX || !window.A10_CTX.usr_seq) {
    showToast('로그인 정보를 확인할 수 없어 저장할 수 없습니다.');
    return;
  }
  // 서버 정책 없이 저장하면 diff 기준이 JS 폴백 기본값으로 떨어져, 부서 일괄권한이
  // 준 메뉴가 통째로 개인 예외(a10_access_policy)로 굳는다 — 이후 일괄권한을 고쳐도
  // 이 사람만 안 따라온다(2026-08-16 감사). 한 번 더 받아 보고, 그래도 없으면
  // 저장하지 않는다.
  if (!selectedEmployee.serverPolicy) {
    await loadServerPolicy();
  }
  if (!selectedEmployee.serverPolicy) {
    showToast('이 직원의 현재 권한을 불러오지 못해 저장할 수 없습니다. 잠시 뒤 다시 눌러 주세요.');
    return;
  }
  const server = selectedEmployee.serverPolicy;
  const isHeadOffice = selectedEmployee.office.id === '10';
  const available = availableMenuKeys();
  const effective = effectiveMenuPermissions();
  const menuDefaults = new Set(server.menus.filter(item => item.default).map(item => item.key));
  const menuOverrides = {};
  available.forEach(key => {
    const allowed = effective.has(key);
    if (allowed !== menuDefaults.has(key)) menuOverrides[key] = allowed;
  });
  // 조회 범위: 토글값이 기본값(server.defaults)과 다를 때만 개인 예외로 보낸다.
  // 같으면 null(=예외 없음). 전지사는 본사에서만 값을 가진다(지사는 늘 null).
  const viewAllDefault = server ? server.defaults.view_all_offices : isHeadOfficeExecutiveOrFinance();
  const viewAllValue = isHeadOffice && effectiveViewAll();
  const viewAllOffices = (isHeadOffice && viewAllValue !== viewAllDefault) ? viewAllValue : null;
  const viewOtherDefault = server
    ? server.defaults.view_other_users
    : (isHeadOfficeExecutiveOrFinance() || isBranchFinanceEmployee());
  const viewOtherValue = effectiveViewOtherUsers();
  const viewOtherUsers = (viewOtherValue !== viewOtherDefault) ? viewOtherValue : null;
  const memoInput = $('saveMemo');
  const memo = memoInput && memoInput.value.trim() ? memoInput.value.trim() : null;

  const button = $('saveButton');
  button.disabled = true;
  try {
    const response = await fetch(`/api/permissions/users/${encodeURIComponent(selectedEmployee.usr_seq)}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        requester_usr_seq: Number(window.A10_CTX.usr_seq),
        view_all_offices: viewAllOffices,
        view_other_users: viewOtherUsers,
        menu_overrides: menuOverrides,
        active: true,
        memo,
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      showToast(payload.message || '저장에 실패했습니다.');
      return;
    }
    showToast(`${selectedEmployee.name} 권한을 저장했습니다.`);
    if (memoInput) memoInput.value = '';
    await loadServerPolicy();
  } catch (error) {
    showToast(`저장 중 오류가 발생했습니다: ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

function changeOfficeFilter() {
  const officeId = $('officeFilter').value;
  if (officeId !== 'all' && selectedEmployee.office.id !== officeId) {
    const office = offices.find(item => item.id === officeId);
    const department = office.departments[0];
    const employee = department.employees[0];
    selectedEmployee = {...employee, office, department};
    renderSelectedEmployee();
    // 클릭 경로(selectEmployee)와 같이 서버 정책을 불러온다 — 안 부르면 메뉴 패널이
    // '불러오는 중' 에서 멈춰, 담당자가 그 사람을 한 번 더 눌러야 풀렸다(2026-08-19 감사).
    loadServerPolicy();
  }
  renderTree();
}

$('officeFilter').addEventListener('change', changeOfficeFilter);
$('employeeSearch').addEventListener('input', renderTree);
$('viewAllToggle').addEventListener('change', updatePreviewPermission);
$('viewOtherUsersToggle').addEventListener('change', updatePeopleScopePermission);
$('resetButton').addEventListener('click', resetPreviewPermission);
$('allowAllMenus').addEventListener('click', allowAllMenus);
$('denyAllMenus').addEventListener('click', denyAllMenus);
$('saveButton').addEventListener('click', savePermission);
// 부서 권한 패널 (2026-08-16). 부서명 옆 '부서 권한' 을 누르면 열린다.
$('deptClose').addEventListener('click', closeDepartment);
$('deptApply').addEventListener('click', applyDepartment);
// 열린 팝오버는 아래 메뉴 토글을 덮는다(z-index:20, 최대 320px). <details> 는
// 바깥 클릭·Esc 로 안 닫히므로, 토글을 누르려다 프리셋 행을 누르는 길이 생긴다
// — 그 한 번이 부서 전원 적용으로 이어진다(2026-08-17 적대 검증). 직접 닫는다.
// pointerdown 캡처 단계에서 잡아 클릭이 행에 닿기 전에 닫는다.
document.addEventListener('pointerdown', event => {
  if (!event.target.closest('.preset-menu')) closePresetMenus();
}, true);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closePresetMenus();
});
$('deptPresets').addEventListener('click', event => {
  // 세트를 누르면 **아래 메뉴 토글만 채운다** — 바로 저장하지 않는다(2026-08-18
  // 사용자 지적: "무엇이 바뀌는지 보고 적용해야 한다"). 채운 뒤 담당자가 '부서에
  // 저장'을 눌러야 이 부서 전원에게 반영된다. '전체 허용/해제' 버튼과 같은 흐름이다.
  // (2026-08-16 엔 확인창 한 번으로 즉시 적용이었는데, 검토 없이 부서 전원이
  //  바뀌는 게 불안하다는 판단으로 두 단계로 되돌렸다.)
  const button = event.target.closest('[data-preset]');
  if (!button || !deptDraft) return;
  const role = roleCatalog.find(r => String(r.role_id) === button.dataset.preset);
  if (!role) return;
  const available = new Set(deptAvailableKeys());
  const keys = (role.menu_keys || []).filter(k => available.has(k));
  deptDraft.menus = new Set(keys);
  deptDraft.viewAll = flagToChar(role.view_all_offices);
  deptDraft.viewOther = flagToChar(role.view_other_users);
  $('deptPresetMenu').open = false;
  renderDepartmentPanel();
  // renderDepartmentPanel 이 paintPresetMenu 에서 표시를 지우므로 그 **뒤**에 채운다.
  $('deptPresetPick').textContent = role.name;
  const msg = $('deptMsg');
  msg.className = 'msg';
  msg.textContent = "'" + role.name + "' 일괄권한으로 채웠습니다 — 바뀐 메뉴를 확인하고 '부서에 저장'을 누르세요.";
});
$('personPresets').addEventListener('click', event => {
  // 세트를 누르면 아래 메뉴 토글만 채운다 — 바로 저장하지 않는다(2026-08-18).
  // 담당자가 무엇이 바뀌는지 보고 '변경사항 저장'을 눌러야 반영된다. 저장 시
  // 값만 복사되므로(세트를 나중에 고쳐도 이 사람은 안 따라온다) 지금 채운 게
  // 곧 이 사람의 개인 예외가 된다.
  const button = event.target.closest('[data-preset]');
  if (!button || !selectedEmployee) return;
  const role = roleCatalog.find(r => String(r.role_id) === button.dataset.preset);
  if (!role) return;
  const availableKeys = availableMenuKeys();
  const keys = (role.menu_keys || []).filter(k => availableKeys.has(k));
  $('personPresetMenu').open = false;
  saveMenuOverride(new Set(keys));
  renderSelectedEmployee();
  // renderSelectedEmployee 뒤에 채운다(paintPresetMenu 가 표시를 지우므로).
  $('personPresetPick').textContent = role.name;
  showToast("'" + role.name + "' 일괄권한으로 채웠습니다 — 바뀐 메뉴를 확인하고 \"변경사항 저장\"을 눌러야 적용됩니다.");
});
$('deptAllowAll').addEventListener('click', deptAllowAll);
$('deptDenyAll').addEventListener('click', deptDenyAll);
// 부서 조회 범위 토글(2026-08-18) — 켜짐=Y, 꺼짐=N. 저장(부서에 저장)해야 반영된다.
$('deptViewAllToggle').addEventListener('change', event => {
  if (!deptDraft) return;
  deptDraft.viewAll = event.target.checked ? 'Y' : 'N';
  renderDepartmentPanel();
});
$('deptViewOtherToggle').addEventListener('change', event => {
  if (!deptDraft) return;
  deptDraft.viewOther = event.target.checked ? 'Y' : 'N';
  renderDepartmentPanel();
});
async function loadOrganization() {
  // 메인으로 돌아갈 때 현재 로그인 컨텍스트(usr)를 유지한다.
  const backLink = $('backToMain');
  if (backLink && window.A10_USR) {
    backLink.href = `/desktop?usr=${encodeURIComponent(window.A10_USR)}`;
  }
  // 일괄권한 목록과 부서 지정을 먼저 받아 둔다 — 조직 트리를 그릴 때 함께 쓴다.
  // 표가 아직 없으면 서버가 빈 목록을 주므로 화면은 그냥 선택칸만 안 보인다.
  await loadRoles();
  const response = await fetch('/api/permissions/organization-preview');
  const payload = await response.json();
  if (!response.ok || !payload.success) {
    throw new Error(payload.message || '실제 조직을 불러오지 못했습니다.');
  }
  offices = payload.data.offices;
  const headOffice = offices.find(office => office.id === '10') || offices[0];
  if (!headOffice || !headOffice.departments.length) {
    throw new Error('표시할 MOA 대상 사용자가 없습니다.');
  }

  const canChooseAllOffices = offices.some(office => office.id === '10');
  $('officeFilter').innerHTML = [
    ...(canChooseAllOffices ? ['<option value="all">전체 본·지사</option>'] : []),
    ...offices.map(office =>
      `<option value="${escapeHtml(office.id)}">${escapeHtml(office.name)} (${office.employee_count}명)</option>`
    ),
  ].join('');
  $('officeFilter').value = headOffice.id;

  const firstDepartment = headOffice.departments[0];
  const firstEmployee = firstDepartment.employees[0];
  selectedEmployee = {...firstEmployee, office: headOffice, department: firstDepartment};
  expanded = new Set([
    `office-${headOffice.id}`,
    `dept-${headOffice.id}-${firstDepartment.name}`,
  ]);
  renderTree();
  renderSelectedEmployee();
  loadServerPolicy();
}

window.A10_READY.then(loadOrganization).catch(error => {
  $('employeeCount').textContent = '실제 조직을 불러오지 못했습니다';
  $('organizationTree').innerHTML = `<div class="tree-empty">${escapeHtml(error.message)}</div>`;
  document.querySelector('.permission-detail').classList.add('hidden');
  // 지사 필터가 '불러오는 중…' 에 멈춰 있지 않게 실패 상태로 바꾼다(2026-08-19 감사).
  const officeFilter = $('officeFilter');
  if (officeFilter) { officeFilter.innerHTML = '<option>불러오지 못했습니다</option>'; officeFilter.disabled = true; }
});

// ── 전표 캐시 수동 동기화 (옛 권한부여 화면 permissions.html에서 이식) ──────────
// 최근 일수 또는 지정 기간의 전표를 다시 받아온다. 31일 초과 기간은 서버가 월별로
// 나눠 처리하며, 상태를 3초마다 폴링해 진행률을 보여준다. API는 permissionManage(권한관리) 권한으로 보호.
function renderSyncStatus(state) {
  const status = $('syncStatus');
  if (!status) return;
  status.classList.toggle('error', !!state.error);
  if (state.running) {
    status.textContent = `실행 중 (${state.date_from}~${state.date_to}, ${state.days}일) — ${state.progress || '준비 중'}`;
    $('syncButton').disabled = true;
    clearTimeout(renderSyncStatus.timer);
    renderSyncStatus.timer = setTimeout(pollSyncStatus, 3000);
    return;
  }
  $('syncButton').disabled = false;
  if (state.error) { status.textContent = `실패 (${state.finished_at}) — ${state.error}`; return; }
  if (state.result) {
    const chunks = state.result.chunks_total > 1
      ? `, 기간 ${state.result.chunks_completed}/${state.result.chunks_total}` : '';
    status.textContent = `완료 (${state.finished_at}) — 전표 ${Number(state.result.fetched).toLocaleString()}건, `
      + `요약 ${Number(state.result.summary_rows).toLocaleString()}건 재집계${chunks}`;
    return;
  }
  status.textContent = '';
}

async function pollSyncStatus() {
  try {
    const response = await fetch('/api/cache-sync/status');
    const payload = await response.json();
    if (payload.success) renderSyncStatus(payload.data);
  } catch (_error) {
    renderSyncStatus.timer = setTimeout(pollSyncStatus, 3000);
  }
}

function syncLocalDateValue(value) {
  const offset = value.getTimezoneOffset() * 60000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 10);
}

function toggleSyncMode() {
  const range = $('syncMode').value === 'range';
  $('syncDaysLabel').classList.toggle('hidden', range);
  $('syncFromLabel').classList.toggle('hidden', !range);
  $('syncToLabel').classList.toggle('hidden', !range);
  if (range && !$('syncDateFrom').value) {
    const today = new Date();
    $('syncDateTo').value = syncLocalDateValue(today);
    $('syncDateFrom').value = syncLocalDateValue(new Date(today.getFullYear(), today.getMonth(), 1));
  }
}

async function startSync() {
  const mode = $('syncMode').value;
  let body;
  let description;
  if (mode === 'days') {
    const days = Number($('syncDays').value);
    if (!Number.isInteger(days) || days < 1 || days > 365) { showToast('일수는 1~365 사이 숫자로 입력하세요.'); return; }
    body = { days };
    description = `최근 ${days}일`;
  } else {
    const dateFrom = $('syncDateFrom').value;
    const dateTo = $('syncDateTo').value;
    if (!dateFrom || !dateTo) { showToast('시작일과 종료일을 입력하세요.'); return; }
    if (dateFrom > dateTo) { showToast('시작일은 종료일보다 늦을 수 없습니다.'); return; }
    const days = Math.floor((new Date(`${dateTo}T00:00:00`) - new Date(`${dateFrom}T00:00:00`)) / 86400000) + 1;
    if (days > 365) { showToast('한 번에 가져올 수 있는 기간은 최대 365일입니다.'); return; }
    body = { date_from: dateFrom, date_to: dateTo };
    description = `${dateFrom}~${dateTo}`;
  }
  if (!confirm(`${description} 전표를 다시 가져올까요?\n(기간이 길면 월별로 나눠 처리하며, 다른 전표 동기화는 잠시 건너뜁니다)`)) return;
  $('syncButton').disabled = true;
  try {
    const response = await fetch('/api/cache-sync/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!payload.success) throw new Error(payload.message || payload.detail?.[0]?.msg || '동기화를 시작하지 못했습니다.');
    showToast(payload.message || '전표 동기화를 시작했습니다.');
    renderSyncStatus(payload.data);
  } catch (error) {
    showToast(`전표 가져오기 실패: ${error.message}`);
    $('syncButton').disabled = false;
  }
}

// ── 약식 입금전표 회차 수동 실행 (2026-08-28) ─────────────────────────────
// 서버 예약 작업(A10Bridge_DepositVoucherYak)을 즉시 1회 실행한다 — 서버에
// 접속해 schtasks /run 을 치던 일을 버튼으로 옮겼다. schtasks 는 시작만 하고
// 바로 돌아오므로, 배치 로그 꼬리를 폴링해 갱신되면 결과 줄을 보여준다.
let yakTriggeredTs = 0;

function renderYakStatus(text, isError = false) {
  const status = $('yakStatus');
  status.classList.toggle('error', isError);
  status.textContent = text;
}

async function pollYakStatus(deadline) {
  try {
    const response = await fetch('/api/deposit-yak/status');
    const payload = await response.json();
    if (payload.success && payload.data.exists && payload.data.updated_ts > yakTriggeredTs) {
      const lines = payload.data.lines.filter(line => line.startsWith('입금 수집') || line.startsWith('전표 전송'));
      renderYakStatus(`완료 (${payload.data.updated_at}) — ${lines.slice(-2).join(' / ') || payload.data.lines.slice(-1)[0] || '로그를 확인하세요'}`);
      $('yakRunButton').disabled = false;
      return;
    }
  } catch (_error) { /* 폴링 실패는 다음 주기에 재시도 */ }
  if (Date.now() < deadline) { setTimeout(() => pollYakStatus(deadline), 3000); return; }
  renderYakStatus('아직 로그가 갱신되지 않았습니다 — 다시 실행하지 말고 서버 로그를 확인하세요.', true);
  $('yakRunButton').disabled = false;
}

async function runYak() {
  if (!confirm('약식(400*) 입금전표 회차를 지금 실행할까요?\n(매일 17시 예약 회차와 같은 작업입니다 — 실제 아마란스 전표가 생성됩니다)')) return;
  $('yakRunButton').disabled = true;
  renderYakStatus('실행 요청 중...');
  try {
    const response = await fetch('/api/deposit-yak/run', { method: 'POST' });
    const payload = await response.json();
    if (!payload.success) throw new Error(payload.message);
    yakTriggeredTs = payload.data.triggered_ts;
    renderYakStatus('실행 중 — 결과를 기다리는 중...');
    pollYakStatus(Date.now() + 180000);
  } catch (error) {
    renderYakStatus(error.message, true);
    showToast(`약식 입금전표 실행 실패: ${error.message}`);
    $('yakRunButton').disabled = false;
  }
}

// 본사 + 데이터 품질 권한 사용자에게만 전표 가져오기 카드를 노출한다(API도 동일 권한).
window.A10_READY.then(ctx => {
  const section = $('cacheSyncSection');
  if (!section) return;
  const canSync = String(ctx.office_id) === '10' && !!(window.A10_CAN && window.A10_CAN('permissionManage'));
  if (!canSync) return;
  section.classList.remove('hidden');
  $('syncMode').addEventListener('change', toggleSyncMode);
  $('syncButton').addEventListener('click', startSync);
  toggleSyncMode();
  pollSyncStatus();
  // 약식 실행 카드도 같은 잣대(본사 + permissionManage)로만 연다 — API도 동일 권한.
  const yakSection = $('yakRunSection');
  if (yakSection) {
    yakSection.classList.remove('hidden');
    $('yakRunButton').addEventListener('click', runYak);
  }
}).catch(() => {});


// ── 일괄권한 ──────────────────────────────────────────────────────────────

async function loadRoles() {
  try {
    const [roleRes, deptRes] = await Promise.all([
      fetch('/api/permissions/roles'),
      fetch('/api/permissions/departments'),
    ]);
    rolesLoadFailed = !roleRes.ok;
    roleCatalog = roleRes.ok ? (((await roleRes.json()).data || {}).items || []) : [];
    deptRoleMap.clear();
    if (deptRes.ok) {
      (((await deptRes.json()).data || {}).items || []).forEach(row => {
        deptRoleMap.set(`${row.office_id}|${row.department_name}`, row.role_id);
      });
    }
    await loadPersonalSettings();
  } catch (error) {
    rolesLoadFailed = true;
    roleCatalog = [];
  }
}

/** 개인 설정(일괄권한·예외)을 가진 사람들. 실패해도 화면은 살려 둔다 — 표가
 *  안 그려질 뿐이고, 이 목록이 없다고 권한이 달라지지는 않는다. */
async function loadPersonalSettings() {
  userRoleMap.clear();
  personalOverrides.clear();
  try {
    const res = await fetch('/api/permissions/roles/user-assignments');
    if (!res.ok) return;
    const data = (await res.json()).data || {};
    (data.items || []).forEach(row => {
      userRoleMap.set(Number(row.usr_seq), row.role_id);
    });
    (data.personal_overrides || []).forEach(seq => personalOverrides.add(Number(seq)));
  } catch (error) {
    /* 표시는 부가 정보다 — 못 얻으면 그냥 안 그린다 */
  }
}

/** 이 사람은 부서 권한을 따라가는가. 안 따라가면 그 이유를 문장으로 돌려준다. */
function personalSettingOf(employee) {
  const seq = Number(employee && employee.usr_seq);
  if (!seq) return null;
  const roleId = userRoleMap.get(seq);
  if (roleId != null) {
    const role = roleCatalog.find(item => item.role_id === roleId);
    return {label: '개인', why: '개인 일괄권한(' + (role ? role.name : '#' + roleId)
      + ')이 붙어 있어 부서 권한을 따라가지 않습니다.'};
  }
  if (personalOverrides.has(seq)) {
    return {label: '개인', why: '개인 예외가 걸려 있어 부서 권한 위에 얹힙니다.'};
  }
  return null;
}

// 부서 일괄권한 지정은 이제 부서 패널(applyDepartment)이 맡는다.
// 종전에는 트리 줄에 붙은 작은 셀렉트가 change 즉시 서버로 보냈는데,
// 무엇을 주는 일괄권한인지 보지도 못한 채 부서 전원이 바뀌었다 (2026-08-16 요청으로 교체).

