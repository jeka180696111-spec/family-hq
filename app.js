'use strict';
const APP_CONFIG={GOOGLE_CLIENT_ID:'650414957833-s37phqum36bfomv5sr5n2cm4tau55ng5.apps.googleusercontent.com',SCRIPT_URL_KEY:'budget_script_url',TOKEN_KEY:'budget_google_token',USER_KEY:'budget_user',THEME_KEY:'budget_theme',SCALE_KEY:'budget_scale'};
const state={user:null,token:null,scriptUrl:'',currentPage:'dashboard',currentMonth:new Date(),currentType:'Витрата',currentCurrency:'UAH',reserveType:'Поповнення',reserveCurrency:'UAH',selectedCat:'',dashboard:null,reserve:null,operations:[],goals:[],fx:null,filterActive:'all'};
const CURRENCIES=['UAH','USD','EUR'];
const CUR_SYMBOLS={UAH:'₴',USD:'$',EUR:'€'};
const MONTH_UK=['Січень','Лютий','Березень','Квітень','Травень','Червень','Липень','Серпень','Вересень','Жовтень','Листопад','Грудень'];
const CATEGORIES=[{id:'Продукти',icon:'ti-shopping-cart',bg:'#E1F5EE',color:'#085041'},{id:'Транспорт',icon:'ti-car',bg:'#FAECE7',color:'#712B13'},{id:'Комунальні',icon:'ti-home',bg:'#E6F1FB',color:'#0C447C'},{id:'Ресторани',icon:'ti-tools-kitchen-2',bg:'#FEF3E2',color:'#633806'},{id:"Здоров'я",icon:'ti-heart',bg:'#FBEAF0',color:'#72243E'},{id:'Одяг',icon:'ti-shirt',bg:'#EEEDFE',color:'#3C3489'},{id:'Розваги',icon:'ti-device-gamepad-2',bg:'#F0F4FF',color:'#2D4AB7'},{id:'Дім',icon:'ti-sofa',bg:'#E6F1FB',color:'#0C447C'},{id:'Зарплата',icon:'ti-briefcase',bg:'#EAF3DE',color:'#27500A'},{id:'Підробіток',icon:'ti-coin',bg:'#FEF3E2',color:'#633806'},{id:'Дитячі',icon:'ti-baby-carriage',bg:'#FBEAF0',color:'#72243E'},{id:'Інше',icon:'ti-dots',bg:'#F0F0F0',color:'#555'}];
window.addEventListener('DOMContentLoaded',()=>{loadSettings();initGoogleAuth();bindEvents();});

function loadSettings(){
  const theme=localStorage.getItem(APP_CONFIG.THEME_KEY)||'light';
  const scale=localStorage.getItem(APP_CONFIG.SCALE_KEY)||'1.0';
  state.scriptUrl=localStorage.getItem(APP_CONFIG.SCRIPT_URL_KEY)||'';
  applyTheme(theme); applyScale(scale);
}

function initGoogleAuth(){
  const s=document.createElement('script');
  s.src='https://accounts.google.com/gsi/client';
  s.onload=()=>{
    const u=localStorage.getItem(APP_CONFIG.USER_KEY);
    const t=localStorage.getItem(APP_CONFIG.TOKEN_KEY);
    if(u&&t){state.user=JSON.parse(u);state.token=t;showApp();}
    else showAuthScreen();
  };
  s.onerror=()=>{
    const u=localStorage.getItem(APP_CONFIG.USER_KEY);
    if(u){state.user=JSON.parse(u);state.token=localStorage.getItem(APP_CONFIG.TOKEN_KEY);showApp();}
    else showAuthScreen();
  };
  document.head.appendChild(s);
}

document.getElementById('google-signin-btn').addEventListener('click',()=>{
  if(!window.google){alert('Немає інтернету. Перевірте підключення.');return;}
  google.accounts.id.initialize({client_id:APP_CONFIG.GOOGLE_CLIENT_ID,callback:handleGoogleSignIn});
  google.accounts.id.prompt(n=>{
    if(n.isNotDisplayed()||n.isSkippedMoment()){
      const url='https://accounts.google.com/o/oauth2/v2/auth?client_id='+APP_CONFIG.GOOGLE_CLIENT_ID+'&redirect_uri='+encodeURIComponent(location.origin+location.pathname)+'&response_type=token&scope=email%20profile';
      location.href=url;
    }
  });
});

