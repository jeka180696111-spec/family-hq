// ═══════════════════════════════
// INIT — auth, navigation, startup
// ═══════════════════════════════
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
