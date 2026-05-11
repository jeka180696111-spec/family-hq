'use strict';
const APP_CONFIG={GOOGLE_CLIENT_ID:'650414957833-s37phqum36bfomv5sr5n2cm4tau55ng5.apps.googleusercontent.com',SCRIPT_URL_KEY:'budget_script_url',TOKEN_KEY:'budget_google_token',USER_KEY:'budget_user',THEME_KEY:'budget_theme',SCALE_KEY:'budget_scale',AVATAR_KEY:'budget_avatar',USERNAME_KEY:'budget_username',FAMILY_KEY:'budget_family',GOALS_KEY:'budget_goals',EXP_CATS_KEY:'budget_exp_cats',INC_CATS_KEY:'budget_inc_cats',MONO_EVGEN_KEY:'budget_mono_evgen',MONO_MARINA_KEY:'budget_mono_marina'};
const state={user:null,token:null,scriptUrl:'',currentPage:'dashboard',currentMonth:new Date(),calMonth:new Date(),currentType:'Витрата',currentCurrency:'UAH',reserveType:'Поповнення',reserveCurrency:'UAH',selectedCat:'',dashboard:null,reserve:null,operations:[],goals:[],fx:null,filterActive:'all',editingGoalIdx:-1};
const CURRENCIES=['UAH','USD','EUR'],CUR_SYMBOLS={UAH:'₴',USD:'$',EUR:'€'};
const MONTH_UK=['Січень','Лютий','Березень','Квітень','Травень','Червень','Липень','Серпень','Вересень','Жовтень','Листопад','Грудень'];
const DEFAULT_EXP_CATS=[{id:'Продукти',icon:'ti-shopping-cart',bg:'#E1F5EE',color:'#085041'},{id:'Транспорт',icon:'ti-car',bg:'#FAECE7',color:'#712B13'},{id:'Комунальні',icon:'ti-home',bg:'#E6F1FB',color:'#0C447C'},{id:'Ресторани',icon:'ti-tools-kitchen-2',bg:'#FEF3E2',color:'#633806'},{id:"Здоров'я",icon:'ti-heart',bg:'#FBEAF0',color:'#72243E'},{id:'Одяг',icon:'ti-shirt',bg:'#EEEDFE',color:'#3C3489'},{id:'Розваги',icon:'ti-device-gamepad-2',bg:'#F0F4FF',color:'#2D4AB7'},{id:'Дім',icon:'ti-sofa',bg:'#E6F1FB',color:'#0C447C'},{id:'Дитячі',icon:'ti-baby-carriage',bg:'#FBEAF0',color:'#72243E'},{id:'Інше',icon:'ti-dots',bg:'#F0F0F0',color:'#555'}];
const DEFAULT_INC_CATS=[{id:'Зарплата',icon:'ti-briefcase',bg:'#EAF3DE',color:'#27500A'},{id:'Підробіток',icon:'ti-coin',bg:'#FEF3E2',color:'#633806'},{id:'Інше',icon:'ti-dots',bg:'#F0F0F0',color:'#555'}];
// ── HELPERS ──────────────────────────────────────────────────────
function getExpCats(){try{const s=localStorage.getItem(APP_CONFIG.EXP_CATS_KEY);return s?JSON.parse(s):DEFAULT_EXP_CATS;}catch{return DEFAULT_EXP_CATS;}}
function getIncCats(){try{const s=localStorage.getItem(APP_CONFIG.INC_CATS_KEY);return s?JSON.parse(s):DEFAULT_INC_CATS;}catch{return DEFAULT_INC_CATS;}}
function getCat(id){return [...getExpCats(),...getIncCats()].find(c=>c.id===id)||{id,icon:'ti-dots',bg:'#F0F0F0',color:'#555'};}
function getGoals(){try{const s=localStorage.getItem(APP_CONFIG.GOALS_KEY);return s?JSON.parse(s):[];}catch{return[];}}
function saveGoals(g){localStorage.setItem(APP_CONFIG.GOALS_KEY,JSON.stringify(g));}
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
  const scale=localStorage.getItem(APP_CONFIG.SCALE_KEY)||'1.0';
  state.scriptUrl=localStorage.getItem(APP_CONFIG.SCRIPT_URL_KEY)||'';
  applyTheme(theme);applyScale(scale);
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
  const titles={dashboard:'Дашборд',operations:'Операції',calendar:'Календар',analytics:'Аналіз',reserve:'Резерв',goals:'Цілі',settings:'Налаштування'};
  setText('topbar-title',titles[page]||page);
  loadPageData(page);closeSidebar();
}
function loadPageData(page){
  if(!state.scriptUrl){renderDemoData(page);return;}
  if(page==='dashboard')fetchDashboard();
  else if(page==='operations')fetchOperations();
  else if(page==='calendar')renderCalendar();
  else if(page==='analytics')fetchDashboard().then(()=>renderAnalytics());
  else if(page==='reserve')fetchReserve();
  else if(page==='goals'){renderGoals(getGoals());}
  else if(page==='settings')renderSettingsUI();
}

