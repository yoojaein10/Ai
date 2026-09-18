const services = [
  { icon: "✈", title: "항공권", copy: "Skyscanner에서 최적의 항공편을 찾아보세요.", href: "https://www.skyscanner.co.kr/" },
  { icon: "▤", title: "해외 숙소", copy: "여행 동선에 어울리는 숙소를 한 번에 비교하세요.", href: "https://www.booking.com/" },
  { icon: "◇", title: "투어 · 티켓", copy: "현지의 특별한 경험을 일정에 더해보세요.", href: "https://www.klook.com/ko/" },
  { icon: "♢", title: "여행자 보험", copy: "출발 전 꼭 필요한 보장을 간편하게 준비하세요.", href: "https://gayage.vercel.app/login" },
  { icon: "◉", title: "글로벌 렌터카", copy: "도시 밖까지 자유롭게 이어지는 이동을 준비하세요.", href: "https://gayage.vercel.app/login" },
  { icon: "⌁", title: "간편 eSIM", copy: "도착하는 순간부터 바로 연결되는 여행을 시작하세요.", href: "https://gayage.vercel.app/login" },
];

const destinations = [
  { city: "도쿄", country: "일본", image: "/images/tokyo.jpg", className: "destination destination-main" },
  { city: "오사카", country: "일본", image: "/images/osaka.jpg", className: "destination" },
  { city: "홍콩", country: "중국", image: "/images/hongkong.jpg", className: "destination" },
  { city: "파리", country: "프랑스", image: "/images/paris.jpg", className: "destination" },
  { city: "타이베이", country: "대만", image: "/images/taipei.jpg", className: "destination" },
];

