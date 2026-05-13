'use strict';
const APP_CONFIG={GOOGLE_CLIENT_ID:'650414957833-s37phqum36bfomv5sr5n2cm4tau55ng5.apps.googleusercontent.com',SCRIPT_URL_KEY:'budget_script_url',TOKEN_KEY:'budget_google_token',USER_KEY:'budget_user',THEME_KEY:'budget_theme',FONT_KEY:'budget_font',AVATAR_KEY:'budget_avatar',USERNAME_KEY:'budget_username',FAMILY_KEY:'budget_family',GOALS_KEY:'budget_goals',EXP_CATS_KEY:'budget_exp_cats',INC_CATS_KEY:'budget_inc_cats',CARDS_KEY:'budget_cards',MONO_EVGEN_KEY:'budget_mono_evgen',MONO_MARINA_KEY:'budget_mono_marina',PROFILES_KEY:'budget_profiles',LAST_SYNC_KEY:'budget_last_sync',TRANSFERS_KEY:'budget_transfers',SECRET_KEY:'budget2026koval',SCRIPT_URL:'https://script.google.com/macros/s/AKfycbwlZdxmHbaCVEJ5XmvA3oLEOHgGAPHzoGgXmB4OKgSmbhbH1whzid4YHNKvLMQiaczbbA/exec'};
const ICON_LIST=['ti-shopping-cart','ti-car','ti-home','ti-tools-kitchen-2','ti-heart','ti-shirt','ti-device-gamepad-2','ti-sofa','ti-baby-carriage','ti-dots','ti-briefcase','ti-coin','ti-plane','ti-book','ti-coffee','ti-paw','ti-phone','ti-gift','ti-bike','ti-pill','ti-school','ti-sport-billard','ti-music','ti-bus','ti-credit-card','ti-cash','ti-building-bank','ti-star','ti-pizza','ti-salad','ti-droplet','ti-bolt','ti-wifi','ti-device-laptop','ti-tools','ti-shirt-sport','ti-garden-cart','ti-vaccine','ti-receipt'];
const state={user:null,token:null,scriptUrl:'',currentPage:'dashboard',currentMonth:new Date(),calMonth:new Date(),calPeriod:'month',currentType:'Витрата',currentCurrency:'UAH',reserveType:'Поповнення',reserveCurrency:'UAH',selectedCat:'',selectedCard:'',modalMember:null,dashboard:null,reserve:null,operations:[],goals:[],transfers:[],fx:null,filterActive:'all',editingGoalIdx:-1,activeAccountId:null,editingOp:null};
const CURRENCIES=['UAH','USD','EUR'],CUR_SYMBOLS={UAH:'₴',USD:'$',EUR:'€'};
const MONTH_UK=['Січень','Лютий','Березень','Квітень','Травень','Червень','Липень','Серпень','Вересень','Жовтень','Листопад','Грудень'];
const DEFAULT_EXP_CATS=[{id:'Продукти',icon:'ti-shopping-cart',bg:'#E1F5EE',color:'#085041'},{id:'Транспорт',icon:'ti-car',bg:'#FAECE7',color:'#712B13'},{id:'Комунальні',icon:'ti-home',bg:'#E6F1FB',color:'#0C447C'},{id:'Ресторани',icon:'ti-tools-kitchen-2',bg:'#FEF3E2',color:'#633806'},{id:"Здоров'я",icon:'ti-heart',bg:'#FBEAF0',color:'#72243E'},{id:'Одяг',icon:'ti-shirt',bg:'#EEEDFE',color:'#3C3489'},{id:'Розваги',icon:'ti-device-gamepad-2',bg:'#F0F4FF',color:'#2D4AB7'},{id:'Дім',icon:'ti-sofa',bg:'#E6F1FB',color:'#0C447C'},{id:'Дитячі',icon:'ti-baby-carriage',bg:'#FBEAF0',color:'#72243E'},{id:'Інше',icon:'ti-dots',bg:'#F0F0F0',color:'#555'}];
const DEFAULT_INC_CATS=[{id:'Зарплата',icon:'ti-briefcase',bg:'#EAF3DE',color:'#27500A'},{id:'Підробіток',icon:'ti-coin',bg:'#FEF3E2',color:'#633806'},{id:'Інше',icon:'ti-dots',bg:'#F0F0F0',color:'#555'}];
const DEFAULT_CARDS=[{id:'Готівка',icon:'ti-cash',bg:'#EAF3DE',color:'#27500A'},{id:'Моно чорна',icon:'ti-credit-card',bg:'#1a1a2e',color:'#fff'},{id:'ПУМБ',icon:'ti-credit-card',bg:'#E6F1FB',color:'#0C447C'},{id:'Приват',icon:'ti-credit-card',bg:'#FBEAF0',color:'#72243E'},{id:'Кредитна',icon:'ti-credit-card',bg:'#FAEEDA',color:'#633806'}];
// Два члени сім'ї — константа для дашборду і операцій
const FAMILY_MEMBERS=['Євген','Марина'];
// Кольори членів
const MEMBER_COLORS={Євген:{bg:'var(--c-blue-soft)',cl:'var(--c-blue)',initials:'ЄК'},Марина:{bg:'var(--c-pink-soft)',cl:'var(--c-pink)',initials:'МК'}};
// ── HELPERS ──────────────────────────────────────────────────────
function getExpCats(){try{const s=localStorage.getItem(APP_CONFIG.EXP_CATS_KEY);return s?JSON.parse(s):DEFAULT_EXP_CATS;}catch{return DEFAULT_EXP_CATS;}}
function getIncCats(){try{const s=localStorage.getItem(APP_CONFIG.INC_CATS_KEY);return s?JSON.parse(s):DEFAULT_INC_CATS;}catch{return DEFAULT_INC_CATS;}}
// Картки по члену: getCards('Євген') або getCards() → спільні
function getCards(member){
  const key=member?APP_CONFIG.CARDS_KEY+'_'+member:APP_CONFIG.CARDS_KEY;
  try{const s=localStorage.getItem(key);return s?JSON.parse(s):DEFAULT_CARDS;}catch{return DEFAULT_CARDS;}
}
function saveCards(c,member){
  const key=member?APP_CONFIG.CARDS_KEY+'_'+member:APP_CONFIG.CARDS_KEY;
  localStorage.setItem(key,JSON.stringify(c));
  syncSettingsToSheet();
}
// Профілі юзерів (ім'я, аватар, картки) — зберігаємо/читаємо з Sheet
function getProfiles(){try{const s=localStorage.getItem(APP_CONFIG.PROFILES_KEY);return s?JSON.parse(s):{Євген:{name:'Євген',avatar:null,cards:DEFAULT_CARDS},Марина:{name:'Марина',avatar:null,cards:DEFAULT_CARDS}};}catch{return {};}}
function saveProfiles(p){localStorage.setItem(APP_CONFIG.PROFILES_KEY,JSON.stringify(p));syncSettingsToSheet();}
// Отримати профіль поточного юзера за email
function getMyMember(){
  const email=(state.user?.email||'').toLowerCase();
  if(email.includes('yevhen')||email.includes('evgen')||email.includes('євген'))return'Євген';
  if(email.includes('marina')||email.includes('марина'))return'Марина';
  // Fallback — по імені
  const name=localStorage.getItem(APP_CONFIG.USERNAME_KEY)||state.user?.name||'';
  if(name.toLowerCase().includes('марина')||name.toLowerCase().includes('marina'))return'Марина';
  return'Євген';
}

// ── ACCOUNTS BALANCE ─────────────────────────────────────────────
// Рахує баланс кожного рахунку (опційно фільтр по члену)
function getAccountBalances(member){
  const cards=member?getCards(member):getCards();
  const balances={};
  cards.forEach(c=>{ balances[c.id]=0; });
  state.operations.forEach(op=>{
    const card=op.card||'';
    if(!card)return;
    if(member&&op.who!==member)return; // фільтр по члену
    if(!(card in balances))balances[card]=0;
    if(op.type==='Дохід') balances[card]+=(op.amountUah||op.amount||0);
    else if(op.type==='Витрата') balances[card]-=(op.amountUah||op.amount||0);
  });
  return balances;
}
// Баланс конкретного члена (сума всіх його карток)
function getMemberBalance(member){
  const b=getAccountBalances(member);
  return Object.values(b).reduce((s,v)=>s+v,0);
}
function getTotalBalance(){
  return FAMILY_MEMBERS.reduce((s,m)=>s+getMemberBalance(m),0);
}
function getCat(id){return [...getExpCats(),...getIncCats()].find(c=>c.id===id)||{id,icon:'ti-dots',bg:'#F0F0F0',color:'#555'};}
function getGoals(){try{const s=localStorage.getItem(APP_CONFIG.GOALS_KEY);return s?JSON.parse(s):[];}catch{return[];}}
function saveGoals(g){
  localStorage.setItem(APP_CONFIG.GOALS_KEY,JSON.stringify(g));
  state.goals=g;
  // Синкуємо в Sheet
  if(state.scriptUrl)apiPost({action:'updateGoals',goals:g}).catch(e=>console.warn('Goals sync:',e));
}
function fmtMoney(n,cur){if(n===undefined||n===null||isNaN(n))return'—';const sym=CUR_SYMBOLS[cur]||cur;const fmt=Math.abs(Math.round(n)).toLocaleString('uk-UA');return cur==='UAH'?fmt+' '+sym:sym+fmt;}
function fmtDate(s){if(!s)return'';const d=new Date(s);if(isNaN(d))return s;const t=new Date();const y=new Date(t);y.setDate(t.getDate()-1);if(d.toDateString()===t.toDateString())return'сьогодні '+d.toLocaleTimeString('uk-UA',{hour:'2-digit',minute:'2-digit'});if(d.toDateString()===y.toDateString())return'вчора '+d.toLocaleTimeString('uk-UA',{hour:'2-digit',minute:'2-digit'});return d.getDate()+' '+MONTH_UK[d.getMonth()].toLowerCase().slice(0,3)+' '+d.toLocaleTimeString('uk-UA',{hour:'2-digit',minute:'2-digit'});}
function fmtMonth(d){return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0');}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function setText(id,v){const el=document.getElementById(id);if(el)el.textContent=v??'—';}
function showToast(msg,type='success'){const t=document.createElement('div');t.style.cssText='position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:'+(type==='error'?'var(--c-red)':'var(--c-green)')+';color:#fff;padding:10px 20px;border-radius:10px;font-size:13px;font-weight:600;z-index:1000;box-shadow:0 4px 16px rgba(0,0,0,.2);animation:fadeInUp .2s ease;white-space:nowrap;';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),2500);}

// ── INIT ──────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded',()=>{loadSettings();initGoogleAuth();bindEvents();});

function loadSettings(){
  const theme=localStorage.getItem(APP_CONFIG.THEME_KEY)||'light';
  state.scriptUrl=APP_CONFIG.SCRIPT_URL||localStorage.getItem(APP_CONFIG.SCRIPT_URL_KEY)||'';
  applyTheme(theme);
  // Load family name
  const fam=localStorage.getItem(APP_CONFIG.FAMILY_KEY)||'Родина Коваль';
  const fi=document.getElementById('family-name-input');
  if(fi)fi.value=fam;
  setText('sb-family-name',fam);
  // Load avatar
  const av=localStorage.getItem(APP_CONFIG.AVATAR_KEY);
  if(av)applyAvatar(av);
  // Load username
  const un=localStorage.getItem(APP_CONFIG.USERNAME_KEY);
  if(un){const ni=document.getElementById('settings-name-input');if(ni)ni.value=un;}
  // Load mono tokens
  const me=localStorage.getItem(APP_CONFIG.MONO_EVGEN_KEY);
  const mm=localStorage.getItem(APP_CONFIG.MONO_MARINA_KEY);
  if(me){const el=document.getElementById('mono-token-evgen');if(el)el.value=me;}
  if(mm){const el=document.getElementById('mono-token-marina');if(el)el.value=mm;}
}

// ── AUTH ──────────────────────────────────────────────────────────
function initGoogleAuth(){
  if(location.hash.includes('access_token')){handleOAuthRedirect();return;}
  const u=localStorage.getItem(APP_CONFIG.USER_KEY);
  const t=localStorage.getItem(APP_CONFIG.TOKEN_KEY);
  if(u&&t){state.user=JSON.parse(u);state.token=t;showApp();return;}
  showAuthScreen();
}
document.getElementById('google-signin-btn').addEventListener('click',()=>{
  const params=new URLSearchParams({client_id:APP_CONFIG.GOOGLE_CLIENT_ID,redirect_uri:location.origin+location.pathname,response_type:'token',scope:'email profile openid',prompt:'select_account'});
  location.href='https://accounts.google.com/o/oauth2/v2/auth?'+params.toString();
});
function handleOAuthRedirect(){
  const hash=location.hash.substring(1);
  const params=new URLSearchParams(hash);
  const token=params.get('access_token');
  if(!token){showAuthScreen();return;}
  history.replaceState(null,'',location.pathname);
  fetch('https://www.googleapis.com/oauth2/v2/userinfo',{headers:{Authorization:'Bearer '+token}})
  .then(r=>r.json()).then(info=>{
    state.user={name:info.given_name||info.name,email:info.email};
    state.token=token;
    localStorage.setItem(APP_CONFIG.USER_KEY,JSON.stringify(state.user));
    localStorage.setItem(APP_CONFIG.TOKEN_KEY,token);
    showApp();
  }).catch(()=>showAuthScreen());
}
function logout(){
  localStorage.removeItem(APP_CONFIG.USER_KEY);localStorage.removeItem(APP_CONFIG.TOKEN_KEY);
  state.user=null;state.token=null;
  document.getElementById('app').classList.add('hidden');
  document.getElementById('auth-screen').classList.remove('hidden');
}
function showAuthScreen(){hideSplash();document.getElementById('auth-screen').classList.remove('hidden');}
function showApp(){
  hideSplash();
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  updateUserUI();navigateTo('dashboard');loadFx();
  loadSyncQueue(); // відновлюємо чергу з sessionStorage
  setTimeout(async()=>{
    // 1. Налаштовуємо листи таблиці (додає колонку M якщо нема)
    if(state.scriptUrl)apiPost({action:'setup'}).catch(()=>{});
    // 2. Повний синк: Sheet → App
    await fullSync(false);
    showSyncStatus('ok');
    // 3. Запускаємо авто-синк
    initSync();
  },600);
}
function hideSplash(){document.getElementById('splash').classList.add('hidden');}