// ── API ───────────────────────────────────────────────────────────
async function apiGet(action,params={}){
  if(!state.scriptUrl)return null;
  const url=new URL(state.scriptUrl);
  url.searchParams.set('action',action);url.searchParams.set('token',state.token||'');
  Object.entries(params).forEach(([k,v])=>url.searchParams.set(k,v));
  const r=await fetch(url.toString());if(!r.ok)throw new Error('API '+r.status);return r.json();
}
async function apiPost(body){
  if(!state.scriptUrl)return null;
  const r=await fetch(state.scriptUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,token:state.token})});
  if(!r.ok)throw new Error('API '+r.status);return r.json();
}
async function fetchDashboard(){try{const d=await apiGet('dashboard',{month:fmtMonth(state.currentMonth)});if(d){state.dashboard=d;renderDashboard(d);}}catch(e){console.error(e);renderDemoData('dashboard');}}
async function fetchOperations(){try{const d=await apiGet('operations',{month:fmtMonth(state.currentMonth)});if(d){state.operations=d.operations||[];renderOperations();renderCalendar();}}catch(e){console.error(e);}}
async function fetchReserve(){try{const d=await apiGet('reserve');if(d){state.reserve=d;renderReserve(d);}}catch(e){console.error(e);renderDemoData('reserve');}}
async function loadFx(){try{const d=state.scriptUrl?await apiGet('fx'):null;if(d){state.fx=d;setText('fx-usd',d.USD?.mid?.toFixed(2)+' ₴');setText('fx-eur',d.EUR?.mid?.toFixed(2)+' ₴');}}catch(e){}}