function handleGoogleSignIn(resp){
  const tok=resp.credential;
  const p=JSON.parse(atob(tok.split('.')[1]));
  state.user={name:p.given_name||p.name,email:p.email};
  state.token=tok;
  localStorage.setItem(APP_CONFIG.USER_KEY,JSON.stringify(state.user));
  localStorage.setItem(APP_CONFIG.TOKEN_KEY,tok);
  showApp();
}

function logout(){
  localStorage.removeItem(APP_CONFIG.USER_KEY);
  localStorage.removeItem(APP_CONFIG.TOKEN_KEY);
  state.user=null;state.token=null;
  document.getElementById('app').classList.add('hidden');
  document.getElementById('auth-screen').classList.remove('hidden');
  if(window.google)google.accounts.id.disableAutoSelect();
}

function showAuthScreen(){hideSplash();document.getElementById('auth-screen').classList.remove('hidden');}
function showApp(){hideSplash();document.getElementById('auth-screen').classList.add('hidden');document.getElementById('app').classList.remove('hidden');updateUserUI();navigateTo('dashboard');loadFx();}
function hideSplash(){const s=document.getElementById('splash');s.classList.add('hidden');}

function updateUserUI(){
  const u=state.user;if(!u)return;
  const ini=getInitials(u.name);
  setText('sb-avatar',ini);setText('sb-user-name',u.name);setText('topbar-av-text',ini);
  setText('settings-name',u.name);setText('settings-email',u.email);
  setText('greeting-text',getGreeting(u.name));
}
function getInitials(n){return(n||'').split(' ').map(w=>w[0]).join('').toUpperCase().substring(0,2)||'?';}
function getGreeting(n){const h=new Date().getHours();const g=h<12?'Доброго ранку':h<18?'Привіт':'Добрий вечір';return g+', '+n+' 👋';}

function navigateTo(page){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.sb-item,.bn-item').forEach(i=>i.classList.remove('active'));
  const el=document.getElementById('page-'+page);
  if(el)el.classList.add('active');
  document.querySelectorAll('[data-page="'+page+'"]').forEach(e=>e.classList.add('active'));
  state.currentPage=page;
  const titles={dashboard:'Дашборд',operations:'Операції',analytics:'Аналіз',reserve:'Резерв',goals:'Цілі',settings:'Налаштування'};
  setText('topbar-title',titles[page]||page);
  loadPageData(page);closeSidebar();
}

function loadPageData(page){
  if(!state.scriptUrl){renderDemoData(page);return;}
  if(page==='dashboard')fetchDashboard();
  else if(page==='operations')fetchOperations();
  else if(page==='analytics')fetchDashboard().then(()=>renderAnalytics());
  else if(page==='reserve')fetchReserve();
  else if(page==='goals')fetchGoals();
  else if(page==='settings')renderSettingsUI();
}

async function apiGet(action,params={}){
  if(!state.scriptUrl)return null;
  const url=new URL(state.scriptUrl);
  url.searchParams.set('action',action);
  url.searchParams.set('token',state.token||'');
  Object.entries(params).forEach(([k,v])=>url.searchParams.set(k,v));
  const r=await fetch(url.toString());
  if(!r.ok)throw new Error('API '+r.status);
  return r.json();
}
async function apiPost(body){
  if(!state.scriptUrl)return null;
  const r=await fetch(state.scriptUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,token:state.token})});
  if(!r.ok)throw new Error('API '+r.status);
  return r.json();
}