// ── USER UI ───────────────────────────────────────────────────────
function updateUserUI(){
  const u=state.user;if(!u)return;
  const savedName=localStorage.getItem(APP_CONFIG.USERNAME_KEY)||u.name;
  const ini=getInitials(savedName);
  setText('sb-avatar',ini);setText('sb-user-name',savedName);setText('topbar-av-text',ini);
  setText('settings-email',u.email);
  const ni=document.getElementById('settings-name-input');if(ni)ni.value=savedName;
  setText('greeting-text',getGreeting(savedName));
  const fam=localStorage.getItem(APP_CONFIG.FAMILY_KEY)||'Родина Коваль';
  setText('sb-family-name',fam);
  const fi=document.getElementById('family-name-input');if(fi)fi.value=fam;
  const pap=document.getElementById('profile-av-placeholder');if(pap)pap.textContent=ini;
}
function getInitials(n){return(n||'').split(' ').map(w=>w[0]).join('').toUpperCase().substring(0,2)||'?';}
function getGreeting(n){const h=new Date().getHours();const g=h<12?'Доброго ранку':h<18?'Привіт':'Добрий вечір';return g+', '+n+' 👋';}
function applyAvatar(dataUrl){
  const ids=['sb-avatar-img','topbar-av-img','profile-av-img'];
  const hideIds=['sb-avatar','topbar-av-text','profile-av-placeholder'];
  ids.forEach(id=>{const el=document.getElementById(id);if(el){el.src=dataUrl;el.style.display='block';}});
  hideIds.forEach(id=>{const el=document.getElementById(id);if(el)el.style.display='none';});
}

// ── NAVIGATION ────────────────────────────────────────────────────
function navigateTo(page){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.sb-item,.bn-item').forEach(i=>i.classList.remove('active'));
  const el=document.getElementById('page-'+page);
  if(el)el.classList.add('active');
  document.querySelectorAll('[data-page="'+page+'"]').forEach(e=>e.classList.add('active'));
  state.currentPage=page;
  const titles={dashboard:'Дашборд',operations:'Операції',calendar:'Календар',analytics:'Аналіз',reserve:'Накопичення',settings:'Налаштування'};
  setText('topbar-title',titles[page]||page);
  loadPageData(page);closeSidebar();
}
function loadPageData(page){
  // Показуємо локальні дані відразу (без затримки)
  if(page==='dashboard'){if(state.dashboard)renderDashboard(state.dashboard);renderMemberColumns();}
  else if(page==='operations')renderOperations();
  else if(page==='calendar')renderCalendar();
  else if(page==='analytics'){if(state.dashboard)renderAnalytics();}
  else if(page==='reserve'){if(state.reserve)renderReserve(state.reserve);}
  else if(page==='goals'){
    // Спочатку показуємо локальні
    const localGoals=getGoals();
    if(localGoals.length)renderGoals(localGoals);
    // Потім тягнемо з Sheet
    if(state.scriptUrl)fetchGoals();
    else renderDemoData('goals');
  }
  else if(page==='settings')renderSettingsUI();
  // Тягнемо з сервера
  if(!state.scriptUrl){renderDemoData(page);return;}
  if(page==='dashboard')fetchDashboard().then(()=>fetchOperations());
  else if(page==='operations')fetchOperations();
  else if(page==='analytics')fetchDashboard().then(()=>renderAnalytics());
  else if(page==='reserve')fetchReserve();
}

// ── API ───────────────────────────────────────────────────────────
async function apiGet(action,params={}){
  if(!state.scriptUrl)return null;
  const url=new URL(state.scriptUrl);
  url.searchParams.set('action',action);url.searchParams.set('key',APP_CONFIG.SECRET_KEY);url.searchParams.set('token',state.token||'');
  Object.entries(params).forEach(([k,v])=>url.searchParams.set(k,v));
  const r=await fetch(url.toString());if(!r.ok)throw new Error('API '+r.status);return r.json();
}
async function apiPost(body){
  if(!state.scriptUrl)return null;
  // Apps Script не приймає справжній POST через CORS.
  // Використовуємо GET з payload= параметром — doGet його розпізнає і роутить як POST
  const url=new URL(state.scriptUrl);
  url.searchParams.set('key',APP_CONFIG.SECRET_KEY);
  url.searchParams.set('payload',JSON.stringify(body));
  const r=await fetch(url.toString());
  if(!r.ok)throw new Error('API '+r.status);
  const text=await r.text();
  try{return JSON.parse(text);}catch{return null;}
}
async function fetchDashboard(){try{const d=await apiGet('dashboard');if(d&&!d.error){state.dashboard=d;renderDashboard(d);renderMemberColumns();}}catch(e){console.warn('fetchDashboard:',e);}}
async function fetchTransfers(){try{const d=await apiGet('transfers');if(d){state.transfers=d.transfers||[];}}catch(e){console.warn('fetchTransfers:',e);}}
async function fetchOperations(){try{const d=await apiGet('operations',{month:fmtMonth(state.currentMonth)});if(d&&d.operations){state.operations=d.operations;renderOperations();renderCalendar();renderMemberColumns();}}catch(e){console.warn('fetchOperations:',e);}}
async function fetchReserve(){try{const d=await apiGet('reserve');if(d&&!d.error){state.reserve=d;renderReserve(d);}}catch(e){console.warn('fetchReserve:',e);}}
async function fetchGoals(){
  try{
    const d=await apiGet('goals');
    if(d&&d.goals&&d.goals.length){
      // Зберігаємо в localStorage і показуємо
      localStorage.setItem(APP_CONFIG.GOALS_KEY,JSON.stringify(d.goals));
      state.goals=d.goals;
      renderGoals(d.goals);
    }
  }catch(e){console.warn('fetchGoals:',e);}
}
async function loadFx(){try{const d=state.scriptUrl?await apiGet('fx'):null;if(d){state.fx=d;setText('fx-usd',d.USD?.mid?.toFixed(2)+' ₴');setText('fx-eur',d.EUR?.mid?.toFixed(2)+' ₴');}}catch(e){}}

// ── RENDER DASHBOARD ─────────────────────────────────────────────
function renderDashboard(d){
  setText('dash-income',fmtMoney(d.totalIncome,'UAH'));
  setText('dash-expense',fmtMoney(d.totalExpense,'UAH'));
  setText('dash-balance',fmtMoney(d.balance,'UAH'));
  setText('dash-savings-rate','Накопичення '+(d.savingsRate||0).toFixed(0)+'%');
  renderMemberColumns();
  renderRecentOps(d.recent||[]);
  renderCatBars("cat-bars",d.byCategory||{},d.totalExpense);
  renderDailyChart(d.byDay||{});
  updateMonthLabel();
}
function renderMemberColumns(){
  const el=document.getElementById('members-columns');if(!el)return;
  const profiles=getProfiles();
  const byMember=state.dashboard?.byMember||{};

  // Групи карток за назвою
  const CARD_GROUPS=[
    {id:'credit',  label:'Кредитні',    icon:'ti-credit-card',   match:['кредит']},
    {id:'cash',    label:'Готівка',      icon:'ti-cash',          match:['готівка','налич']},
    {id:'savings', label:'Накопичення',  icon:'ti-piggy-bank',    match:['накопич','ощад','депозит','savings']},
    {id:'cards',   label:'Картки',       icon:'ti-cards',         match:[]}, // решта
  ];
  function getGroupId(cardId){
    const low=(cardId||'').toLowerCase();
    for(const g of CARD_GROUPS){
      if(g.id==='cards')continue;
      if(g.match.some(m=>low.includes(m)))return g.id;
    }
    return 'cards';
  }

  el.innerHTML=FAMILY_MEMBERS.map(member=>{
    const mc=MEMBER_COLORS[member]||{bg:'var(--c-bg-3)',cl:'var(--c-text)',initials:'??'};
    const prof=profiles[member]||{name:member,avatar:null};
    const cards=getCards(member);
    const memberData=byMember[member]||{income:0,expense:0,byCard:{}};
    // Загальний баланс — локальний якщо є операції, інакше з сервера
    const displayBal=state.operations.length
      ?state.operations.filter(o=>o.who===member).reduce((s,o)=>{
          if(o.type==='Дохід')return s+(o.amountUah||o.amount);
          if(o.type==='Витрата')return s-(o.amountUah||o.amount);
          return s;},0)
      :memberData.income-memberData.expense;

    const avatarHtml=prof.avatar
      ?`<img src="${prof.avatar}" class="member-col-av-img">`
      :`<div class="member-col-av" style="background:${mc.bg};color:${mc.cl}">${mc.initials}</div>`;

    // Групуємо картки
    const grouped={};
    cards.forEach(c=>{
      const g=getGroupId(c.id);
      if(!grouped[g])grouped[g]=[];
      grouped[g].push(c);
    });

    // Баланс картки
    const cardBal=c=>{
      const local=state.operations.filter(o=>o.who===member&&o.card===c.id)
        .reduce((s,o)=>{if(o.type==='Дохід')return s+(o.amountUah||o.amount);if(o.type==='Витрата')return s-(o.amountUah||o.amount);return s;},0);
      const srv=(memberData.byCard?.[c.id]?.income||0)-(memberData.byCard?.[c.id]?.expense||0);
      return state.operations.length?local:srv;
    };

    let cardsHtml='';
    for(const grp of CARD_GROUPS){
      if(!grouped[grp.id]||!grouped[grp.id].length)continue;
      cardsHtml+=`<div class="member-cards-group-label"><i class="ti ${grp.icon}"></i>${grp.label}</div>`;
      cardsHtml+=grouped[grp.id].map(c=>{
        const bal=cardBal(c);
        return `<div class="wallet-card" data-member="${esc(member)}" data-account="${esc(c.id)}">
          <div class="wallet-card-icon" style="background:${c.bg}"><i class="ti ${c.icon}" style="color:${c.color}"></i></div>
          <div class="wallet-card-name">${esc(c.id)}</div>
          <div class="wallet-card-bal ${bal>=0?'pos':'neg'}">${fmtMoney(Math.abs(bal),'UAH')}</div>
        </div>`;
      }).join('');
    }

    return `<div class="member-col" data-member="${esc(member)}">
      <div class="member-col-head" data-member="${esc(member)}">
        <div class="member-col-av-wrap">${avatarHtml}</div>
        <div class="member-col-name">${esc(prof.name||member)}</div>
        <div class="member-col-total ${displayBal>=0?'pos':'neg'}">${fmtMoney(Math.abs(displayBal),'UAH')}</div>
        <i class="ti ti-chevron-down member-col-chevron"></i>
      </div>
      <div class="member-cards-wrap">${cardsHtml}</div>
    </div>`;
  }).join('');

  // Collapsible — клік по заголовку
  el.querySelectorAll('.member-col-head').forEach(hd=>{
    hd.addEventListener('click',()=>{
      const wrap=hd.nextElementSibling;
      const chev=hd.querySelector('.member-col-chevron');
      const isOpen=wrap.style.display!=='none';
      // Закриваємо всі, відкриваємо цей
      el.querySelectorAll('.member-cards-wrap').forEach(w=>{w.style.display='none';});
      el.querySelectorAll('.member-col-chevron').forEach(c=>{c.style.transform='rotate(-90deg)';});
      if(!isOpen){wrap.style.display='';chev.style.transform='';}
    });
  });

  // Клік по картці
  el.querySelectorAll('.wallet-card').forEach(ch=>{
    ch.addEventListener('click',e=>{
      e.stopPropagation();
      openAccountDetail(ch.dataset.account,ch.dataset.member);
    });
  });

  // За замовчуванням відкриваємо першого члена
  const firstWrap=el.querySelector('.member-cards-wrap');
  const firstChev=el.querySelector('.member-col-chevron');
  if(firstWrap){firstWrap.style.display='';if(firstChev)firstChev.style.transform='';}
  // Решту закриваємо
  el.querySelectorAll('.member-cards-wrap:not(:first-of-type)').forEach((w,i)=>{
    if(i>0){w.style.display='none';}
  });
  el.querySelectorAll('.member-col').forEach((col,i)=>{
    const wrap=col.querySelector('.member-cards-wrap');
    const chev=col.querySelector('.member-col-chevron');
    if(i>0&&wrap){wrap.style.display='none';if(chev)chev.style.transform='rotate(-90deg)';}
  });
}