// ── RENDER DASHBOARD ─────────────────────────────────────────────
function renderDashboard(d){
  setText('dash-income',fmtMoney(d.totalIncome,'UAH'));
  setText('dash-expense',fmtMoney(d.totalExpense,'UAH'));
  setText('dash-balance',fmtMoney(d.balance,'UAH'));
  setText('dash-savings-rate','Накопичення '+(d.savingsRate||0).toFixed(0)+'%');
  setText('bud-family',fmtMoney(d.budgets?.["Сімейний"]?.balance,"UAH"));
  setText('bud-evgen',fmtMoney(d.budgets?.["Євген"]?.balance,"UAH"));
  setText('bud-marina',fmtMoney(d.budgets?.["Марина"]?.balance,"UAH"));
  renderRecentOps(d.recent||[]);
  renderCatBars("cat-bars",d.byCategory||{},d.totalExpense);
  renderDailyChart(d.byDay||{});
  updateMonthLabel();
}
function renderRecentOps(ops){
  const el=document.getElementById('recent-list');
  if(!ops.length){el.innerHTML='<div style="padding:16px;text-align:center;color:var(--c-text-3);font-size:13px">Операцій немає</div>';return;}
  el.innerHTML=ops.slice(0,6).map(txItem).join('');
}
function txItem(op){
  const cat=getCat(op.category);const plus=op.type==="Дохід";
  return '<div class="tx-item"><div class="tx-icon" style="background:'+cat.bg+'"><i class="ti '+cat.icon+'" style="color:'+cat.color+'"></i></div><div class="tx-info"><div class="tx-name">'+esc(op.desc||op.category)+'</div><div class="tx-meta">'+esc(op.category)+' · '+esc(op.who||'')+' · '+fmtDate(op.date)+'</div></div><div class="tx-amount '+(plus?'plus':'minus')+'">'+(plus?'+':'−')+fmtMoney(op.amount,op.currency)+'</div></div>';
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
  if(state.filterActive!=="all")ops=ops.filter(o=>o.type===state.filterActive||o.budget===state.filterActive);
  if(!ops.length){el.innerHTML='<div style="padding:20px;text-align:center;color:var(--c-text-3)">Немає операцій</div>';return;}
  el.innerHTML=ops.map(txItem).join('');
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
function renderCalendar(){
  const d=state.calMonth;
  const y=d.getFullYear(),m=d.getMonth();
  setText('cal-month-label',MONTH_UK[m]+' '+y);
  const firstDay=(new Date(y,m,1).getDay()+6)%7; // Mon=0
  const daysInMonth=new Date(y,m+1,0).getDate();
  const ops=state.operations.filter(o=>{
    const od=new Date(o.date);return od.getFullYear()===y&&od.getMonth()===m&&o.type==="Витрата";
  });
  const byDay={};
  ops.forEach(o=>{const day=new Date(o.date).getDate();byDay[day]=(byDay[day]||0)+(o.amountUah||o.amount);});
  const today=new Date();
  const headers=['Пн','Вт','Ср','Чт','Пт','Сб','Нд'];
  let html=headers.map(h=>'<div class="cal-header">'+h+'</div>').join('');
  for(let i=0;i<firstDay;i++)html+='<div class="cal-day empty"></div>';
  for(let day=1;day<=daysInMonth;day++){
    const amt=byDay[day]||0;
    const isToday=today.getDate()===day&&today.getMonth()===m&&today.getFullYear()===y;
    html+='<div class="cal-day'+(isToday?' today':'')+'" data-day="'+day+'"><div class="cal-day-num">'+day+'</div>'+(amt>0?'<div class="cal-day-amt">'+fmtMoney(amt,"UAH")+'</div>':'')+'</div>';
  }
  document.getElementById('cal-grid').innerHTML=html;
  updateCalKPI();
  document.querySelectorAll('.cal-day[data-day]').forEach(el=>{
    el.addEventListener('click',()=>{
      document.querySelectorAll('.cal-day').forEach(x=>x.classList.remove('selected'));
      el.classList.add('selected');
      showCalDay(parseInt(el.dataset.day),m,y);
    });
  });
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
    return '<div class="goal-card"><div class="goal-card-head"><div class="goal-icon" style="background:var(--c-blue-soft)"><i class="ti ti-target" style="color:var(--c-blue)"></i></div><div style="flex:1"><div class="goal-name">'+esc(g.name)+'</div><div class="goal-budget">'+esc(g.budget||'Сімейний')+'</div></div><div class="goal-pct">'+pct+'%</div></div><div class="goal-progress-wrap"><div class="goal-progress-fill" style="width:'+pct+'%"></div></div><div class="goal-footer"><span class="goal-saved">'+fmtMoney(g.saved,'UAH')+'</span><span class="goal-remaining">з '+fmtMoney(g.target,'UAH')+'</span></div><div class="goal-actions"><button class="goal-action-btn goal-transfer-btn" data-idx="'+i+'">⇄ Переказ</button><button class="goal-action-btn goal-delete-btn" data-del="'+i+'">✕ Видалити</button></div></div>';
  }).join('');
  document.querySelectorAll('.goal-transfer-btn').forEach(b=>{
    b.addEventListener('click',()=>openTransferModal(parseInt(b.dataset.idx)));
  });
  document.querySelectorAll('.goal-delete-btn').forEach(b=>{
    b.addEventListener('click',()=>{
      if(!confirm('Видалити ціль?'))return;
      const g=getGoals();g.splice(parseInt(b.dataset.del),1);saveGoals(g);renderGoals(g);showToast('Ціль видалено');
    });
  });
}

// ── RENDER SETTINGS ───────────────────────────────────────────────
function renderSettingsUI(){
  const el=document.getElementById('script-url-preview');
  el.textContent=state.scriptUrl?state.scriptUrl.substring(0,50)+'…':'Не налаштовано';
  const ss=document.getElementById('sync-status');
  ss.textContent=state.scriptUrl?'● Підключено':'○ Не підключено';
  ss.style.color=state.scriptUrl?'var(--c-green)':'var(--c-red)';
  renderCatsList('expense-cats-list',getExpCats(),false);
  renderCatsList('income-cats-list',getIncCats(),true);
}
function renderCatsList(containerId,cats,isIncome){
  const el=document.getElementById(containerId);if(!el)return;
  el.innerHTML=cats.map((c,i)=>'<div class="cat-accordion-item"><div class="cat-bar-icon" style="background:'+c.bg+'"><i class="ti '+c.icon+'" style="color:'+c.color+'"></i></div><div class="cat-accordion-name">'+esc(c.id)+'</div><button class="cat-del-btn" data-idx="'+i+'" data-inc="'+isIncome+'"><i class="ti ti-x"></i></button></div>').join('');
  el.querySelectorAll('.cat-del-btn').forEach(b=>{
    b.addEventListener('click',()=>{
      const inc=b.dataset.inc==='true';
      const key=inc?APP_CONFIG.INC_CATS_KEY:APP_CONFIG.EXP_CATS_KEY;
      const cats=inc?getIncCats():getExpCats();
      cats.splice(parseInt(b.dataset.idx),1);
      localStorage.setItem(key,JSON.stringify(cats));
      renderSettingsUI();showToast('Категорію видалено');
    });
  });
}