async function fetchDashboard(){try{const d=await apiGet('dashboard',{month:fmtMonth(state.currentMonth)});if(d){state.dashboard=d;renderDashboard(d);}}catch(e){console.error(e);renderDemoData('dashboard');}}
async function fetchOperations(){try{const d=await apiGet('operations',{month:fmtMonth(state.currentMonth)});if(d){state.operations=d.operations||[];renderOperations();}}catch(e){console.error(e);}}
async function fetchReserve(){try{const d=await apiGet('reserve');if(d){state.reserve=d;renderReserve(d);}}catch(e){console.error(e);renderDemoData('reserve');}}
async function fetchGoals(){try{const d=await apiGet('goals');if(d){state.goals=d.goals||[];renderGoals(d.goals);}}catch(e){renderDemoGoals();}}
async function loadFx(){try{const d=state.scriptUrl?await apiGet('fx'):null;if(d){state.fx=d;setText('fx-usd',d.USD?.mid?.toFixed(2)+' ₴');setText('fx-eur',d.EUR?.mid?.toFixed(2)+' ₴');}}catch(e){}}

function renderDashboard(d){
  setText('dash-income',fmtMoney(d.totalIncome,'UAH'));
  setText('dash-expense',fmtMoney(d.totalExpense,'UAH'));
  setText('dash-balance',fmtMoney(d.balance,'UAH'));
  setText('dash-savings-rate','Накопичення '+(d.savingsRate||0).toFixed(0)+'%');
  setText('bud-family',fmtMoney(d.budgets?.['Сімейний']?.balance,'UAH'));
  setText('bud-evgen',fmtMoney(d.budgets?.['Євген']?.balance,'UAH'));
  setText('bud-marina',fmtMoney(d.budgets?.['Марина']?.balance,'UAH'));
  renderRecentOps(d.recent||[]);
  renderCatBars('cat-bars',d.byCategory||{},d.totalExpense);
  updateMonthLabel();
}

function renderRecentOps(ops){
  const el=document.getElementById('recent-list');
  if(!ops.length){el.innerHTML='<div style="padding:16px;text-align:center;color:var(--c-text-3);font-size:13px">Операцій немає</div>';return;}
  el.innerHTML=ops.slice(0,6).map(txItem).join('');
}

function txItem(op){
  const cat=CATEGORIES.find(c=>c.id===op.category)||CATEGORIES.at(-1);
  const plus=op.type==='Дохід';
  return '<div class="tx-item"><div class="tx-icon" style="background:'+cat.bg+'"><i class="ti '+cat.icon+'" style="color:'+cat.color+'"></i></div><div class="tx-info"><div class="tx-name">'+esc(op.desc||op.category)+'</div><div class="tx-meta">'+esc(op.category)+' · '+esc(op.who||'')+' · '+fmtDate(op.date)+'</div></div><div class="tx-amount '+(plus?'plus':'minus')+'">'+(plus?'+':'−')+fmtMoney(op.amount,op.currency)+'</div></div>';
}

function renderCatBars(id,by,total){
  const el=document.getElementById(id);if(!el)return;
  const sorted=Object.entries(by).sort((a,b)=>b[1]-a[1]).slice(0,8);
  const mx=sorted[0]?.[1]||1;
  el.innerHTML=sorted.map(([cat,amt])=>{
    const c=CATEGORIES.find(x=>x.id===cat)||CATEGORIES.at(-1);
    const pct=Math.round(amt/mx*100);
    return '<div class="cat-bar-item"><div class="cat-bar-icon" style="background:'+c.bg+'"><i class="ti '+c.icon+'" style="color:'+c.color+'"></i></div><div class="cat-bar-info"><div class="cat-bar-name">'+esc(cat)+'</div><div class="cat-bar-track"><div class="cat-bar-fill" style="width:'+pct+'%;background:'+c.color+'"></div></div></div><div class="cat-bar-amt">'+fmtMoney(amt,'UAH')+'</div></div>';
  }).join('');
}

function renderOperations(){
  const el=document.getElementById('ops-list');
  let ops=state.operations;
  if(state.filterActive!=='all')ops=ops.filter(o=>o.type===state.filterActive||o.budget===state.filterActive);
  if(!ops.length){el.innerHTML='<div style="padding:20px;text-align:center;color:var(--c-text-3)">Немає операцій</div>';return;}
  el.innerHTML=ops.map(txItem).join('');
}

