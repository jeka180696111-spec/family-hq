// ═══════════════════════════════
// API — server calls + sync
// ═══════════════════════════════
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