export default function Home() {
  return (
    <main>
      <header className="site-header">
        <a className="brand" href="#top" aria-label="가야지 홈">가야지</a>
        <nav className="desktop-nav" aria-label="주요 메뉴">
          <a href="#features">여행 일정</a>
          <a href="#destinations">여행지</a>
          <a href="#services">파트너</a>
        </nav>
        <div className="header-actions">
          <a className="login-link" href="https://gayage.vercel.app/login">로그인</a>
          <a className="button button-small" href="https://gayage.vercel.app/login">시작하기</a>
        </div>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow">THE ART OF TRAVEL</p>
          <h1>일정도, 예약도<br />한 곳에서.</h1>
          <p className="hero-description">
            목적지와 날짜만 정하면 AI가 하루하루 일정을 짜고,
            동선·예산·짐·예약까지 한 흐름으로 이어드립니다.
          </p>
          <div className="hero-actions">
            <a className="button" href="https://gayage.vercel.app/login">
              무료로 시작하기 <span aria-hidden="true">→</span>
            </a>
            <a className="button button-outline" href="#destinations">인기 여행지 보기</a>
          </div>
          <div className="trust-row" aria-label="서비스 특징">
            <span>가입 없이 둘러보기</span><i />
            <span>iCloud 자동 동기화</span><i />
            <span>여행 전 과정을 한 번에</span>
          </div>
        </div>

        <div className="hero-visual" aria-label="여행 기록을 작성하는 장면">
          <div className="hero-image-wrap">
            <img src="/images/hero-travel-journal.png" alt="여행 노트와 폴라로이드 사진을 펼쳐두고 일정을 기록하는 모습" />
          </div>
          <div className="ai-note">
            <span className="note-mark" aria-hidden="true">✣</span>
            <div>
              <strong>AI가 만든 오늘의 여정</strong>
              <p>경주 황리단길에서 시작해 동궁과 월지의 야경으로 마무리해요.</p>
            </div>
          </div>
          <div className="string-art" aria-hidden="true"><span /><span /><span /></div>
        </div>
      </section>

      <section className="features section" id="features">
        <div className="section-heading ornament-heading">
          <span /><h2>스마트한 여행의 시작</h2><span />
        </div>
        <div className="feature-grid">
          <article>
            <div className="feature-icon" aria-hidden="true">ϟ</div>
            <p className="feature-index">01 / PLAN</p>
            <h3>3초 만의 일정 생성</h3>
            <p>목적지, 기간, 인원만 입력하세요. 취향과 이동 시간을 고려한 하루가 완성됩니다.</p>
          </article>
          <article>
            <div className="feature-icon" aria-hidden="true">≡</div>
            <p className="feature-index">02 / EDIT</p>
            <h3>정교한 맞춤 편집</h3>
            <p>마음에 들지 않는 장소는 바꾸고, 시간과 순서는 내 여행 방식대로 다듬으세요.</p>
          </article>
          <article>
            <div className="feature-icon" aria-hidden="true">✧</div>
            <p className="feature-index">03 / BOOK</p>
            <h3>원스톱 예약 연결</h3>
            <p>항공, 숙소, 투어까지 일정의 흐름을 놓치지 않고 바로 예약할 수 있습니다.</p>
          </article>
        </div>
      </section>

      <section className="destinations section" id="destinations">
        <div className="section-label-row">
          <div>
            <p className="eyebrow">CURATED COLLECTIONS</p>
            <h2>요즘 많이 가는 곳</h2>
          </div>
          <a href="https://gayage.vercel.app/login">모든 여행지 보기 <span aria-hidden="true">↗</span></a>
        </div>
        <div className="destination-grid">
          {destinations.map((destination) => (
            <article className={destination.className} key={destination.city}>
              <img src={destination.image} alt={`${destination.city}의 여행 풍경`} />
              <div className="destination-shade" />
              <div className="destination-copy">
                <h3>{destination.city}</h3>
                <p>{destination.country}</p>
              </div>
              <span className="destination-arrow" aria-hidden="true">↗</span>
            </article>
          ))}
        </div>
        <div className="mini-destinations" aria-label="추천 여행지">
          <div><img src="/images/fukuoka.jpg" alt="후쿠오카" /><span><strong>후쿠오카</strong>미식이 있는 도시</span></div>
          <div><img src="/images/danang.jpg" alt="다낭" /><span><strong>다낭</strong>휴식과 미식 사이</span></div>
          <div><img src="/images/guam.jpg" alt="괌" /><span><strong>괌</strong>가장 가까운 휴양</span></div>
        </div>
      </section>

      <section className="planner section" aria-labelledby="planner-title">
        <div className="planner-copy">
          <p className="eyebrow">YOUR JOURNEY, IN RHYTHM</p>
          <h2 id="planner-title">흐름이 보이는<br />하루의 여정.</h2>
          <p>지도에서 동선을 확인하고, 시간대별 일정을 한눈에 살펴보세요. 여행 경비와 준비물도 같은 화면에서 이어집니다.</p>
          <a className="text-link" href="https://gayage.vercel.app/login">AI 일정 만들어보기 <span aria-hidden="true">→</span></a>
        </div>
        <div className="itinerary-card">
          <div className="itinerary-top">
            <div><p>추천 일정</p><h3>경주, 천년의 시간</h3></div>
            <span>2박 3일</span>
          </div>
          <ol>
            <li><time>10:00</time><div><strong>대릉원 산책</strong><span>고요한 능선을 따라 여행의 첫 장을 엽니다.</span></div></li>
            <li><time>12:30</time><div><strong>황리단길 점심</strong><span>오래된 골목에서 경주의 새로운 맛을 만납니다.</span></div></li>
            <li><time>16:00</time><div><strong>국립경주박물관</strong><span>신라의 시간을 천천히 들여다봅니다.</span></div></li>
            <li><time>19:20</time><div><strong>동궁과 월지</strong><span>물 위에 번지는 야경으로 하루를 마무리합니다.</span></div></li>
          </ol>
        </div>
      </section>

      <section className="services section" id="services">
        <div className="section-label-row">
          <div>
            <p className="eyebrow">TRAVEL ESSENTIALS</p>
            <h2>여행에 필요한 모든 것</h2>
          </div>
          <p className="section-intro">계획에서 출발까지, 필요한 서비스를<br />가야지 안에서 자연스럽게 이어보세요.</p>
        </div>
        <div className="service-grid">
          {services.map((service) => (
            <a href={service.href} className="service-card" key={service.title} target="_blank" rel="noreferrer">
              <span className="service-icon" aria-hidden="true">{service.icon}</span>
              <h3>{service.title}</h3>
              <p>{service.copy}</p>
              <span className="service-link">살펴보기 ↗</span>
            </a>
          ))}
        </div>
      </section>

      <section className="final-cta" id="start">
        <p className="eyebrow">BEGIN YOUR JOURNEY</p>
        <h2>당신만의 여정을 시작하세요.</h2>
        <p>여행 계획이 하나의 선율처럼 매끄러워지는 새로운 경험.</p>
        <div>
          <a className="button button-gold" href="https://gayage.vercel.app/login">지금 일정 만들기</a>
          <a className="button button-dark-outline" href="#services">서비스 둘러보기</a>
        </div>
      </section>

      <footer>
        <div><a className="brand brand-footer" href="#top">가야지</a><p>© 2026 Gayage. 여행에 조화를 담습니다.</p></div>
        <nav aria-label="하단 메뉴"><a href="#features">여행 일정</a><a href="#destinations">여행지</a><a href="#services">파트너</a><a href="https://gayage.vercel.app/login">고객 지원</a></nav>
      </footer>
    </main>
  );
}