function renderAnalytics(){
  const d=state.dashboard;if(!d)return;
  renderCatBars('analytics-cats',d.byCategory||{},d.totalExpense);
  const el=document.getElementById('analytics-budgets');
  const bud=d.budgets||{};
  const mx=Math.max(...Object.values(bud).map(b=>b.expense||0))||1;
  const avs={'Сімейний':{ic:'ti-users',bg:'var(--c-bg-3)',cl:'var(--c-text-2)'},'Євген':{av:'ЄК',bg:'var(--c-blue-soft)',cl:'var(--c-blue)'},'Марина':{av:'МК',bg:'var(--c-pink-soft)',cl:'var(--c-pink)'}};
  el.innerHTML=Object.entries(bud).map(([n,b])=>{
    const a=avs[n]||avs['Сімейний'];
    const pct=Math.round((b.expense||0)/mx*100);
    const av=a.ic?'<div class="budget-bar-av" style="background:'+a.bg+';color:'+a.cl+'"><i class="ti '+a.ic+'"></i></div>':'<div class="budget-bar-av" style="background:'+a.bg+';color:'+a.cl+'">'+a.av+'</div>';
    return '<div class="budget-bar-item">'+av+'<div class="budget-bar-info"><div class="budget-bar-name">'+esc(n)+'</div><div class="budget-bar-track"><div class="budget-bar-fill" style="width:'+pct+'%;background:var(--c-red)"></div></div></div><div class="budget-bar-val" style="color:var(--c-red)">'+fmtMoney(b.expense,'UAH')+'</div></div>';
  }).join('');
}

function renderReserve(d){
  setText('res-total',fmtMoney(d.totalUah,'UAH'));
  setText('res-months',d.monthsCoverage+' міс.');
  setText('res-added',fmtMoney(d.addedThisMonth,'UAH'));
  setText('res-months-label','при витратах ~'+fmtMoney(d.avgMonthlyExpense,'UAH')+'/міс');
  setText('mm-val',d.monthsCoverage+' міс.');
  const pct=Math.min(d.monthsCoverage/6*100,100);
  document.getElementById('mm-fill').style.width=pct+'%';
  const rates=d.rates||{UAH:1,USD:40,EUR:44};
  const bals=d.balances||{};
  const ce=document.getElementById('res-currencies');
  ce.innerHTML=['UAH','USD','EUR'].map(cur=>{
    const flags={UAH:'🇺🇦',USD:'🇺🇸',EUR:'🇪🇺'};
    const names={UAH:'Гривня',USD:'Долар',EUR:'Євро'};
    const r=rates[cur]||1;const a=bals[cur]||0;
    const eq=Math.round(a*r);const sym=CUR_SYMBOLS[cur];
    const psh=d.totalUah?Math.round(eq/d.totalUah*100):0;
    return '<div class="tx-item"><div class="tx-icon" style="font-size:20px">'+flags[cur]+'</div><div class="tx-info"><div class="tx-name">'+names[cur]+'</div><div class="tx-meta">'+(cur!=='UAH'?'Курс: '+r.toFixed(2)+' ₴':'Основна валюта')+'</div></div><div style="text-align:right"><div style="font-size:14px;font-weight:700">'+sym+Math.abs(a).toLocaleString('uk-UA')+'</div><div style="font-size:11px;color:var(--c-text-2)">'+eq.toLocaleString('uk-UA')+' ₴ · '+psh+'%</div></div></div>';
  }).join('');
  const he=document.getElementById('res-history');
  const hist=d.history||[];const mxh=Math.max(...hist.map(h=>h.total),1);
  he.innerHTML=hist.slice(-6).map(h=>'<div class="res-hist-row"><div class="res-hist-month">'+h.month.substring(5)+'</div><div class="res-hist-bar-wrap"><div class="res-hist-bar" style="width:'+Math.round(h.total/mxh*100)+'%"></div></div><div class="res-hist-val">'+fmtMoney(h.total,'UAH')+'</div></div>').join('');
  const te=document.getElementById('res-tx-list');
  te.innerHTML=(d.transactions||[]).slice(0,8).map(tx=>{
    const add=tx.type==='Поповнення';
    return '<div class="tx-item"><div class="tx-icon" style="background:'+(add?'var(--c-green-soft)':'var(--c-red-soft)')+'"><i class="ti ti-shield" style="color:'+(add?'var(--c-green)':'var(--c-red)')+'"></i></div><div class="tx-info"><div class="tx-name">'+esc(tx.comment||tx.type)+'</div><div class="tx-meta">'+esc(tx.type)+' · '+esc(tx.who||'')+' · '+fmtDate(tx.date)+'</div></div><div class="tx-amount '+(add?'plus':'minus')+'">'+(add?'+':'−')+(CUR_SYMBOLS[tx.currency]||'₴')+Math.abs(tx.amount).toLocaleString('uk-UA')+'</div></div>';
  }).join('');
}