function renderAccountChips(){
  const el=document.getElementById('accounts-row');if(!el)return;
  const cards=getCards();
  const balances=getAccountBalances();
  el.innerHTML=cards.map(c=>{
    const bal=balances[c.id]||0;
    const isActive=state.activeAccountId===c.id;
    return `<div class="account-chip${isActive?' active':''}" data-account="${esc(c.id)}">
      <div class="account-chip-icon" style="background:${c.bg}"><i class="ti ${c.icon}" style="color:${c.color}"></i></div>
      <div class="account-chip-info">
        <div class="account-chip-name">${esc(c.id)}</div>
        <div class="account-chip-bal ${bal>=0?'pos':'neg'}">${fmtMoney(Math.abs(bal),'UAH')}</div>
      </div>
    </div>`;
  }).join('');
  el.querySelectorAll('.account-chip').forEach(ch=>{
    ch.addEventListener('click',()=>openAccountDetail(ch.dataset.account));
  });
}
function openAccountDetail(accountId,member){
  const cards=member?getCards(member):getCards();
  const card=cards.find(c=>c.id===accountId);
  if(!card)return;
  const ops=state.operations.filter(o=>o.card===accountId&&(!member||o.who===member));
  const bal=getAccountBalances()[accountId]||0;
  let old=document.getElementById('account-detail-modal');if(old)old.remove();
  const div=document.createElement('div');
  div.id='account-detail-modal';
  div.style.cssText='position:fixed;inset:0;z-index:500;display:flex;align-items:flex-end;justify-content:center;background:rgba(0,0,0,.5);backdrop-filter:blur(2px);';
  const txHtml=ops.length?ops.slice(0,15).map(txItem).join(''):'<div style="padding:20px;text-align:center;color:var(--c-text-3)">Операцій немає</div>';
  div.innerHTML=`<div style="background:var(--c-card);border-radius:20px 20px 0 0;padding:20px;width:100%;max-width:500px;max-height:85vh;overflow-y:auto;">
    <div style="width:40px;height:4px;background:var(--c-border);border-radius:2px;margin:0 auto 16px;"></div>
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:20px;">
      <div style="width:48px;height:48px;border-radius:14px;background:${card.bg};display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;"><i class="ti ${card.icon}" style="color:${card.color}"></i></div>
      <div style="flex:1"><div style="font-size:18px;font-weight:700;">${esc(card.id)}</div><div style="font-size:13px;color:var(--c-text-2)">Рахунок</div></div>
      <div style="text-align:right"><div style="font-size:20px;font-weight:800;color:${bal>=0?'var(--c-green)':'var(--c-red)'};">${fmtMoney(bal,'UAH')}</div><div style="font-size:11px;color:var(--c-text-3)">Поточний баланс</div></div>
    </div>
    <div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--c-text-3);margin-bottom:10px;">Операції</div>
    <div class="tx-list">${txHtml}</div>
    <button id="acc-close-btn" style="width:100%;margin-top:16px;padding:13px;border-radius:14px;background:var(--c-bg-3);color:var(--c-text-2);font-size:14px;font-weight:700;">Закрити</button>
  </div>`;
  document.body.appendChild(div);
  div.addEventListener('click',e=>{if(e.target===div)div.remove();});
  div.querySelector('#acc-close-btn').addEventListener('click',()=>div.remove());
}
function renderRecentOps(ops){
  const el=document.getElementById('recent-list');
  if(!ops.length){el.innerHTML='<div style="padding:16px;text-align:center;color:var(--c-text-3);font-size:13px">Операцій немає</div>';return;}
  el.innerHTML=ops.slice(0,6).map((op,i)=>txItem(op,true,state.operations.indexOf(op))).join('');
  el.querySelectorAll('.tx-edit-btn').forEach(btn=>{btn.addEventListener('click',()=>openEditModal(btn.dataset.row));});
}
function txItem(op,editable=false,opIdx){
  const cat=getCat(op.category);const plus=op.type==="Дохід";
  const whoCards=getCards(op.who);const cardObj=whoCards.find(c=>c.id===op.card)||getCards().find(c=>c.id===op.card);
  const cardBadge=cardObj?`<span style="display:inline-flex;align-items:center;gap:3px;background:${cardObj.bg};color:${cardObj.color};border-radius:4px;padding:1px 5px;font-size:10px;font-weight:700;white-space:nowrap;"><i class="ti ${cardObj.icon}"></i>${esc(cardObj.id)}</span>`:'';
  // Використовуємо row якщо є, інакше індекс масиву (для локальних операцій)
  const editId=op.row||opIdx;
  const pendingBadge=op._local?'<span style="font-size:9px;background:#f59e0b22;color:#f59e0b;border-radius:3px;padding:1px 4px;margin-left:4px;">↑</span>':'';
  const editBtn=editable?`<button class="tx-edit-btn" data-row="${editId}" style="opacity:${editId!==undefined?1:.4}"><i class="ti ti-edit"></i></button>`:'';
  return `<div class="tx-item"><div class="tx-icon" style="background:${cat.bg}"><i class="ti ${cat.icon}" style="color:${cat.color}"></i></div><div class="tx-info"><div class="tx-name">${esc(op.desc||op.category)}${pendingBadge}</div><div class="tx-meta">${esc(op.category)} · ${esc(op.who||'')} · ${fmtDate(op.date)} ${cardBadge}</div></div><div style="display:flex;align-items:center;gap:8px;"><div class="tx-amount ${plus?'plus':'minus'}">${plus?'+':'−'}${fmtMoney(op.amount,op.currency)}</div>${editBtn}</div></div>`;
}
function renderCatBars(id,by,total){
  const el=document.getElementById(id);if(!el)return;
  const sorted=Object.entries(by).sort((a,b)=>b[1]-a[1]).slice(0,8);
  const mx=sorted[0]?.[1]||1;
  el.innerHTML=sorted.map(([cat,amt])=>{
    const c=getCat(cat);const pct=Math.round(amt/mx*100);
    return '<div class="cat-bar-item"><div class="cat-bar-icon" style="background:'+c.bg+'"><i class="ti '+c.icon+'" style="color:'+c.color+'"></i></div><div class="cat-bar-info"><div class="cat-bar-name">'+esc(cat)+'</div><div class="cat-bar-track"><div class="cat-bar-fill" style="width:'+pct+'%;background:'+c.color+'"></div></div></div><div class="cat-bar-amt">'+fmtMoney(amt,"UAH")+'</div></div>';
  }).join('');
}
function renderDailyChart(byDay){
  const el=document.getElementById('daily-chart');if(!el)return;
  const d=state.currentMonth;const daysInMonth=new Date(d.getFullYear(),d.getMonth()+1,0).getDate();
  const days=[];for(let i=1;i<=daysInMonth;i++)days.push(i);
  const mx=Math.max(...days.map(i=>byDay[i]||0),1);
  el.innerHTML=days.map(i=>{
    const amt=byDay[i]||0;const h=Math.max(Math.round(amt/mx*68),amt>0?4:0);
    return '<div class="daily-bar-wrap" title="'+i+' — '+fmtMoney(amt,"UAH")+'"><div class="daily-bar" style="height:'+h+'px"></div><div class="daily-bar-label">'+i+'</div></div>';
  }).join('');
}

// ── RENDER OPERATIONS ─────────────────────────────────────────────
function renderOperations(){
  const el=document.getElementById('ops-list');
  let ops=state.operations;
  if(state.filterActive!=="all")ops=ops.filter(o=>o.type===state.filterActive||o.budget===state.filterActive||o.card===state.filterActive);
  if(!ops.length){el.innerHTML='<div style="padding:20px;text-align:center;color:var(--c-text-3)">Немає операцій</div>';return;}
  // Зберігаємо маппінг відфільтрованих ops → оригінальні індекси
  const opsWithIdx=ops.map(op=>({op,idx:state.operations.indexOf(op)}));
  el.innerHTML=opsWithIdx.map(({op,idx})=>txItem(op,true,idx)).join('');
  el.querySelectorAll('.tx-edit-btn').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const rowVal=btn.dataset.row;openEditModal(rowVal);
    });
  });
}
function openEditModal(rowOrIdx){
  // Шукаємо за row (збережені в Sheet) або за індексом (локальні)
  let op=null;
  const rowStr=String(rowOrIdx);
  // 1. Шукаємо за row числом
  if(rowOrIdx&&rowOrIdx!=='')op=state.operations.find(o=>o.row&&String(o.row)===rowStr);
  // 2. Якщо не знайшли — шукаємо за індексом масиву (для локальних операцій)
  if(!op){const idx=parseInt(rowOrIdx);if(!isNaN(idx)&&state.operations[idx])op=state.operations[idx];}
  if(!op){showToast('Операцію не знайдено','error');return;}
  let old2=document.getElementById('edit-op-modal');if(old2)old2.remove();
  const whoMember=op.who||getMyMember();
  const cards=getCards(whoMember);
  const cardOpts=cards.map(c=>`<option value="${esc(c.id)}" ${op.card===c.id?'selected':''}>${esc(c.id)}</option>`).join('');
  const cats=[...getExpCats(),...getIncCats()];
  const catOpts=cats.map(c=>`<option value="${esc(c.id)}" ${op.category===c.id?'selected':''}>${esc(c.id)}</option>`).join('');
  const memberOpts=FAMILY_MEMBERS.map(m=>`<option value="${esc(m)}" ${op.who===m?'selected':''}>${esc(m)}</option>`).join('');
  const div=document.createElement('div');
  div.id='edit-op-modal';
  div.style.cssText='position:fixed;inset:0;z-index:500;display:flex;align-items:flex-end;justify-content:center;background:rgba(0,0,0,.5);backdrop-filter:blur(2px);';
  div.innerHTML=`<div style="background:var(--c-card);border-radius:20px 20px 0 0;padding:20px;width:100%;max-width:500px;max-height:85vh;overflow-y:auto;">
    <div style="width:40px;height:4px;background:var(--c-border);border-radius:2px;margin:0 auto 16px;"></div>
    <div style="font-size:17px;font-weight:700;margin-bottom:16px;">Редагувати операцію</div>
    <div class="modal-row"><label class="modal-label">Тип</label>
      <select id="edit-type" class="desc-input" style="margin-bottom:0">
        <option value="Витрата" ${op.type==='Витрата'?'selected':''}>Витрата</option>
        <option value="Дохід" ${op.type==='Дохід'?'selected':''}>Дохід</option>
      </select></div>
    <div class="modal-row"><label class="modal-label">Сума</label>
      <input id="edit-amount" type="number" class="desc-input" value="${op.amount||''}" style="margin-bottom:0"></div>
    <div class="modal-row"><label class="modal-label">Категорія</label>
      <select id="edit-cat" class="desc-input" style="margin-bottom:0">${catOpts}</select></div>
    <div class="modal-row"><label class="modal-label">Хто</label>
      <select id="edit-who" class="desc-input" style="margin-bottom:0">${memberOpts}</select></div>
    <div class="modal-row"><label class="modal-label">Рахунок</label>
      <select id="edit-card" class="desc-input" style="margin-bottom:0">${cardOpts}</select></div>
    <div class="modal-row"><label class="modal-label">Опис</label>
      <input id="edit-desc" type="text" class="desc-input" value="${esc(op.desc||'')}" style="margin-bottom:0"></div>
    <div style="display:flex;gap:10px;margin-top:16px;">
      <button id="edit-delete-btn" style="flex:1;padding:13px;border-radius:14px;background:var(--c-red-soft);color:var(--c-red);font-size:14px;font-weight:700;">Видалити</button>
      <button id="edit-save-btn" style="flex:2;padding:13px;border-radius:14px;background:var(--c-accent);color:#fff;font-size:14px;font-weight:700;">Зберегти</button>
    </div>
  </div>`;
  document.body.appendChild(div);
  div.addEventListener('click',e=>{if(e.target===div)div.remove();});
  div.querySelector('#edit-save-btn').addEventListener('click',async()=>{
    const newAmt=parseFloat(div.querySelector('#edit-amount').value);
    if(!newAmt||newAmt<=0){showToast('Вкажи суму','error');return;}
    const newWho=div.querySelector('#edit-who')?.value||op.who;const body={action:'updateOperation',row:op.row,type:div.querySelector('#edit-type').value,amount:newAmt,category:div.querySelector('#edit-cat').value,card:div.querySelector('#edit-card').value,desc:div.querySelector('#edit-desc').value,currency:op.currency||'UAH',who:newWho,budget:newWho};
    try{
      if(state.scriptUrl)await apiPost(body);
      // Update local
      Object.assign(op,{type:body.type,amount:newAmt,amountUah:newAmt,category:body.category,card:body.card,desc:body.desc,who:body.who,budget:body.budget});
      div.remove();renderOperations();renderAccountChips();showToast('✅ Збережено!');
    }catch(e){showToast('Помилка','error');}
  });
  div.querySelector('#edit-delete-btn').addEventListener('click',async()=>{
    if(!confirm('Видалити операцію?'))return;
    try{
      state.operations=state.operations.filter(o=>o!==op);
      div.remove();renderOperations();renderMemberColumns();showToast('Видалено');
      if(state.scriptUrl&&op.row){const dBody={action:'deleteOperation',row:op.row};apiPost(dBody).then(()=>showSyncStatus('ok')).catch(()=>{enqueue(dBody);showSyncStatus('pending');});}
    }catch(e){showToast('Помилка','error');}
  });
}