// ── DEMO DATA ─────────────────────────────────────────────────────
function renderDemoData(page){
  if(page==='dashboard'){
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
  state.currentType=type||'Витрата';state.currentCurrency='UAH';state.selectedCat='';
  renderCatGrid();updateModalType();
  document.getElementById('amount-input').value='';
  document.getElementById('desc-input').value='';
  document.getElementById('currency-btn').innerHTML='UAH <i class="ti ti-chevron-down"></i>';
  document.getElementById('amount-cur-icon').textContent='₴';
  // Set current datetime
  const now=new Date();
  const local=new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,16);
  document.getElementById('datetime-input').value=local;
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.getElementById('modal-add').classList.remove('hidden');
  setTimeout(()=>document.getElementById('amount-input').focus(),100);
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
  try{
    const body={action:'addOperation',type:state.currentType,category:state.selectedCat,amount:amt,currency:state.currentCurrency,desc:document.getElementById('desc-input').value||'',budget:'Сімейний',date:dt};
    if(state.scriptUrl)await apiPost(body);
    // Also store locally for calendar
    state.operations.unshift({...body,date:dt,amountUah:amt,who:localStorage.getItem(APP_CONFIG.USERNAME_KEY)||state.user?.name||'Я'});
    closeModal();showToast('✅ Збережено!');
    if(state.currentPage==='dashboard')fetchDashboard();
    else if(state.currentPage==='operations')renderOperations();
    else if(state.currentPage==='calendar')renderCalendar();
  }catch(e){showToast('Помилка збереження','error');}
  finally{btn.disabled=false;updateModalType();}
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
  try{if(state.scriptUrl)await apiPost({action:'addReserve',type:state.reserveType,amount:amt,currency:state.reserveCurrency,comment:document.getElementById('res-desc-input').value||''});closeModal();showToast('✅ Збережено!');fetchReserve();}
  catch(e){showToast('Помилка','error');}finally{btn.disabled=false;}
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
  const goal={name,target,saved:parseFloat(document.getElementById('goal-saved-input').value)||0,budget:document.getElementById('goal-budget-input').value||'Сімейний'};
  if(state.editingGoalIdx>=0)g[state.editingGoalIdx]=goal;else g.push(goal);
  saveGoals(g);closeModal();renderGoals(g);showToast('✅ Збережено!');
}

// Transfer modal
function openTransferModal(fromIdx){
  const goals=getGoals();
  const fromSel=document.getElementById('transfer-from');
  const toSel=document.getElementById('transfer-to');
  fromSel.innerHTML=goals.map((g,i)=>'<option value="'+i+'"'+(i===fromIdx?' selected':'')+'>'+esc(g.name)+' ('+fmtMoney(g.saved,'UAH')+')</option>').join('');
  toSel.innerHTML=goals.map((g,i)=>'<option value="'+i+'"'+(i!==(fromIdx)&&i===0?' selected':'')+'>'+esc(g.name)+'</option>').join('');
  document.getElementById('transfer-amount').value='';
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.getElementById('modal-transfer').classList.remove('hidden');
}
function submitTransfer(){
  const amt=parseFloat(document.getElementById('transfer-amount').value);
  const fi=parseInt(document.getElementById('transfer-from').value);
  const ti=parseInt(document.getElementById('transfer-to').value);
  if(!amt||amt<=0){showToast('Вкажи суму','error');return;}
  if(fi===ti){showToast('Оберіть різні цілі','error');return;}
  const g=getGoals();
  if(g[fi].saved<amt){showToast('Недостатньо коштів','error');return;}
  g[fi].saved-=amt;g[ti].saved+=amt;
  saveGoals(g);closeModal();renderGoals(g);showToast('✅ Переказано!');
}