function renderGoals(goals){
  const el=document.getElementById('goals-list');
  if(!goals||!goals.length){el.innerHTML='<p style="color:var(--c-text-3)">Цілей немає</p>';return;}
  el.innerHTML=goals.map(g=>{
    const pct=Math.min(Math.round((g.saved/g.target)*100),100);
    return '<div class="goal-card"><div class="goal-card-head"><div class="goal-icon" style="background:var(--c-blue-soft)"><i class="ti ti-target" style="color:var(--c-blue)"></i></div><div style="flex:1"><div class="goal-name">'+esc(g.name)+'</div><div class="goal-budget">'+esc(g.budget||'')+'</div></div><div class="goal-pct">'+pct+'%</div></div><div class="goal-progress-wrap"><div class="goal-progress-fill" style="width:'+pct+'%"></div></div><div class="goal-footer"><span class="goal-saved">'+fmtMoney(g.saved,'UAH')+'</span><span class="goal-remaining">з '+fmtMoney(g.target,'UAH')+'</span></div></div>';
  }).join('');
}

function renderSettingsUI(){
  const el=document.getElementById('script-url-preview');
  el.textContent=state.scriptUrl?state.scriptUrl.substring(0,50)+'…':'Не налаштовано';
  const ss=document.getElementById('sync-status');
  ss.textContent=state.scriptUrl?'● Підключено':'○ Не підключено';
  ss.style.color=state.scriptUrl?'var(--c-green)':'var(--c-red)';
  const cl=document.getElementById('categories-list');
  cl.innerHTML=CATEGORIES.map(c=>'<div class="settings-row-item"><div class="sri-icon" style="background:'+c.bg+'"><i class="ti '+c.icon+'" style="color:'+c.color+'"></i></div><div class="sri-info"><div class="sri-name">'+esc(c.id)+'</div></div></div>').join('');
}