// ── RENDER CALENDAR ───────────────────────────────────────────────
function getCalPeriodOps(){
  const period=state.calPeriod||'month';
  const now=state.calMonth;
  let from,to;
  if(period==='month'){from=new Date(now.getFullYear(),now.getMonth(),1);to=new Date(now.getFullYear(),now.getMonth()+1,0);}
  else if(period==='3m'){from=new Date(now.getFullYear(),now.getMonth()-2,1);to=new Date(now.getFullYear(),now.getMonth()+1,0);}
  else if(period==='6m'){from=new Date(now.getFullYear(),now.getMonth()-5,1);to=new Date(now.getFullYear(),now.getMonth()+1,0);}
  else{from=new Date(now.getFullYear(),0,1);to=new Date(now.getFullYear(),11,31);}
  return{ops:state.operations.filter(o=>{const d=new Date(o.date);return d>=from&&d<=to;}),from,to};
}
function updateCalKPI(){
  const{ops}=getCalPeriodOps();
  const inc=ops.filter(o=>o.type==="Дохід").reduce((s,o)=>s+(o.amountUah||o.amount),0);
  const exp=ops.filter(o=>o.type==="Витрата").reduce((s,o)=>s+(o.amountUah||o.amount),0);
  setText('cal-income',fmtMoney(inc,'UAH'));
  setText('cal-expense',fmtMoney(exp,'UAH'));
  setText('cal-balance',fmtMoney(inc-exp,'UAH'));
}
function showCalDay(day,m,y){
  const ops=state.operations.filter(o=>{
    const od=new Date(o.date);return od.getDate()===day&&od.getMonth()===m&&od.getFullYear()===y;
  });
  const det=document.getElementById('cal-day-detail');
  const ttl=document.getElementById('cal-day-title');
  const lst=document.getElementById('cal-day-list');
  setText('cal-day-title',day+' '+MONTH_UK[m].toLowerCase());
  if(!ops.length){lst.innerHTML='<div style="padding:16px;text-align:center;color:var(--c-text-3);font-size:13px">Немає операцій</div>';}
  else lst.innerHTML=ops.map(txItem).join('');
  det.style.display='block';
}

// ── RENDER ANALYTICS ─────────────────────────────────────────────
function renderAnalytics(){
  const d=state.dashboard;if(!d)return;
  renderCatBars('analytics-cats',d.byCategory||{},d.totalExpense);
  const el=document.getElementById('analytics-budgets');
  const bud=d.budgets||{};
  const mx=Math.max(...Object.values(bud).map(b=>b.expense||0))||1;
  const avs={"Сімейний":{ic:'ti-users',bg:'var(--c-bg-3)',cl:'var(--c-text-2)'},"Євген":{av:'ЄК',bg:'var(--c-blue-soft)',cl:'var(--c-blue)'},"Марина":{av:'МК',bg:'var(--c-pink-soft)',cl:'var(--c-pink)'}};
  el.innerHTML=Object.entries(bud).map(([n,b])=>{
    const a=avs[n]||avs["Сімейний"];
    const pct=Math.round((b.expense||0)/mx*100);
    const av=a.ic?'<div class="budget-bar-av" style="background:'+a.bg+';color:'+a.cl+'"><i class="ti '+a.ic+'"></i></div>':'<div class="budget-bar-av" style="background:'+a.bg+';color:'+a.cl+'">'+a.av+'</div>';
    return '<div class="budget-bar-item">'+av+'<div class="budget-bar-info"><div class="budget-bar-name">'+esc(n)+'</div><div class="budget-bar-track"><div class="budget-bar-fill" style="width:'+pct+'%;background:var(--c-red)"></div></div></div><div class="budget-bar-val" style="color:var(--c-red)">'+fmtMoney(b.expense,"UAH")+'</div></div>';
  }).join('');
}

// ── RENDER RESERVE ────────────────────────────────────────────────
function renderReserve(d){
  setText('res-total',fmtMoney(d.totalUah,'UAH'));setText('res-months',d.monthsCoverage+' міс.');
  setText('res-added',fmtMoney(d.addedThisMonth,'UAH'));
  setText('res-months-label','при витратах ~'+fmtMoney(d.avgMonthlyExpense,'UAH')+'/міс');
  setText('mm-val',d.monthsCoverage+' міс.');
  document.getElementById('mm-fill').style.width=Math.min(d.monthsCoverage/6*100,100)+'%';
  const rates=d.rates||{UAH:1,USD:40,EUR:44};const bals=d.balances||{};
  document.getElementById('res-currencies').innerHTML=['UAH','USD','EUR'].map(cur=>{
    const flags={UAH:'🇺🇦',USD:'🇺🇸',EUR:'🇪🇺'},names={UAH:'Гривня',USD:'Долар',EUR:'Євро'};
    const r=rates[cur]||1,a=bals[cur]||0,eq=Math.round(a*r),sym=CUR_SYMBOLS[cur];
    const psh=d.totalUah?Math.round(eq/d.totalUah*100):0;
    return '<div class="tx-item"><div class="tx-icon" style="font-size:20px">'+flags[cur]+'</div><div class="tx-info"><div class="tx-name">'+names[cur]+'</div><div class="tx-meta">'+(cur!=="UAH"?'Курс: '+r.toFixed(2)+' ₴':'Основна валюта')+'</div></div><div style="text-align:right"><div style="font-size:14px;font-weight:700">'+sym+Math.abs(a).toLocaleString('uk-UA')+'</div><div style="font-size:11px;color:var(--c-text-2)">'+eq.toLocaleString('uk-UA')+' ₴ · '+psh+'%</div></div></div>';
  }).join('');
  const hist=d.history||[],mxh=Math.max(...hist.map(h=>h.total),1);
  document.getElementById('res-history').innerHTML=hist.slice(-6).map(h=>'<div class="res-hist-row"><div class="res-hist-month">'+h.month.substring(5)+'</div><div class="res-hist-bar-wrap"><div class="res-hist-bar" style="width:'+Math.round(h.total/mxh*100)+'%"></div></div><div class="res-hist-val">'+fmtMoney(h.total,"UAH")+'</div></div>').join('');
  document.getElementById('res-tx-list').innerHTML=(d.transactions||[]).slice(0,8).map(tx=>{
    const add=tx.type==="Поповнення";
    return '<div class="tx-item"><div class="tx-icon" style="background:'+(add?'var(--c-green-soft)':'var(--c-red-soft)')+'"><i class="ti ti-shield" style="color:'+(add?'var(--c-green)':'var(--c-red)')+'"></i></div><div class="tx-info"><div class="tx-name">'+esc(tx.comment||tx.type)+'</div><div class="tx-meta">'+esc(tx.type)+' · '+esc(tx.who||'')+' · '+fmtDate(tx.date)+'</div></div><div class="tx-amount '+(add?'plus':'minus')+'">'+(add?'+':'−')+(CUR_SYMBOLS[tx.currency]||'₴')+Math.abs(tx.amount).toLocaleString('uk-UA')+'</div></div>';
  }).join('');
}

// ── RENDER GOALS ─────────────────────────────────────────────────
function renderGoals(goals){
  const el=document.getElementById('goals-list');
  if(!goals.length){el.innerHTML='<div style="padding:20px;color:var(--c-text-3);font-size:14px">Цілей немає. Додай першу ціль!</div>';return;}
  el.innerHTML=goals.map((g,i)=>{
    const pct=g.target>0?Math.min(Math.round(g.saved/g.target*100),100):0;
    return '<div class="goal-card"><div class="goal-card-head"><div class="goal-icon" style="background:var(--c-blue-soft)"><i class="ti ti-target" style="color:var(--c-blue)"></i></div><div style="flex:1"><div class="goal-name">'+esc(g.displayName||g.name)+'</div><div class="goal-budget">'+esc(g.budget||'Сімейний')+'</div></div><div class="goal-pct">'+pct+'%</div></div><div class="goal-progress-wrap"><div class="goal-progress-fill" style="width:'+pct+'%"></div></div><div class="goal-footer"><span class="goal-saved">'+fmtMoney(g.saved,'UAH')+'</span><span class="goal-remaining">з '+fmtMoney(g.target,'UAH')+'</span></div><div class="goal-actions"><button class="goal-action-btn goal-transfer-btn" data-idx="'+i+'">⇄ Переказ</button><button class="goal-action-btn goal-delete-btn" data-del="'+i+'">✕ Видалити</button></div></div>';
  }).join('');
  document.querySelectorAll('.goal-transfer-btn').forEach(b=>{
    b.addEventListener('click',()=>openTransferModal(parseInt(b.dataset.idx)));
  });
  document.querySelectorAll('.goal-delete-btn').forEach(b=>{
    b.addEventListener('click',()=>{
      if(!confirm('Видалити ціль?'))return;
      const g=getGoals();const delIdx=parseInt(b.dataset.del);const delGoal=g[delIdx];g.splice(delIdx,1);saveGoals(g);renderGoals(g);showToast('Ціль видалено');
      if(state.scriptUrl&&delGoal?.row)apiPost({action:'deleteGoal',row:delGoal.row}).catch(()=>{});
    });
  });
}

// ── RENDER SETTINGS ───────────────────────────────────────────────
function renderSettingsUI(){
  const el=document.getElementById('script-url-preview');
  if(el) el.textContent=state.scriptUrl?state.scriptUrl.substring(0,50)+'…':'Не налаштовано';
  const ss=document.getElementById('sync-status');
  if(ss){
    const lastSync=localStorage.getItem(APP_CONFIG.LAST_SYNC_KEY);
    ss.textContent=state.scriptUrl?(lastSync?'● Синхр. '+new Date(lastSync).toLocaleTimeString('uk-UA',{hour:'2-digit',minute:'2-digit'}):'● Підключено'):'○ Не підключено';
    ss.style.color=state.scriptUrl?'var(--c-green)':'var(--c-red)';
  }
  renderCatsList('expense-cats-list',getExpCats(),false);
  renderCatsList('income-cats-list',getIncCats(),true);
  renderMemberProfileCard('evgen','Євген');
  renderMemberProfileCard('marina','Марина');
}
function renderCatsList(containerId,cats,isIncome){
  const el=document.getElementById(containerId);if(!el)return;
  el.innerHTML=cats.map((c,i)=>`<div class="cat-accordion-item"><div class="cat-bar-icon" style="background:${c.bg}"><i class="ti ${c.icon}" style="color:${c.color}"></i></div><div class="cat-accordion-name">${esc(c.id)}</div><button class="cat-del-btn" data-idx="${i}" data-inc="${isIncome}"><i class="ti ti-x"></i></button></div>`).join('');
  el.querySelectorAll('.cat-del-btn').forEach(b=>{
    b.addEventListener('click',()=>{
      const inc=b.dataset.inc==='true';
      const key=inc?APP_CONFIG.INC_CATS_KEY:APP_CONFIG.EXP_CATS_KEY;
      const list=inc?getIncCats():getExpCats();
      list.splice(parseInt(b.dataset.idx),1);
      localStorage.setItem(key,JSON.stringify(list));
      syncSettingsToSheet();
      renderSettingsUI();showToast('Категорію видалено');
    });
  });
}
function renderCardsList(containerId,cards,member){
  const el=document.getElementById(containerId);if(!el)return;
  el.innerHTML=cards.map((c,i)=>`<div class="cat-accordion-item"><div class="cat-bar-icon" style="background:${c.bg}"><i class="ti ${c.icon}" style="color:${c.color}"></i></div><div class="cat-accordion-name">${esc(c.id)}</div><button class="cat-del-btn" data-idx="${i}" data-member="${esc(member||'')}"><i class="ti ti-x"></i></button></div>`).join('');
  el.querySelectorAll('.cat-del-btn').forEach(b=>{
    b.addEventListener('click',()=>{
      const m=b.dataset.member||null;
      const list=getCards(m);list.splice(parseInt(b.dataset.idx),1);saveCards(list,m);
      renderSettingsUI();renderMemberColumns();showToast('Картку видалено');
    });
  });
}

