// ═══════════════════════════════
// STORAGE — localStorage helpers
// ═══════════════════════════════
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