function renderDemoData(page){
  const ops=[
    {date:'2026-05-11',type:'Витрата',category:'Продукти',desc:'Сільпо',amount:680,currency:'UAH',who:'Євген',budget:'Сімейний'},
    {date:'2026-05-10',type:'Дохід',category:'Зарплата',desc:'Зарплата',amount:32000,currency:'UAH',who:'Євген',budget:'Євген'},
    {date:'2026-05-10',type:'Витрата',category:'Транспорт',desc:'ОККО',amount:1200,currency:'UAH',who:'Марина',budget:'Сімейний'},
    {date:'2026-05-09',type:'Витрата',category:'Комунальні',desc:'Yasno',amount:2400,currency:'UAH',who:'Марина',budget:'Сімейний'},
    {date:'2026-05-08',type:'Дохід',category:'Підробіток',desc:'Фріланс',amount:8500,currency:'UAH',who:'Євген',budget:'Євген'},
    {date:'2026-05-07',type:'Дохід',category:'Зарплата',desc:'Зарплата М',amount:18000,currency:'UAH',who:'Марина',budget:'Марина'},
    {date:'2026-05-06',type:'Витрата',category:'Ресторани',desc:'Кафе',amount:340,currency:'UAH',who:'Євген',budget:'Євген'},
  ];
  state.operations=ops;
  if(page==='dashboard'){
    const ti=ops.filter(o=>o.type==='Дохід').reduce((s,o)=>s+o.amount,0);
    const te=ops.filter(o=>o.type==='Витрата').reduce((s,o)=>s+o.amount,0);
    const by={};ops.filter(o=>o.type==='Витрата').forEach(o=>{by[o.category]=(by[o.category]||0)+o.amount;});
    renderDashboard({totalIncome:ti,totalExpense:te,balance:ti-te,savingsRate:(ti-te)/ti*100,budgets:{Сімейний:{income:0,expense:4620,balance:-4620},Євген:{income:40500,expense:340,balance:40160},Марина:{income:18000,expense:0,balance:18000}},byCategory:by,recent:ops.slice(0,5)});
  }
  if(page==='operations')renderOperations();
  if(page==='analytics'){
    const ti=ops.filter(o=>o.type==='Дохід').reduce((s,o)=>s+o.amount,0);
    const te=ops.filter(o=>o.type==='Витрата').reduce((s,o)=>s+o.amount,0);
    const by={};ops.filter(o=>o.type==='Витрата').forEach(o=>{by[o.category]=(by[o.category]||0)+o.amount;});
    state.dashboard={totalIncome:ti,totalExpense:te,byCategory:by,budgets:{Сімейний:{expense:4620},Євген:{expense:340},Марина:{expense:0}}};
    renderAnalytics();
  }
  if(page==='reserve')renderReserve({totalUah:187400,monthsCoverage:4.7,addedThisMonth:8500,avgMonthlyExpense:40000,balances:{UAH:85000,USD:1500,EUR:960},rates:{UAH:1,USD:40.2,EUR:43.8},history:[{month:'2025-12',delta:8000,total:98000},{month:'2026-01',delta:14500,total:112500},{month:'2026-02',delta:15700,total:128200},{month:'2026-03',delta:20700,total:148900},{month:'2026-04',delta:30000,total:178900},{month:'2026-05',delta:8500,total:187400}],transactions:[{date:'2026-05-09',amount:5000,currency:'UAH',type:'Поповнення',who:'Євген',comment:'Відкладено з зарплати'},{date:'2026-04-24',amount:3500,currency:'UAH',type:'Поповнення',who:'Марина',comment:'Економія за місяць'},{date:'2026-04-10',amount:1500,currency:'USD',type:'Поповнення',who:'Євген',comment:'Конвертував'},{date:'2026-03-15',amount:2000,currency:'UAH',type:'Зняття',who:'Євген',comment:'Ремонт машини'}]});
  if(page==='goals')renderGoals([{name:'✈️ Відпустка 2026',target:50000,saved:34000,budget:'Сімейний'},{name:'💻 Новий ноутбук',target:50000,saved:21000,budget:'Євген'},{name:'👶 Для Матвійки',target:20000,saved:5000,budget:'Сімейний'},{name:'📱 Телефон Марина',target:25000,saved:8000,budget:'Марина'}]);
  if(page==='settings')renderSettingsUI();
}

function openModal(type){
  state.currentType=type||'Витрата';state.currentCurrency='UAH';state.selectedCat='';
  renderCatGrid();updateModalType();
  document.getElementById('amount-input').value='';
  document.getElementById('desc-input').value='';
  document.getElementById('currency-btn').innerHTML='UAH <i class="ti ti-chevron-down"></i>';
  document.getElementById('amount-cur-icon').textContent='₴';
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.getElementById('modal-add').classList.remove('hidden');
  setTimeout(()=>document.getElementById('amount-input').focus(),100);
}
function closeModal(){
  document.getElementById('modal-overlay').classList.add('hidden');
  document.getElementById('modal-add').classList.add('hidden');
  document.getElementById('modal-reserve').classList.add('hidden');
}
function setType(t){state.currentType=t;updateModalType();}
function updateModalType(){
  const inc=state.currentType==='Дохід';
  document.getElementById('tt-expense').classList.toggle('active',!inc);
  document.getElementById('tt-income').classList.toggle('active',inc);
  document.getElementById('save-btn').textContent=inc?'Зберегти дохід':'Зберегти витрату';
  document.getElementById('save-btn').style.background=inc?'var(--c-green)':'var(--c-red)';
  renderCatGrid();
}
function renderCatGrid(){
  const inc=state.currentType==='Дохід';
  const cats=inc?CATEGORIES.filter(c=>['Зарплата','Підробіток','Інше'].includes(c.id)):CATEGORIES.filter(c=>!['Зарплата','Підробіток'].includes(c.id));
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
  const btn=document.getElementById('save-btn');
  btn.disabled=true;btn.textContent='Збереження...';
  try{
    if(state.scriptUrl)await apiPost({action:'addOperation',type:state.currentType,category:state.selectedCat,amount:amt,currency:state.currentCurrency,desc:document.getElementById('desc-input').value||'',budget:'Сімейний'});
    closeModal();showToast('✅ Збережено!');
    if(state.currentPage==='dashboard')fetchDashboard();
    if(state.currentPage==='operations')fetchOperations();
  }catch(e){showToast('Помилка збереження','error');}
  finally{btn.disabled=false;updateModalType();}
}