// ── RENDER MEMBER PROFILE CARD (Settings) ────────────────────────
function renderMemberProfileCard(elemId, member){
  const el=document.getElementById('member-profile-'+elemId);if(!el)return;
  const profs=getProfiles();
  const prof=profs[member]||{name:member,avatar:null};
  const mc=MEMBER_COLORS[member]||{bg:'var(--c-bg-3)',cl:'var(--c-text)',initials:'??'};
  const cards=getCards(member);
  const isAdmin=(state.user?.role==='admin'||getMyMember()===member);
  const avatarHtml=prof.avatar
    ?`<img src="${prof.avatar}" style="width:44px;height:44px;border-radius:50%;object-fit:cover;">`
    :`<div style="width:44px;height:44px;border-radius:50%;background:${mc.bg};color:${mc.cl};display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;">${mc.initials}</div>`;
  el.innerHTML=`
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
      <div style="cursor:pointer;" id="av-click-${elemId}">${avatarHtml}</div>
      <div style="flex:1">
        <input class="settings-name-input" id="profile-name-${elemId}" value="${esc(prof.name||member)}" placeholder="Ім'я" style="font-size:15px;font-weight:700;width:100%;${!isAdmin?'opacity:.5;pointer-events:none;':''}">
        <div style="font-size:11px;color:var(--c-text-3);margin-top:3px;">Ім'я гаманця = ім'я профілю</div>
      </div>
      ${isAdmin?`<button class="btn-ghost-sm" id="save-profile-${elemId}"><i class="ti ti-check"></i></button>`:''}
    </div>
    <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--c-text-3);margin-bottom:8px;">Рахунки</div>
    <div class="cat-accordion" id="cards-${elemId}-list"></div>
    ${isAdmin?`<div class="settings-row-item" style="margin-top:8px;"><input class="settings-name-input flex1" id="new-card-${elemId}" placeholder="Назва рахунку"><button class="btn-ghost-sm" id="add-card-${elemId}"><i class="ti ti-plus"></i> Іконка</button></div>`:''}
  `;
  renderCardsList('cards-'+elemId+'-list', cards, member);
  const saveBtn=el.querySelector('#save-profile-'+elemId);
  if(saveBtn) saveBtn.addEventListener('click',()=>{
    const newName=el.querySelector('#profile-name-'+elemId).value.trim();if(!newName)return;
    const profs2=getProfiles();profs2[member]=profs2[member]||{};profs2[member].name=newName;
    saveProfiles(profs2);renderMemberColumns();showToast('✅ Збережено!');
  });
  const avBtn=el.querySelector('#av-click-'+elemId);
  if(avBtn&&isAdmin) avBtn.addEventListener('click',()=>{
    const inp=document.createElement('input');inp.type='file';inp.accept='image/*';
    inp.onchange=e=>{const f=e.target.files[0];if(!f)return;const r=new FileReader();
      r.onload=ev=>{const url=ev.target.result;const profs2=getProfiles();
        profs2[member]=profs2[member]||{};profs2[member].avatar=url;saveProfiles(profs2);
        if(member===getMyMember()){localStorage.setItem(APP_CONFIG.AVATAR_KEY,url);applyAvatar(url);}
        renderMemberProfileCard(elemId,member);renderMemberColumns();showToast('✅ Аватар!');};
      r.readAsDataURL(f);};inp.click();
  });
  const addBtn=el.querySelector('#add-card-'+elemId);
  if(addBtn) addBtn.addEventListener('click',()=>{
    openIconPicker(elemId==='evgen'?'card-evgen':'card-marina');
  });
}

// ── RENDER CALENDAR (з режимами) ─────────────────────────────────
function renderCalendar(){
  const period=state.calPeriod||'month';
  updateCalKPI();
  const grid=document.getElementById('cal-grid');
  if(period==='month') renderCalMonth(grid);
  else if(period==='3m') renderCalMulti(grid,3);
  else if(period==='6m') renderCalMulti(grid,6);
  else renderCalYear(grid);
}
function renderCalMonth(grid){
  const d=state.calMonth,y=d.getFullYear(),m=d.getMonth();
  setText('cal-month-label',MONTH_UK[m]+' '+y);
  const firstDay=(new Date(y,m,1).getDay()+6)%7;
  const daysInMonth=new Date(y,m+1,0).getDate();
  const byDay={};
  state.operations.filter(o=>{const od=new Date(o.date);return od.getFullYear()===y&&od.getMonth()===m&&o.type==='Витрата';})
    .forEach(o=>{const day=new Date(o.date).getDate();byDay[day]=(byDay[day]||0)+(o.amountUah||o.amount);});
  const today=new Date();
  const H=['Пн','Вт','Ср','Чт','Пт','Сб','Нд'];
  let html=H.map(h=>'<div class="cal-header">'+h+'</div>').join('');
  for(let i=0;i<firstDay;i++)html+='<div class="cal-day empty"></div>';
  for(let day=1;day<=daysInMonth;day++){
    const amt=byDay[day]||0,isToday=today.getDate()===day&&today.getMonth()===m&&today.getFullYear()===y;
    html+='<div class="cal-day'+(isToday?' today':'')+'" data-day="'+day+'" data-m="'+m+'" data-y="'+y+'"><div class="cal-day-num">'+day+'</div>'+(amt?'<div class="cal-day-amt">'+fmtMoney(amt,'UAH')+'</div>':'')+'</div>';
  }
  grid.innerHTML=html;
  addCalListeners(grid);
}
function renderCalMulti(grid,count){
  const now=state.calMonth;
  let html='';
  for(let i=count-1;i>=0;i--){
    const d=new Date(now.getFullYear(),now.getMonth()-i,1);
    const y=d.getFullYear(),m=d.getMonth();
    const firstDay=(new Date(y,m,1).getDay()+6)%7;
    const daysInMonth=new Date(y,m+1,0).getDate();
    const byDay={};
    state.operations.filter(o=>{const od=new Date(o.date);return od.getFullYear()===y&&od.getMonth()===m&&o.type==='Витрата';})
      .forEach(o=>{const day=new Date(o.date).getDate();byDay[day]=(byDay[day]||0)+(o.amountUah||o.amount);});
    const H=['Пн','Вт','Ср','Чт','Пт','Сб','Нд'];
    html+='<div style="margin-bottom:20px"><div style="font-size:13px;font-weight:700;color:var(--c-accent);margin-bottom:8px;padding-left:2px">'+MONTH_UK[m]+' '+y+'</div>';
    html+='<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:3px">';
    html+=H.map(h=>'<div class="cal-header">'+h+'</div>').join('');
    let day=1;
    const weeks=Math.ceil((firstDay+daysInMonth)/7);
    for(let w=0;w<weeks;w++){
      for(let dw=0;dw<7;dw++){
        if((w===0&&dw<firstDay)||day>daysInMonth){html+='<div class="cal-day empty" style="min-height:34px"></div>';}
        else{
          const amt=byDay[day]||0;
          html+='<div class="cal-day" style="min-height:34px;padding:3px 2px" data-day="'+day+'" data-m="'+m+'" data-y="'+y+'"><div class="cal-day-num" style="font-size:10px">'+day+'</div>'+(amt?'<div class="cal-day-dot"></div>':'')+'</div>';
          day++;
        }
      }
    }
    html+='</div></div>';
  }
  setText('cal-month-label',count+' міс.');
  grid.innerHTML=html;
  addCalListeners(grid);
}
function renderCalYear(grid){
  const y=state.calMonth.getFullYear();
  setText('cal-month-label',String(y));
  const byMonth=new Array(12).fill(0);
  state.operations.filter(o=>{const d=new Date(o.date);return d.getFullYear()===y&&o.type==='Витрата';})
    .forEach(o=>{byMonth[new Date(o.date).getMonth()]+=(o.amountUah||o.amount);});
  const mx=Math.max(...byMonth,1);
  const today=new Date();
  let html='<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:8px;padding:4px 0">';
  html+=MONTH_UK.map((mn,mi)=>{
    const h=Math.max(Math.round(byMonth[mi]/mx*80),byMonth[mi]>0?4:0);
    const isCur=today.getMonth()===mi&&today.getFullYear()===y;
    return '<div style="display:flex;flex-direction:column;align-items:center;gap:4px;cursor:pointer" data-m="'+mi+'" data-y="'+y+'">'
      +'<div style="width:100%;height:88px;display:flex;align-items:flex-end;justify-content:center">'
      +'<div style="width:70%;height:'+h+'px;border-radius:4px 4px 0 0;background:var(--c-accent);opacity:'+(isCur?1:.7)+'"></div></div>'
      +'<div style="font-size:9px;font-weight:700;color:var(--c-text-2);text-align:center">'+(byMonth[mi]>0?fmtMoney(byMonth[mi],'UAH'):'')+'</div>'
      +'<div style="font-size:10px;font-weight:'+(isCur?700:600)+';color:'+(isCur?'var(--c-accent)':'var(--c-text-3)')+'">'+mn.substring(0,3)+'</div>'
      +'</div>';
  }).join('');
  html+='</div>';
  grid.innerHTML=html;
  grid.querySelectorAll('[data-m][data-y]').forEach(el=>{
    el.addEventListener('click',()=>{
      state.calMonth=new Date(parseInt(el.dataset.y),parseInt(el.dataset.m),1);
      state.calPeriod='month';
      document.querySelectorAll('.cal-period-btn').forEach(b=>b.classList.toggle('active',b.dataset.period==='month'));
      renderCalendar();
    });
  });
}
function addCalListeners(grid){
  grid.querySelectorAll('.cal-day[data-day]').forEach(el=>{
    el.addEventListener('click',()=>{
      grid.querySelectorAll('.cal-day').forEach(x=>x.classList.remove('selected'));
      el.classList.add('selected');
      showCalDay(parseInt(el.dataset.day),parseInt(el.dataset.m||state.calMonth.getMonth()),parseInt(el.dataset.y||state.calMonth.getFullYear()));
    });
  });
}

// ── DEMO DATA ─────────────────────────────────────────────────────
function renderDemoData(page){
  if(page==='dashboard'){
    // Генеруємо демо операції по рахунках
    // Демо операції тільки якщо scriptUrl НЕ налаштований (офлайн режим)
    if(!state.scriptUrl&&!state.operations.length){state.operations=[{date:new Date().toISOString(),type:'Витрата',category:'Продукти',desc:'Сільпо',amount:680,currency:'UAH',amountUah:680,who:'Євген',card:'Моно чорна',_demo:true},{date:new Date(Date.now()-86400000).toISOString(),type:'Дохід',category:'Зарплата',desc:'Зарплата',amount:32000,currency:'UAH',amountUah:32000,who:'Євген',card:'Приват',_demo:true},{date:new Date(Date.now()-86400000).toISOString(),type:'Витрата',category:'Транспорт',desc:'ОККО',amount:1200,currency:'UAH',amountUah:1200,who:'Марина',card:'Готівка',_demo:true},{date:new Date(Date.now()-172800000).toISOString(),type:'Дохід',category:'Зарплата',desc:'Зарплата',amount:18000,currency:'UAH',amountUah:18000,who:'Марина',card:'Приват',_demo:true}];}
    renderDashboard({
      totalIncome:58500,totalExpense:16940,balance:41560,savingsRate:71,
      budgets:{"Сімейний":{income:0,expense:7420,balance:-7420},"Євген":{income:40500,expense:8420,balance:32080},"Марина":{income:18000,expense:1100,balance:16900}},
      byCategory:{"Продукти":5680,"Комунальні":3200,"Транспорт":2800,"Ресторани":1960,"Розваги":1400,"Здоров'я":900,"Одяг":600,"Дім":400},
      byDay:{3:680,5:1200,7:340,9:2400,11:850,14:1200,16:440,18:900,20:1100,22:680,25:1500,27:350},
      recent:[
        {date:new Date().toISOString(),type:'Витрата',category:'Продукти',desc:'Сільпо',amount:680,currency:'UAH',who:'Євген'},
        {date:new Date(Date.now()-86400000).toISOString(),type:'Дохід',category:'Зарплата',desc:'Зарплата',amount:32000,currency:'UAH',who:'Євген'},
        {date:new Date(Date.now()-86400000).toISOString(),type:'Витрата',category:'Транспорт',desc:'ОККО',amount:1200,currency:'UAH',who:'Марина'},
        {date:new Date(Date.now()-172800000).toISOString(),type:'Витрата',category:'Комунальні',desc:'Yasno',amount:2400,currency:'UAH',who:'Марина'},
        {date:new Date(Date.now()-259200000).toISOString(),type:'Дохід',category:'Підробіток',desc:'Фріланс',amount:8500,currency:'UAH',who:'Євген'},
      ],
    });
  }
  if(page==='operations'){
    state.operations=[
      {date:new Date().toISOString(),type:'Витрата',category:'Продукти',desc:'Сільпо',amount:680,currency:'UAH',who:'Євген',budget:'Сімейний'},
      {date:new Date(Date.now()-86400000).toISOString(),type:'Дохід',category:'Зарплата',desc:'Зарплата',amount:32000,currency:'UAH',who:'Євген',budget:'Євген'},
      {date:new Date(Date.now()-172800000).toISOString(),type:'Витрата',category:'Транспорт',desc:'ОККО',amount:1200,currency:'UAH',who:'Марина',budget:'Сімейний'},
    ];
    renderOperations();
  }
  if(page==='calendar')renderCalendar();
  if(page==='reserve')renderReserve({
    totalUah:187400,monthsCoverage:4.7,addedThisMonth:8500,avgMonthlyExpense:40000,
    balances:{UAH:85000,USD:1500,EUR:960},rates:{UAH:1,USD:40.2,EUR:43.8},
    history:[{month:'2025-12',delta:8000,total:98000},{month:'2026-01',delta:14500,total:112500},{month:'2026-02',delta:15700,total:128200},{month:'2026-03',delta:20700,total:148900},{month:'2026-04',delta:30000,total:178900},{month:'2026-05',delta:8500,total:187400}],
    transactions:[{date:new Date().toISOString(),amount:5000,currency:'UAH',type:'Поповнення',who:'Євген',comment:'Відкладено з зарплати'},{date:new Date(Date.now()-864000000).toISOString(),amount:3500,currency:'UAH',type:'Поповнення',who:'Марина',comment:'Економія'}],
  });
  if(page==='goals'){
    const g=getGoals();
    if(!g.length){
      const demo=[{name:'✈️ Відпустка 2026',target:50000,saved:34000,budget:'Сімейний'},{name:'💻 Новий ноутбук',target:50000,saved:21000,budget:'Євген'},{name:'👶 Для Матвійки',target:20000,saved:5000,budget:'Сімейний'}];
      saveGoals(demo);renderGoals(demo);
    } else renderGoals(g);
  }
  if(page==='settings')renderSettingsUI();
  if(page==='analytics'){
    state.dashboard={totalIncome:58500,totalExpense:16940,byCategory:{"Продукти":5680,"Комунальні":3200,"Транспорт":2800,"Ресторани":1960},budgets:{"Сімейний":{expense:7420},"Євген":{expense:8420},"Марина":{expense:1100}}};
    renderAnalytics();
  }
}

