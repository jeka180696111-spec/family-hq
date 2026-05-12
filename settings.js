// ═══════════════════════════════
// SETTINGS — settings page
// ═══════════════════════════════
function renderSettingsUI(){
  const el=document.getElementById('script-url-preview');
  if(el) el.textContent=state.scriptUrl?state.scriptUrl.substring(0,50)+'…':'Не налаштовано';
  const ss=document.getElementById('sync-status');
  if(ss){
    const lastSync=localStorage.getItem(APP_CONFIG.LAST_SYNC_KEY);
    ss.textContent=state.scriptUrl?(lastSync?'● Синхронізовано '+new Date(lastSync).toLocaleTimeString('uk-UA'):'● Підключено'):'○ Не підключено';
    ss.style.color=state.scriptUrl?'var(--c-green)':'var(--c-red)';
  }
  renderCatsList('expense-cats-list',getExpCats(),false);
  renderCatsList('income-cats-list',getIncCats(),true);
  // Профілі членів + їх картки
  renderMemberProfileCard('evgen','Євген');
  renderMemberProfileCard('marina','Марина');
}
function renderMemberProfileCard(elemId, member){
  const el=document.getElementById('member-profile-'+elemId);if(!el)return;
  const profs=getProfiles();
  const prof=profs[member]||{name:member,avatar:null};
  const mc=MEMBER_COLORS[member]||{bg:'var(--c-bg-3)',cl:'var(--c-text)',initials:'??'};
  const cards=getCards(member);
  const isAdmin=(state.user?.role==='admin'||getMyMember()===member);
  const avatarHtml=prof.avatar?`<img src="${prof.avatar}" style="width:44px;height:44px;border-radius:50%;object-fit:cover;">`:`<div style="width:44px;height:44px;border-radius:50%;background:${mc.bg};color:${mc.cl};display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;">${mc.initials}</div>`;
  el.innerHTML=`
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
      <div style="cursor:pointer;" id="av-click-${elemId}">${avatarHtml}</div>
      <div style="flex:1">
        <input class="settings-name-input" id="profile-name-${elemId}" value="${esc(prof.name||member)}" placeholder="Ім'я" style="font-size:15px;font-weight:700;width:100%;${!isAdmin?'opacity:.5;pointer-events:none;':''}">
        <div style="font-size:11px;color:var(--c-text-3);margin-top:3px;">Ім'я гаманця = ім'я профілю</div>
      </div>
      ${isAdmin?`<button class="btn-ghost-sm" id="save-profile-${elemId}" style="white-space:nowrap"><i class="ti ti-check"></i></button>`:''}
    </div>
    <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--c-text-3);margin-bottom:8px;">Рахунки</div>
    <div class="cat-accordion" id="cards-${elemId}-list"></div>
    ${isAdmin?`<div class="settings-row-item" style="margin-top:8px;"><input class="settings-name-input flex1" id="new-card-${elemId}" placeholder="Назва рахунку"><button class="btn-ghost-sm" id="add-card-${elemId}"><i class="ti ti-plus"></i> Іконка</button></div>`:''}
  `;
  renderCardsList('cards-'+elemId+'-list', cards, member);

  // Events
  const saveBtn=el.querySelector('#save-profile-'+elemId);
  if(saveBtn) saveBtn.addEventListener('click',()=>{
    const newName=el.querySelector('#profile-name-'+elemId).value.trim();if(!newName)return;
    const profs2=getProfiles();profs2[member]=profs2[member]||{};profs2[member].name=newName;
    saveProfiles(profs2);
    // Оновлюємо FAMILY_MEMBERS display name і картку гаманця
    document.querySelectorAll('.member-col-name').forEach(e=>{if(e.dataset.member===member)e.textContent=newName;});
    renderMemberColumns();showToast('✅ Збережено!');
  });

  const avBtn=el.querySelector('#av-click-'+elemId);
  if(avBtn&&isAdmin) avBtn.addEventListener('click',()=>{
    const inp=document.createElement('input');inp.type='file';inp.accept='image/*';
    inp.onchange=e=>{const f=e.target.files[0];if(!f)return;const r=new FileReader();r.onload=ev=>{const url=ev.target.result;const profs2=getProfiles();profs2[member]=profs2[member]||{};profs2[member].avatar=url;saveProfiles(profs2);if(member===getMyMember()){localStorage.setItem(APP_CONFIG.AVATAR_KEY,url);applyAvatar(url);}renderMemberProfileCard(elemId,member);renderMemberColumns();showToast('✅ Аватар!');};r.readAsDataURL(f);};
    inp.click();
  });

  const addBtn=el.querySelector('#add-card-'+elemId);
  if(addBtn) addBtn.addEventListener('click',()=>{
    const mode=elemId==='evgen'?'card-evgen':'card-marina';openIconPicker(mode);
  });
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