function openReserveModal(){
  state.reserveType='Поповнення';state.reserveCurrency='UAH';
  document.getElementById('res-amount-input').value='';
  document.getElementById('res-desc-input').value='';
  document.getElementById('res-currency-btn').innerHTML='UAH <i class="ti ti-chevron-down"></i>';
  document.getElementById('rt-add').classList.add('active');
  document.getElementById('rt-remove').classList.remove('active');
  document.getElementById('res-save-btn').textContent='Зберегти поповнення';
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.getElementById('modal-reserve').classList.remove('hidden');
}
function setReserveType(t){
  state.reserveType=t;
  document.getElementById('rt-add').classList.toggle('active',t==='Поповнення');
  document.getElementById('rt-remove').classList.toggle('active',t==='Зняття');
  document.getElementById('res-save-btn').textContent=t==='Поповнення'?'Зберегти поповнення':'Зберегти зняття';
}
function cycleReserveCurrency(){
  const i=CURRENCIES.indexOf(state.reserveCurrency);
  state.reserveCurrency=CURRENCIES[(i+1)%CURRENCIES.length];
  document.getElementById('res-currency-btn').innerHTML=state.reserveCurrency+' <i class="ti ti-chevron-down"></i>';
}
async function submitReserve(){
  const amt=parseFloat(document.getElementById('res-amount-input').value);
  if(!amt||amt<=0){showToast('Вкажи суму','error');return;}
  const btn=document.getElementById('res-save-btn');btn.disabled=true;
  try{
    if(state.scriptUrl)await apiPost({action:'addReserve',type:state.reserveType,amount:amt,currency:state.reserveCurrency,comment:document.getElementById('res-desc-input').value||''});
    closeModal();showToast('✅ Збережено!');fetchReserve();
  }catch(e){showToast('Помилка збереження','error');}
  finally{btn.disabled=false;}
}

function updateMonthLabel(){
  const d=state.currentMonth;
  const lbl=MONTH_UK[d.getMonth()]+' '+d.getFullYear();
  setText('month-label',lbl);setText('greeting-month',lbl);
}
function prevMonth(){state.currentMonth=new Date(state.currentMonth.getFullYear(),state.currentMonth.getMonth()-1,1);updateMonthLabel();loadPageData(state.currentPage);}
function nextMonth(){state.currentMonth=new Date(state.currentMonth.getFullYear(),state.currentMonth.getMonth()+1,1);updateMonthLabel();loadPageData(state.currentPage);}
function fmtMonth(d){return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0');}

function applyTheme(t){document.body.setAttribute('data-theme',t);localStorage.setItem(APP_CONFIG.THEME_KEY,t);document.querySelectorAll('.theme-btn').forEach(b=>b.classList.toggle('active',b.dataset.theme===t));}
function applyScale(s){document.documentElement.style.fontSize=(16*parseFloat(s))+'px';localStorage.setItem(APP_CONFIG.SCALE_KEY,s);document.querySelectorAll('.scale-btn').forEach(b=>b.classList.toggle('active',b.dataset.scale===s));}

function openSidebar(){
  document.getElementById('sidebar').classList.add('open');
  let ov=document.getElementById('sb-ov');
  if(!ov){ov=document.createElement('div');ov.id='sb-ov';ov.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:99;';ov.onclick=closeSidebar;document.body.appendChild(ov);}
  ov.style.display='block';
}
function closeSidebar(){document.getElementById('sidebar').classList.remove('open');const ov=document.getElementById('sb-ov');if(ov)ov.style.display='none';}

function showToast(msg,type='success'){
  const t=document.createElement('div');
  t.style.cssText='position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:'+(type==='error'?'var(--c-red)':'var(--c-green)')+';color:#fff;padding:10px 20px;border-radius:10px;font-size:13px;font-weight:600;z-index:1000;box-shadow:0 4px 16px rgba(0,0,0,.2);animation:fadeInUp .2s ease;white-space:nowrap;';
  t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),2500);
}