// ── MODALS ────────────────────────────────────────────────────────
function openModal(type){
  state.currentType=type||'Витрата';state.currentCurrency='UAH';state.selectedCat='';state.selectedCard='';
  state.modalMember=getMyMember(); // дефолт — поточний юзер
  renderCatGrid();renderCardGrid();updateModalType();updateModalOwner();
  document.getElementById('amount-input').value='';
  document.getElementById('desc-input').value='';
  document.getElementById('currency-btn').innerHTML='UAH <i class="ti ti-chevron-down"></i>';
  document.getElementById('amount-cur-icon').textContent='₴';
  const now=new Date();
  const local=new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,16);
  document.getElementById('datetime-input').value=local;
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.getElementById('modal-add').classList.remove('hidden');
  setTimeout(()=>document.getElementById('amount-input').focus(),100);
}
function updateModalOwner(){
  document.querySelectorAll('.owner-modal-btn').forEach(b=>{
    const isActive=b.dataset.owner===state.modalMember;
    b.style.background=isActive?'var(--c-blue-soft)':'var(--c-bg-3)';
    b.style.color=isActive?'var(--c-blue)':'var(--c-text-2)';
    b.style.borderColor=isActive?'var(--c-blue)':'transparent';
  });
  renderCardGrid(); // перемалюємо картки для нового члена
}
function closeModal(){
  document.getElementById('modal-overlay').classList.add('hidden');
  ['modal-add','modal-reserve','modal-goal','modal-transfer'].forEach(id=>{
    const el=document.getElementById(id);if(el)el.classList.add('hidden');
  });
}
function setType(t){state.currentType=t;updateModalType();}
function updateModalType(){
  const inc=state.currentType==="Дохід";
  document.getElementById('tt-expense').classList.toggle('active',!inc);
  document.getElementById('tt-income').classList.toggle('active',inc);
  document.getElementById('save-btn').textContent=inc?'Зберегти дохід':'Зберегти витрату';
  document.getElementById('save-btn').style.background=inc?'var(--c-green)':'var(--c-red)';
  renderCatGrid();
}
function renderCatGrid(){
  const inc=state.currentType==="Дохід";
  const cats=inc?getIncCats():getExpCats();
  document.getElementById('cat-grid-modal').innerHTML=cats.map(c=>'<div class="cat-cell'+(state.selectedCat===c.id?' selected':'')+'" data-cat="'+esc(c.id)+'"><i class="ti '+c.icon+'"></i><span>'+esc(c.id)+'</span></div>').join('');
  document.querySelectorAll('.cat-cell').forEach(el=>el.addEventListener('click',()=>{state.selectedCat=el.dataset.cat;renderCatGrid();}));
}
function renderCardGrid(){
  const el=document.getElementById('card-grid-modal');if(!el)return;
  const member=state.modalMember||getMyMember();
  const cards=getCards(member);
  el.innerHTML=cards.map(c=>`<div class="cat-cell${state.selectedCard===c.id?' selected':''}" data-card="${esc(c.id)}" style="${state.selectedCard===c.id?'background:'+c.bg+';border-color:'+c.color+';':''}"><i class="ti ${c.icon}" style="color:${state.selectedCard===c.id?c.color:'var(--c-text-2)'}"></i><span>${esc(c.id)}</span></div>`).join('');
  el.querySelectorAll('[data-card]').forEach(el=>el.addEventListener('click',()=>{state.selectedCard=el.dataset.card;renderCardGrid();}));
}
function cycleCurrency(){
  const i=CURRENCIES.indexOf(state.currentCurrency);
  state.currentCurrency=CURRENCIES[(i+1)%CURRENCIES.length];
  document.getElementById('currency-btn').innerHTML=state.currentCurrency+' <i class="ti ti-chevron-down"></i>';
  document.getElementById('amount-cur-icon').textContent=CUR_SYMBOLS[state.currentCurrency];
}
async function submitOperation(){
  const amt=parseFloat(document.getElementById('amount-input').value);
  if(!amt||amt<=0){showToast('Вкажи суму','error');return;}
  if(!state.selectedCat){showToast('Вибери категорію','error');return;}
  const dtVal=document.getElementById('datetime-input').value;
  const dt=dtVal?new Date(dtVal).toISOString():new Date().toISOString();
  const btn=document.getElementById('save-btn');btn.disabled=true;btn.textContent='Збереження...';
  // Закриваємо форму ОДРАЗУ — не чекаємо API
  if(!state.selectedCard){showToast('Вибери рахунок','error');btn.disabled=false;updateModalType();return;}
  const whoName=state.modalMember||getMyMember();
  const body={action:'addOperation',type:state.currentType,category:state.selectedCat,amount:amt,currency:state.currentCurrency,desc:document.getElementById('desc-input').value||'',budget:whoName,date:dt,card:state.selectedCard,who:whoName};
  // 1. Зберігаємо локально і закриваємо форму
  const localOp={...body,date:dt,amountUah:amt,who:whoName,_local:true};
  state.operations.unshift(localOp);
  btn.disabled=false;updateModalType();closeModal();showToast('✅ Збережено!');
  if(state.currentPage==='dashboard'){renderMemberColumns();renderRecentOps(state.operations);}
  else if(state.currentPage==='operations')renderOperations();
  else if(state.currentPage==='calendar')renderCalendar();
  // 2. Фонова відправка на сервер
  if(state.scriptUrl){
    apiPost(body)
      .then(res=>{
        if(res?.row){localOp.row=res.row;delete localOp._local;showSyncStatus('ok');
          if(state.currentPage==='operations')renderOperations();
          else if(state.currentPage==='dashboard')renderRecentOps(state.operations);}
      })
      .catch(()=>{enqueue(body);showSyncStatus('pending');});
  }
}

// Reserve modal
function openReserveModal(){
  state.reserveType='Поповнення';state.reserveCurrency='UAH';
  document.getElementById('res-amount-input').value='';document.getElementById('res-desc-input').value='';
  document.getElementById('res-currency-btn').innerHTML='UAH <i class="ti ti-chevron-down"></i>';
  document.getElementById('rt-add').classList.add('active');document.getElementById('rt-remove').classList.remove('active');
  document.getElementById('res-save-btn').textContent='Зберегти поповнення';
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.getElementById('modal-reserve').classList.remove('hidden');
}
function setReserveType(t){
  state.reserveType=t;
  document.getElementById('rt-add').classList.toggle('active',t==="Поповнення");
  document.getElementById('rt-remove').classList.toggle('active',t==="Зняття");
  document.getElementById('res-save-btn').textContent=t==="Поповнення"?'Зберегти поповнення':'Зберегти зняття';
}
function cycleReserveCurrency(){const i=CURRENCIES.indexOf(state.reserveCurrency);state.reserveCurrency=CURRENCIES[(i+1)%CURRENCIES.length];document.getElementById('res-currency-btn').innerHTML=state.reserveCurrency+' <i class="ti ti-chevron-down"></i>';}
async function submitReserve(){
  const amt=parseFloat(document.getElementById('res-amount-input').value);
  if(!amt||amt<=0){showToast('Вкажи суму','error');return;}
  const btn=document.getElementById('res-save-btn');btn.disabled=true;
  const resBody={action:'addReserve',type:state.reserveType,amount:amt,currency:state.reserveCurrency,comment:document.getElementById('res-desc-input').value||''};
  closeModal();showToast('✅ Збережено!');btn.disabled=false;
  if(state.scriptUrl){
    apiPost(resBody).then(()=>{fetchReserve();showSyncStatus('ok');}).catch(()=>{enqueue(resBody);showSyncStatus('pending');});
  }
}

// Goal modal
function openGoalModal(idx){
  state.editingGoalIdx=idx??-1;
  const isEdit=idx>=0;
  const g=isEdit?getGoals()[idx]:{};
  setText('goal-modal-title',isEdit?'Редагувати ціль':'Нова ціль');
  document.getElementById('goal-name-input').value=g.name||'';
  document.getElementById('goal-target-input').value=g.target||'';
  document.getElementById('goal-saved-input').value=g.saved||'';
  document.getElementById('goal-budget-input').value=g.budget||'Сімейний';
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.getElementById('modal-goal').classList.remove('hidden');
}
function submitGoal(){
  const name=document.getElementById('goal-name-input').value.trim();
  const target=parseFloat(document.getElementById('goal-target-input').value);
  if(!name||!target){showToast('Вкажи назву і суму','error');return;}
  const g=getGoals();
  const deadline=document.getElementById('goal-deadline-input')?.value||null;
  const goal={name,displayName:name,target,saved:parseFloat(document.getElementById('goal-saved-input').value)||0,budget:document.getElementById('goal-budget-input')?.value||'Сімейний',deadline};
  const isNew=state.editingGoalIdx<0;
  if(!isNew)g[state.editingGoalIdx]=goal;else g.push(goal);
  saveGoals(g);closeModal();renderGoals(g);showToast('✅ Збережено!');
  // Додаємо в Sheet якщо нова
  if(isNew&&state.scriptUrl){apiPost({action:'addGoal',...goal}).catch(e=>console.warn('Add goal:',e));}
}

// Transfer modal
// ── ПОВНОЦІННИЙ ПЕРЕКАЗ ──────────────────────────────────────────
function openTransferModal(context){
  // context може бути {fromMember, fromCard} або просто індекс цілі
  let old2=document.getElementById('transfer-full-modal');if(old2)old2.remove();

  const members=FAMILY_MEMBERS;
  const goals=getGoals();
  const profiles=getProfiles();

  // Типи об'єктів
  const accountOpts=members.flatMap(m=>{
    const prof=profiles[m]||{name:m};
    return getCards(m).map(c=>`<option value="member:${esc(m)}:${esc(c.id)}">${esc(prof.name||m)} → ${esc(c.id)}</option>`);
  });
  const reserveOpt='<option value="reserve:">🛡️ Резерв</option>';
  const goalsOpts=goals.map((g,i)=>`<option value="goal:${i}">🎯 ${esc(g.name)}</option>`);
  const allOpts=[...accountOpts,reserveOpt,...goalsOpts].join('');

  const div=document.createElement('div');
  div.id='transfer-full-modal';
  div.style.cssText='position:fixed;inset:0;z-index:600;display:flex;align-items:flex-end;justify-content:center;background:rgba(0,0,0,.5);backdrop-filter:blur(2px);';
  div.innerHTML=`<div style="background:var(--c-card);border-radius:20px 20px 0 0;padding:20px;width:100%;max-width:500px;max-height:85vh;overflow-y:auto;">
    <div style="width:40px;height:4px;background:var(--c-border);border-radius:2px;margin:0 auto 16px;"></div>
    <div style="font-size:17px;font-weight:700;margin-bottom:16px;">🔄 Переказ</div>
    <div class="modal-row"><label class="modal-label">Звідки</label>
      <select id="trf-from" class="desc-input" style="margin-bottom:0">${allOpts}</select></div>
    <div class="modal-row"><label class="modal-label">Куди</label>
      <select id="trf-to" class="desc-input" style="margin-bottom:0">${allOpts}</select></div>
    <div class="modal-row"><label class="modal-label">Сума</label>
      <div style="display:flex;gap:8px;align-items:center;">
        <input id="trf-amount" type="number" class="desc-input" placeholder="0" style="flex:1;margin-bottom:0">
        <button id="trf-currency-btn" style="padding:10px 14px;border-radius:10px;background:var(--c-bg-3);color:var(--c-text);font-weight:700;white-space:nowrap;">UAH</button>
      </div></div>
    <div class="modal-row"><label class="modal-label">Коментар</label>
      <input id="trf-desc" type="text" class="desc-input" placeholder="Опис переказу" style="margin-bottom:0"></div>
    <button id="trf-save-btn" style="width:100%;padding:14px;border-radius:14px;background:var(--c-accent);color:#fff;font-size:15px;font-weight:700;margin-top:6px;">Переказати</button>
  </div>`;
  document.body.appendChild(div);
  div.addEventListener('click',e=>{if(e.target===div)div.remove();});

  let trfCurrency='UAH';
  div.querySelector('#trf-currency-btn').addEventListener('click',()=>{
    const curs=['UAH','USD','EUR'];const i=curs.indexOf(trfCurrency);trfCurrency=curs[(i+1)%curs.length];div.querySelector('#trf-currency-btn').textContent=trfCurrency;
  });

  div.querySelector('#trf-save-btn').addEventListener('click',async()=>{
    const amt=parseFloat(div.querySelector('#trf-amount').value);
    if(!amt||amt<=0){showToast('Вкажи суму','error');return;}
    const fromVal=div.querySelector('#trf-from').value;
    const toVal=div.querySelector('#trf-to').value;
    if(fromVal===toVal){showToast('Оберіть різні рахунки','error');return;}

    const parseTarget=v=>{const[type,...rest]=v.split(':');return{type,id:rest[0]||'',card:rest[1]||''};};
    const from=parseTarget(fromVal);const to=parseTarget(toVal);
    const body={action:'addTransfer',amount:amt,currency:trfCurrency,desc:div.querySelector('#trf-desc').value||'',date:new Date().toISOString()};

    if(from.type==='member'){body.fromWho=from.id;body.fromCard=from.card;}
    if(from.type==='reserve'){body.fromReserve=true;}
    if(from.type==='goal'){/* goal logic local */}
    if(to.type==='member'){body.toWho=to.id;body.toCard=to.card;}
    if(to.type==='reserve'){body.toReserve=true;}

    // Локально
    if(from.type==='member'){state.operations.unshift({type:'Витрата',category:'Переказ',desc:`→ ${to.type==='member'?to.id+' '+to.card:'Резерв'}`,amount:amt,amountUah:amt,currency:trfCurrency,who:from.id,card:from.card,date:new Date().toISOString()});}
    if(to.type==='member'){state.operations.unshift({type:'Дохід',category:'Переказ',desc:`← ${from.type==='member'?from.id+' '+from.card:'Резерв'}`,amount:amt,amountUah:amt,currency:trfCurrency,who:to.id,card:to.card,date:new Date().toISOString()});}
    // Ціль → ціль
    if(from.type==='goal'&&to.type==='goal'){
      const g=getGoals();const fi=parseInt(from.id);const ti=parseInt(to.id);
      if(g[fi]&&g[ti]){g[fi].saved-=amt;g[ti].saved+=amt;saveGoals(g);renderGoals(g);}
    }

    div.remove();renderMemberColumns();renderRecentOps(state.operations);showToast('✅ Переказ записано!');
    if(state.scriptUrl){apiPost(body).then(()=>showSyncStatus('ok')).catch(()=>{enqueue(body);showSyncStatus('pending');});}
  });
}
function submitTransfer(){openTransferModal();}