// ── MONTH/CALENDAR NAV ────────────────────────────────────────────
function updateMonthLabel(){
  const d=state.currentMonth;const lbl=MONTH_UK[d.getMonth()]+' '+d.getFullYear();
  setText('month-label',lbl);setText('greeting-month',lbl);
}
function prevMonth(){state.currentMonth=new Date(state.currentMonth.getFullYear(),state.currentMonth.getMonth()-1,1);updateMonthLabel();loadPageData(state.currentPage);}
function nextMonth(){state.currentMonth=new Date(state.currentMonth.getFullYear(),state.currentMonth.getMonth()+1,1);updateMonthLabel();loadPageData(state.currentPage);}

// ── THEME / SCALE ─────────────────────────────────────────────────
function applyTheme(t){document.body.setAttribute('data-theme',t);localStorage.setItem(APP_CONFIG.THEME_KEY,t);document.querySelectorAll('.theme-btn').forEach(b=>b.classList.toggle('active',b.dataset.theme===t));}
function applyScale(s){document.documentElement.style.fontSize=(16*parseFloat(s))+'px';localStorage.setItem(APP_CONFIG.SCALE_KEY,s);document.querySelectorAll('.scale-btn').forEach(b=>b.classList.toggle('active',b.dataset.scale===s));}

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
  // FAB & add buttons
  document.getElementById('fab').addEventListener('click',()=>openModal());
  document.getElementById('add-btn-dash').addEventListener('click',()=>openModal());
  const aob=document.getElementById('add-btn-ops');if(aob)aob.addEventListener('click',()=>openModal());
  document.getElementById('add-reserve-btn').addEventListener('click',openReserveModal);
  document.getElementById('add-goal-btn').addEventListener('click',()=>openGoalModal());
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
  document.getElementById('res-save-btn').addEventListener('click',submitReserve);
  document.getElementById('goal-save-btn').addEventListener('click',submitGoal);
  document.getElementById('transfer-save-btn').addEventListener('click',submitTransfer);
  // Theme & scale
  document.querySelectorAll('.theme-btn').forEach(b=>b.addEventListener('click',()=>applyTheme(b.dataset.theme)));
  document.querySelectorAll('.scale-btn').forEach(b=>b.addEventListener('click',()=>applyScale(b.dataset.scale)));
  // Settings
  document.getElementById('logout-btn').addEventListener('click',logout);
  document.getElementById('set-url-btn').addEventListener('click',setScriptUrl);
  document.getElementById('sync-now-btn').addEventListener('click',()=>{loadFx();loadPageData(state.currentPage);showToast('🔄 Синхронізація...');});
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
  });
  // Avatar upload
  document.getElementById('profile-av-upload').addEventListener('click',()=>document.getElementById('avatar-file-input').click());
  document.getElementById('avatar-file-input').addEventListener('change',e=>{
    const file=e.target.files[0];if(!file)return;
    const reader=new FileReader();
    reader.onload=ev=>{const url=ev.target.result;localStorage.setItem(APP_CONFIG.AVATAR_KEY,url);applyAvatar(url);showToast('✅ Аватар збережено!');};
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
  document.getElementById('add-expense-cat').addEventListener('click',()=>{
    const v=document.getElementById('new-expense-cat').value.trim();if(!v)return;
    const cats=getExpCats();cats.push({id:v,icon:'ti-dots',bg:'#F0F0F0',color:'#555'});
    localStorage.setItem(APP_CONFIG.EXP_CATS_KEY,JSON.stringify(cats));
    document.getElementById('new-expense-cat').value='';renderSettingsUI();showToast('✅ Додано!');
  });
  document.getElementById('add-income-cat').addEventListener('click',()=>{
    const v=document.getElementById('new-income-cat').value.trim();if(!v)return;
    const cats=getIncCats();cats.push({id:v,icon:'ti-dots',bg:'#F0F0F0',color:'#555'});
    localStorage.setItem(APP_CONFIG.INC_CATS_KEY,JSON.stringify(cats));
    document.getElementById('new-income-cat').value='';renderSettingsUI();showToast('✅ Додано!');
  });
  // Filters
  document.querySelectorAll('.filter-pill').forEach(b=>b.addEventListener('click',()=>{
    document.querySelectorAll('.filter-pill').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');state.filterActive=b.dataset.filter;renderOperations();
  }));
  // Keyboard
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
  updateMonthLabel();
}