function setScriptUrl(){
  const u=prompt('URL Google Apps Script Web App:',state.scriptUrl);
  if(u!==null){state.scriptUrl=u.trim();localStorage.setItem(APP_CONFIG.SCRIPT_URL_KEY,state.scriptUrl);renderSettingsUI();if(state.scriptUrl){loadFx();fetchDashboard();}}
}

function fmtMoney(n,cur){if(n===undefined||n===null||isNaN(n))return '—';const sym=CUR_SYMBOLS[cur]||cur;const fmt=Math.abs(Math.round(n)).toLocaleString('uk-UA');return cur==='UAH'?fmt+' '+sym:sym+fmt;}
function fmtDate(s){if(!s)return '';const d=new Date(s);if(isNaN(d))return s;const t=new Date();const y=new Date(t);y.setDate(t.getDate()-1);if(d.toDateString()===t.toDateString())return 'сьогодні';if(d.toDateString()===y.toDateString())return 'вчора';return d.getDate()+' '+MONTH_UK[d.getMonth()].toLowerCase().slice(0,3);}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function setText(id,v){const el=document.getElementById(id);if(el)el.textContent=v??'—';}

function bindEvents(){
  document.querySelectorAll('[data-page]').forEach(el=>el.addEventListener('click',e=>{e.preventDefault();navigateTo(el.dataset.page);}));
  document.getElementById('menu-btn').addEventListener('click',openSidebar);
  document.getElementById('month-prev').addEventListener('click',prevMonth);
  document.getElementById('month-next').addEventListener('click',nextMonth);
  document.getElementById('fab').addEventListener('click',()=>openModal());
  document.getElementById('add-btn-dash').addEventListener('click',()=>openModal());
  const aob=document.getElementById('add-btn-ops');if(aob)aob.addEventListener('click',()=>openModal());
  document.getElementById('add-reserve-btn').addEventListener('click',openReserveModal);
  document.getElementById('modal-overlay').addEventListener('click',closeModal);
  document.getElementById('tt-expense').addEventListener('click',()=>setType('Витрата'));
  document.getElementById('tt-income').addEventListener('click',()=>setType('Дохід'));
  document.getElementById('rt-add').addEventListener('click',()=>setReserveType('Поповнення'));
  document.getElementById('rt-remove').addEventListener('click',()=>setReserveType('Зняття'));
  document.getElementById('currency-btn').addEventListener('click',cycleCurrency);
  document.getElementById('res-currency-btn').addEventListener('click',cycleReserveCurrency);
  document.getElementById('save-btn').addEventListener('click',submitOperation);
  document.getElementById('res-save-btn').addEventListener('click',submitReserve);
  document.querySelectorAll('.theme-btn').forEach(b=>b.addEventListener('click',()=>applyTheme(b.dataset.theme)));
  document.querySelectorAll('.scale-btn').forEach(b=>b.addEventListener('click',()=>applyScale(b.dataset.scale)));
  document.getElementById('logout-btn').addEventListener('click',logout);
  document.getElementById('set-url-btn').addEventListener('click',setScriptUrl);
  document.getElementById('sync-now-btn').addEventListener('click',()=>{loadFx();loadPageData(state.currentPage);showToast('🔄 Синхронізація...');});
  document.querySelectorAll('.filter-pill').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.filter-pill').forEach(x=>x.classList.remove('active'));b.classList.add('active');state.filterActive=b.dataset.filter;renderOperations();}));
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
  updateMonthLabel();
}