// ── MONTH/CALENDAR NAV ────────────────────────────────────────────
function updateMonthLabel(){
  const d=state.currentMonth;const lbl=MONTH_UK[d.getMonth()]+' '+d.getFullYear();
  setText('month-label',lbl);setText('greeting-month',lbl);
}
function prevMonth(){state.currentMonth=new Date(state.currentMonth.getFullYear(),state.currentMonth.getMonth()-1,1);updateMonthLabel();loadPageData(state.currentPage);}
function nextMonth(){state.currentMonth=new Date(state.currentMonth.getFullYear(),state.currentMonth.getMonth()+1,1);updateMonthLabel();loadPageData(state.currentPage);}

// ── THEME / SCALE ─────────────────────────────────────────────────
// applyFont removed
// ═══════════════════════════════════════════════════════
// SYNC ENGINE — єдина система синхронізації
// ═══════════════════════════════════════════════════════
const syncState={
  queue:[],          // черга операцій що очікують відправки
  isSyncing:false,
  lastFullSync:null,
  pendingSettings:false,
};
const SYNC_INTERVAL_MS = 30000; // авто-оновлення кожні 30с

// ── ІНІЦІАЛІЗАЦІЯ SYNC ──────────────────────────────────
function initSync(){
  if(!state.scriptUrl)return;
  // 1. При поверненні у вкладку — одразу синк
  document.addEventListener('visibilitychange',()=>{
    if(document.visibilityState==='visible')fullSync();
  });
  // 2. Авто-синк кожні 30 секунд (для синхронізації між Женею і Мариною)
  setInterval(()=>{ if(document.visibilityState==='visible') fullSync(); }, SYNC_INTERVAL_MS);
  // 3. Якщо є відкладені операції в черзі — відправляємо
  flushQueue();
}

// ── ПОВНИЙ SYNC: Sheet → App ────────────────────────────
async function fullSync(silent=true){
  if(!state.scriptUrl||!state.token){showSyncStatus('disconnected');return;}
  if(syncState.isSyncing)return;
  syncState.isSyncing=true;
  if(!silent)showSyncStatus('syncing');
  try{
    // Паралельно тягнемо все
    const [dash, ops, settings, goalsData] = await Promise.all([
      apiGet('dashboard').catch(()=>null),
      apiGet('operations',{month:fmtMonth(state.currentMonth)}).catch(()=>null),
      apiGet('settings').catch(()=>null),
      apiGet('goals').catch(()=>null),
    ]);
    // Очищаємо демо-дані якщо прийшли реальні
    if(ops?.operations) state.operations=state.operations.filter(o=>!o._demo);
    // Цілі
    if(goalsData?.goals?.length){
      localStorage.setItem(APP_CONFIG.GOALS_KEY,JSON.stringify(goalsData.goals));
      state.goals=goalsData.goals;
      if(state.currentPage==='goals')renderGoals(goalsData.goals);
    }

    // Застосовуємо дані
    if(dash){ state.dashboard=dash; renderDashboard(dash); }
    if(ops && ops.operations){
      // Сервер — єдине джерело правди для збережених операцій
      // Локальні pending (без row) додаємо зверху
      const localPending=state.operations.filter(o=>!o.row&&o._local);
      state.operations=[...localPending,...ops.operations];
      if(state.currentPage==='operations')renderOperations();
      if(state.currentPage==='calendar')renderCalendar();
    }
    if(settings) applySettings(settings);

    // Завжди оновлюємо колонки членів після синку
    renderMemberColumns();

    syncState.lastFullSync=new Date();
    localStorage.setItem(APP_CONFIG.LAST_SYNC_KEY, syncState.lastFullSync.toISOString());
    showSyncStatus('ok');

    // Відправляємо відкладені операції
    await flushQueue();

  }catch(e){
    console.warn('Sync error:',e);
    showSyncStatus('error');
  }finally{
    syncState.isSyncing=false;
  }
}

// ── ЗАСТОСОВУЄМО SETTINGS з Sheet → localStorage + UI ──
function applySettings(d){
  if(!d)return;
  let changed=false;
  const setIfNew=(key,val)=>{
    if(!val)return;
    const cur=localStorage.getItem(key);
    const newStr=JSON.stringify(val);
    if(cur!==newStr){localStorage.setItem(key,newStr);changed=true;}
  };
  setIfNew(APP_CONFIG.EXP_CATS_KEY, d.expCats);
  setIfNew(APP_CONFIG.INC_CATS_KEY, d.incCats);
  setIfNew(APP_CONFIG.CARDS_KEY+'_Євген',  d.cardsEvgen);
  setIfNew(APP_CONFIG.CARDS_KEY+'_Марина', d.cardsMarina);

  if(d.profiles){
    const profStr=JSON.stringify(d.profiles);
    if(localStorage.getItem(APP_CONFIG.PROFILES_KEY)!==profStr){
      localStorage.setItem(APP_CONFIG.PROFILES_KEY,profStr);
      changed=true;
      // Застосовуємо профіль поточного юзера
      const member=getMyMember();
      const myProf=d.profiles[member];
      if(myProf){
        if(myProf.name&&myProf.name!==localStorage.getItem(APP_CONFIG.USERNAME_KEY)){
          localStorage.setItem(APP_CONFIG.USERNAME_KEY,myProf.name);
          updateUserUI();
        }
        if(myProf.avatar&&myProf.avatar!==localStorage.getItem(APP_CONFIG.AVATAR_KEY)){
          localStorage.setItem(APP_CONFIG.AVATAR_KEY,myProf.avatar);
          applyAvatar(myProf.avatar);
        }
      }
    }
  }
  if(changed&&state.currentPage==='settings') renderSettingsUI();
}

// ── ЧЕРГА ВІДКЛАДЕНИХ ОПЕРАЦІЙ ──────────────────────────
// Якщо API недоступний — операція іде в чергу і відправляється пізніше
function enqueue(body){
  syncState.queue.push({body,ts:Date.now()});
  saveSyncQueue();
}
function saveSyncQueue(){
  try{sessionStorage.setItem('sync_queue',JSON.stringify(syncState.queue));}catch{}
}
function loadSyncQueue(){
  try{const s=sessionStorage.getItem('sync_queue');if(s)syncState.queue=JSON.parse(s);}catch{}
}
async function flushQueue(){
  if(!state.scriptUrl||!state.token||!syncState.queue.length)return;
  const toSend=[...syncState.queue];
  syncState.queue=[];saveSyncQueue();
  for(const item of toSend){
    try{
      const res=await apiPost(item.body);
      // Якщо отримали row — оновлюємо локальну операцію
      if(res?.row&&item.body.action==='addOperation'){
        const localOp=state.operations.find(o=>!o.row&&o.desc===item.body.desc&&o.amount==item.body.amount);
        if(localOp)localOp.row=res.row;
      }
    }catch(e){
      // Повертаємо в чергу
      syncState.queue.push(item);
      saveSyncQueue();
      console.warn('Queue flush failed:',e);
      break;
    }
  }
  if(syncState.queue.length)showSyncStatus('pending');
}

// ── СТАТУС СИНХРОНІЗАЦІЇ ────────────────────────────────
function showSyncStatus(status){
  const el=document.getElementById('sync-status');if(!el)return;
  const map={
    ok:     {text:'● Синхронізовано '+new Date().toLocaleTimeString('uk-UA',{hour:'2-digit',minute:'2-digit'}), color:'var(--c-green)'},
    syncing:{text:'↻ Синхронізація...', color:'var(--c-accent)'},
    pending:{text:'⏳ Очікує '+syncState.queue.length+' операцій', color:'#f59e0b'},
    error:  {text:'✕ Помилка синку', color:'var(--c-red)'},
    disconnected:{text:'○ Не підключено', color:'var(--c-text-3)'},
  };
  const s=map[status]||map.ok;
  el.textContent=s.text;el.style.color=s.color;
  // Також топбар індикатор
  const dot=document.getElementById('sync-dot');
  if(dot){dot.style.background=status==='ok'?'var(--c-green)':status==='error'?'var(--c-red)':'#f59e0b';}
}

// ── ПУБЛІЧНІ АЛІАСИ (для зворотної сумісності) ──────────
async function syncSettingsToSheet(){
  if(!state.scriptUrl||!state.token){syncState.pendingSettings=true;return;}
  try{
    await apiPost({
      action:'updateSettings',
      expCats:getExpCats(),
      incCats:getIncCats(),
      cardsEvgen:getCards('Євген'),
      cardsMarina:getCards('Марина'),
      profiles:getProfiles(),
    });
    syncState.pendingSettings=false;
  }catch(e){syncState.pendingSettings=true;console.warn('Settings sync:',e);}
}
async function fetchSettingsFromSheet(){ await fullSync(true); }
function applyTheme(t){document.body.setAttribute('data-theme',t);localStorage.setItem(APP_CONFIG.THEME_KEY,t);document.querySelectorAll('.theme-btn').forEach(b=>b.classList.toggle('active',b.dataset.theme===t));}

