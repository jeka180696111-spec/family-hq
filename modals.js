// ═══════════════════════════════
// MODALS — all modals & forms
// ═══════════════════════════════
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
  try{
    if(!state.selectedCard){showToast('Вибери рахунок','error');btn.disabled=false;updateModalType();return;}
    const whoName=state.modalMember||getMyMember();
    const body={action:'addOperation',type:state.currentType,category:state.selectedCat,amount:amt,currency:state.currentCurrency,desc:document.getElementById('desc-input').value||'',budget:whoName,date:dt,card:state.selectedCard,who:whoName};
    // Зберігаємо локально одразу — не залежить від API
    const localOp={...body,date:dt,amountUah:amt,who:whoName,_local:true};
    state.operations.unshift(localOp);
    closeModal();showToast('✅ Збережено!');
    if(state.currentPage==='dashboard'){renderMemberColumns();renderRecentOps(state.operations);}
    else if(state.currentPage==='operations')renderOperations();
    else if(state.currentPage==='calendar')renderCalendar();
    // Відправляємо на сервер — отримуємо row і знімаємо _local
    if(state.scriptUrl){
      apiPost(body)
        .then(res=>{
          if(res?.row){
            localOp.row=res.row;
            delete localOp._local;
            showSyncStatus('ok');
            // Перемальовуємо щоб кнопка edit з'явилась (тепер є row)
            if(state.currentPage==='operations')renderOperations();
            else if(state.currentPage==='dashboard')renderRecentOps(state.operations);
          }
        })
        .catch(()=>{enqueue(body);showSyncStatus('pending');});
    } else {
      // Без scriptUrl — операція залишається локальною, редагування через індекс
      localOp._localIdx=state.operations.indexOf(localOp);
    }
  }catch(e){console.error(e);showToast('Помилка: '+e.message,'error');}
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