// ── ICON PICKER ───────────────────────────────────────────────────
function openIconPicker(mode){
  // mode: 'expense' | 'income' | 'card'
  let memberForCard=null;
  if(mode==='card-evgen')memberForCard='Євген';
  else if(mode==='card-marina')memberForCard='Марина';
  const baseMode=mode.startsWith('card')?'card':mode;
  const inputId = baseMode==='card' ? ('new-card'+(memberForCard?'-'+memberForCard.toLowerCase():'')) : (mode==='income' ? 'new-income-cat' : 'new-expense-cat');
  const nameVal = (document.getElementById(inputId)||{}).value||'';
  if(!nameVal.trim()){showToast('Спочатку введи назву','error');return;}

  // Знімаємо старий пікер якщо є
  let old=document.getElementById('icon-picker-modal');if(old)old.remove();

  const colors=[
    {bg:'#E1F5EE',color:'#085041'},{bg:'#FAECE7',color:'#712B13'},{bg:'#E6F1FB',color:'#0C447C'},
    {bg:'#FEF3E2',color:'#633806'},{bg:'#FBEAF0',color:'#72243E'},{bg:'#EEEDFE',color:'#3C3489'},
    {bg:'#F0F4FF',color:'#2D4AB7'},{bg:'#EAF3DE',color:'#27500A'},{bg:'#FAEEDA',color:'#633806'},
    {bg:'#1a1a2e',color:'#ffffff'},{bg:'#F0F0F0',color:'#555555'},
  ];

  let selIcon='ti-dots';
  let selColor=colors[0];

  const div=document.createElement('div');
  div.id='icon-picker-modal';
  div.style.cssText='position:fixed;inset:0;z-index:600;display:flex;align-items:flex-end;justify-content:center;background:rgba(0,0,0,.5);backdrop-filter:blur(2px);';
  div.innerHTML=`
    <div style="background:var(--c-card);border-radius:20px 20px 0 0;padding:20px;width:100%;max-width:500px;max-height:80vh;overflow-y:auto;">
      <div style="width:40px;height:4px;background:var(--c-border);border-radius:2px;margin:0 auto 16px;"></div>
      <div style="font-size:16px;font-weight:700;margin-bottom:14px;">Оберіть іконку</div>
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--c-text-3);margin-bottom:8px;">Іконка</div>
      <div id="ip-icons" style="display:grid;grid-template-columns:repeat(7,1fr);gap:8px;margin-bottom:16px;"></div>
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--c-text-3);margin-bottom:8px;">Колір</div>
      <div id="ip-colors" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px;"></div>
      <button id="ip-save" style="width:100%;padding:14px;border-radius:14px;background:var(--c-accent);color:#fff;font-size:15px;font-weight:700;">Додати</button>
    </div>`;
  document.body.appendChild(div);
  div.addEventListener('click',e=>{if(e.target===div)div.remove();});

  const iconsEl=div.querySelector('#ip-icons');
  const colorsEl=div.querySelector('#ip-colors');

  function renderPicker(){
    iconsEl.innerHTML=ICON_LIST.map(ic=>`<button data-ic="${ic}" style="width:100%;aspect-ratio:1;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px;background:${ic===selIcon?selColor.bg:'var(--c-bg-3)'};border:2px solid ${ic===selIcon?selColor.color:'transparent'};transition:.15s;"><i class="ti ${ic}" style="color:${ic===selIcon?selColor.color:'var(--c-text-2)'}"></i></button>`).join('');
    colorsEl.innerHTML=colors.map((c,i)=>`<button data-cidx="${i}" style="width:32px;height:32px;border-radius:50%;background:${c.bg};border:3px solid ${c===selColor?c.color:'transparent'};transition:.15s;"></button>`).join('');
    iconsEl.querySelectorAll('[data-ic]').forEach(b=>b.addEventListener('click',()=>{selIcon=b.dataset.ic;renderPicker();}));
    colorsEl.querySelectorAll('[data-cidx]').forEach(b=>b.addEventListener('click',()=>{selColor=colors[parseInt(b.dataset.cidx)];renderPicker();}));
  }
  renderPicker();

  div.querySelector('#ip-save').addEventListener('click',()=>{
    const name=nameVal.trim();
    const item={id:name,icon:selIcon,bg:selColor.bg,color:selColor.color};
    if(mode==='expense'){const list=getExpCats();list.push(item);localStorage.setItem(APP_CONFIG.EXP_CATS_KEY,JSON.stringify(list));syncSettingsToSheet();}
    else if(mode==='income'){const list=getIncCats();list.push(item);localStorage.setItem(APP_CONFIG.INC_CATS_KEY,JSON.stringify(list));syncSettingsToSheet();}
    else if(baseMode==='card'){saveCards([...getCards(memberForCard),item],memberForCard);renderMemberColumns();renderSettingsUI();}
    const inp=document.getElementById(inputId);if(inp)inp.value='';
    renderSettingsUI();div.remove();showToast('✅ Додано!');
  });
}

// ── FAB MENU ─────────────────────────────────────────────────────
function openFabMenu(){
  let old2=document.getElementById('fab-menu');if(old2){old2.remove();return;}
  const div=document.createElement('div');
  div.id='fab-menu';
  div.style.cssText='position:fixed;bottom:90px;right:16px;z-index:400;display:flex;flex-direction:column;gap:10px;align-items:flex-end;';
  const items=[
    {icon:'ti-plus',label:'Витрата / Дохід',bg:'var(--c-accent)',action:()=>{div.remove();openModal();}},
    {icon:'ti-arrows-exchange',label:'Переказ',bg:'var(--c-blue)',action:()=>{div.remove();openTransferModal();}},
    {icon:'ti-shield',label:'Резерв',bg:'#27500A',action:()=>{div.remove();openReserveModal();}},
    {icon:'ti-target',label:'Ціль',bg:'var(--c-pink)',action:()=>{div.remove();openGoalModal();}},
  ];
  div.innerHTML=items.map((it,i)=>`
    <div class="fab-menu-item" data-idx="${i}" style="display:flex;align-items:center;gap:10px;animation:slideUp .2s ${i*0.05}s both;">
      <span style="background:var(--c-card);border:.5px solid var(--c-border);padding:6px 12px;border-radius:20px;font-size:13px;font-weight:600;color:var(--c-text);white-space:nowrap;box-shadow:var(--shadow);">${it.label}</span>
      <div style="width:44px;height:44px;border-radius:50%;background:${it.bg};display:flex;align-items:center;justify-content:center;box-shadow:0 4px 12px rgba(0,0,0,.25);cursor:pointer;"><i class="ti ${it.icon}" style="color:#fff;font-size:20px;"></i></div>
    </div>`).join('');
  document.body.appendChild(div);

  items.forEach((it,i)=>{div.querySelectorAll('.fab-menu-item')[i].addEventListener('click',it.action);});

  // Клік поза меню — закрити
  setTimeout(()=>document.addEventListener('click',function closeFab(e){if(!div.contains(e.target)&&e.target.id!=='fab'){div.remove();document.removeEventListener('click',closeFab);}},true),100);
}

// ── SIDEBAR ───────────────────────────────────────────────────────
function openSidebar(){document.getElementById('sidebar').classList.add('open');let ov=document.getElementById('sb-ov');if(!ov){ov=document.createElement('div');ov.id='sb-ov';ov.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:99;';ov.onclick=closeSidebar;document.body.appendChild(ov);}ov.style.display='block';}
function closeSidebar(){document.getElementById('sidebar').classList.remove('open');const ov=document.getElementById('sb-ov');if(ov)ov.style.display='none';}

function setScriptUrl(){
  const u=prompt('URL Google Apps Script Web App:',state.scriptUrl);
  if(u!==null){state.scriptUrl=u.trim();localStorage.setItem(APP_CONFIG.SCRIPT_URL_KEY,state.scriptUrl);renderSettingsUI();if(state.scriptUrl){loadFx();fetchDashboard();}}
}

// ── BIND EVENTS ───────────────────────────────────────────────────
function bindEvents(){
  // Navigation
  document.querySelectorAll('[data-page]').forEach(el=>el.addEventListener('click',e=>{e.preventDefault();navigateTo(el.dataset.page);}));
  document.getElementById('menu-btn').addEventListener('click',openSidebar);
  document.getElementById('month-prev').addEventListener('click',prevMonth);
  document.getElementById('month-next').addEventListener('click',nextMonth);
  // Calendar nav
  document.getElementById('cal-prev').addEventListener('click',()=>{state.calMonth=new Date(state.calMonth.getFullYear(),state.calMonth.getMonth()-1,1);renderCalendar();});
  document.getElementById('cal-next').addEventListener('click',()=>{state.calMonth=new Date(state.calMonth.getFullYear(),state.calMonth.getMonth()+1,1);renderCalendar();});
  document.querySelectorAll('.cal-period-btn').forEach(b=>b.addEventListener('click',()=>{
    document.querySelectorAll('.cal-period-btn').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');state.calPeriod=b.dataset.period;renderCalendar();
  }));
  // FAB & add buttons
  document.getElementById('fab').addEventListener('click',openFabMenu);
  document.getElementById('add-btn-dash').addEventListener('click',()=>openModal());
  const aob=document.getElementById('add-btn-ops');if(aob)aob.addEventListener('click',()=>openModal());
  document.getElementById('add-reserve-btn').addEventListener('click',openReserveModal);
  const agoal=document.getElementById('add-goal-btn');if(agoal)agoal.addEventListener('click',()=>openGoalModal());
  document.getElementById('modal-overlay').addEventListener('click',closeModal);
  // Type toggles
  document.getElementById('tt-expense').addEventListener('click',()=>setType('Витрата'));
  document.getElementById('tt-income').addEventListener('click',()=>setType('Дохід'));
  document.getElementById('rt-add').addEventListener('click',()=>setReserveType('Поповнення'));
  document.getElementById('rt-remove').addEventListener('click',()=>setReserveType('Зняття'));
  // Currency
  document.getElementById('currency-btn').addEventListener('click',cycleCurrency);
  document.getElementById('res-currency-btn').addEventListener('click',cycleReserveCurrency);
  // Save buttons
  document.getElementById('save-btn').addEventListener('click',submitOperation);
  // Owner buttons in modal
  document.querySelectorAll('.owner-modal-btn').forEach(b=>{
    b.addEventListener('click',()=>{
      state.modalMember=b.dataset.owner;
      state.selectedCard=''; // скидаємо картку при зміні члена
      updateModalOwner();
    });
  });
  document.getElementById('res-save-btn').addEventListener('click',submitReserve);
  document.getElementById('goal-save-btn').addEventListener('click',submitGoal);
  document.getElementById('transfer-save-btn').addEventListener('click',submitTransfer);
  // Theme & scale
  document.querySelectorAll('.theme-btn').forEach(b=>b.addEventListener('click',()=>applyTheme(b.dataset.theme)));
  document.querySelectorAll('.scale-btn').forEach(b=>b.addEventListener('click',()=>applyScale(b.dataset.scale)));
  // Category tabs
  document.querySelectorAll('.cat-tab').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const tab=btn.dataset.tab;
      document.querySelectorAll('.cat-tab').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('.cat-panel').forEach(p=>p.classList.remove('active'));
      const panel=document.getElementById('panel-'+tab);
      if(panel)panel.classList.add('active');
    });
  });
  // Member cards tabs
  document.querySelectorAll('.mc-tab').forEach(btn=>{
    btn.addEventListener('click',()=>{
      document.querySelectorAll('.mc-tab').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('.mc-panel').forEach(p=>p.classList.remove('active'));
      const panel=document.getElementById('mc-panel-'+btn.dataset.mctab);
      if(panel)panel.classList.add('active');
    });
  });
  // Settings
  document.getElementById('logout-btn').addEventListener('click',logout);
  document.getElementById('set-url-btn').addEventListener('click',setScriptUrl);
  const syncNow=document.getElementById('sync-now-btn');
  if(syncNow)syncNow.addEventListener('click',async()=>{showToast('🔄 Синхронізація...');await fullSync(false);showToast('✅ Синхронізовано!');});
  // Family name
  document.getElementById('save-family-btn').addEventListener('click',()=>{
    const v=document.getElementById('family-name-input').value.trim();
    if(!v)return;localStorage.setItem(APP_CONFIG.FAMILY_KEY,v);setText('sb-family-name',v);showToast('✅ Збережено!');
  });
  // Username
  document.getElementById('settings-name-input').addEventListener('change',e=>{
    const v=e.target.value.trim();if(!v)return;
    localStorage.setItem(APP_CONFIG.USERNAME_KEY,v);
    const ini=getInitials(v);setText('sb-avatar',ini);setText('sb-user-name',v);setText('topbar-av-text',ini);setText('greeting-text',getGreeting(v));
    const pp=document.getElementById('profile-av-placeholder');if(pp)pp.textContent=ini;
    // Зберігаємо в профіль і синхронізуємо
    const member=getMyMember();const profs=getProfiles();
    profs[member]=profs[member]||{};profs[member].name=v;
    saveProfiles(profs);
  });
  // Avatar upload
  document.getElementById('profile-av-upload').addEventListener('click',()=>document.getElementById('avatar-file-input').click());
  document.getElementById('avatar-file-input').addEventListener('change',e=>{
    const file=e.target.files[0];if(!file)return;
    const reader=new FileReader();
    reader.onload=ev=>{
      const url=ev.target.result;
      localStorage.setItem(APP_CONFIG.AVATAR_KEY,url);applyAvatar(url);
      // Зберігаємо в профіль і синхронізуємо
      const member=getMyMember();const profs=getProfiles();
      profs[member]=profs[member]||{};profs[member].avatar=url;
      saveProfiles(profs);showToast('✅ Аватар збережено!');
    };
    reader.readAsDataURL(file);
  });
  // Mono tokens
  document.getElementById('save-mono-evgen').addEventListener('click',()=>{
    const v=document.getElementById('mono-token-evgen').value.trim();
    localStorage.setItem(APP_CONFIG.MONO_EVGEN_KEY,v);showToast('✅ Токен збережено!');
  });
  document.getElementById('save-mono-marina').addEventListener('click',()=>{
    const v=document.getElementById('mono-token-marina').value.trim();
    localStorage.setItem(APP_CONFIG.MONO_MARINA_KEY,v);showToast('✅ Токен збережено!');
  });
  document.getElementById('import-mono-btn').addEventListener('click',async()=>{
    if(!state.scriptUrl){showToast('Спочатку налаштуй URL скрипта','error');return;}
    showToast('🔄 Імпортую...');
    try{await apiPost({action:'importMono'});showToast('✅ Імпорт завершено!');fetchOperations();}
    catch(e){showToast('Помилка імпорту','error');}
  });
  // Add categories
  document.getElementById('add-expense-cat').addEventListener('click',()=>openIconPicker('expense'));
  document.getElementById('add-income-cat').addEventListener('click',()=>openIconPicker('income'));
  const acE=document.getElementById('add-card-evgen');if(acE)acE.addEventListener('click',()=>openIconPicker('card-evgen'));
  const acM=document.getElementById('add-card-marina');if(acM)acM.addEventListener('click',()=>openIconPicker('card-marina'));
  // Кнопка ручної синхронізації
  const syncBtn=document.getElementById('sync-now-btn');
  if(syncBtn)syncBtn.addEventListener('click',()=>{fetchSettingsFromSheet();loadFx();loadPageData(state.currentPage);showToast('🔄 Синхронізація...');});
  // Filters
  document.querySelectorAll('.filter-pill').forEach(b=>b.addEventListener('click',()=>{
    document.querySelectorAll('.filter-pill').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');state.filterActive=b.dataset.filter;renderOperations();
  }));
  // Keyboard
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
  updateMonthLabel();
}
