// ═══════════════════════════════
// RENDER — all render functions
// ═══════════════════════════════
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
  el.innerHTML=FAMILY_MEMBERS.map(member=>{
    const mc=MEMBER_COLORS[member]||{bg:'var(--c-bg-3)',cl:'var(--c-text)',initials:'??'};
    const prof=profiles[member]||{name:member,avatar:null};
    const cards=getCards(member);
    // Баланс по картках — з операцій і з dashboardbyMember
    const memberData=byMember[member]||{income:0,expense:0,byCard:{}};
    const totalBal=memberData.income-memberData.expense;
    const cardsHtml=cards.map(c=>{
      const cardData=memberData.byCard?.[c.id]||{income:0,expense:0};
      const bal=cardData.income-cardData.expense;
      // Локальний баланс з state.operations
      const localBal=state.operations.filter(o=>o.who===member&&o.card===c.id).reduce((s,o)=>{if(o.type==='Дохід')return s+(o.amountUah||o.amount);if(o.type==='Витрата')return s-(o.amountUah||o.amount);return s;},0);
      const displayBal=state.operations.length?localBal:bal;
      return `<div class="member-card-chip" data-member="${esc(member)}" data-account="${esc(c.id)}">
        <div class="mcc-icon" style="background:${c.bg}"><i class="ti ${c.icon}" style="color:${c.color}"></i></div>
        <div class="mcc-info">
          <div class="mcc-name">${esc(c.id)}</div>
          <div class="mcc-bal ${displayBal>=0?'pos':'neg'}">${fmtMoney(Math.abs(displayBal),'UAH')}</div>
        </div>
      </div>`;
    }).join('');
    const displayBal=state.operations.length?state.operations.filter(o=>o.who===member).reduce((s,o)=>{if(o.type==='Дохід')return s+(o.amountUah||o.amount);if(o.type==='Витрата')return s-(o.amountUah||o.amount);return s;},0):totalBal;
    const avatarHtml=prof.avatar
      ?`<img src="${prof.avatar}" class="member-col-av-img">`
      :`<div class="member-col-av" style="background:${mc.bg};color:${mc.cl}">${mc.initials}</div>`;
    return `<div class="member-col">
      <div class="member-col-head">
        <div class="member-col-av-wrap">${avatarHtml}</div>
        <div class="member-col-name">${esc(prof.name||member)}</div>
        <div class="member-col-total ${displayBal>=0?'pos':'neg'}">${fmtMoney(Math.abs(displayBal),'UAH')}</div>
      </div>
      <div class="member-cards">${cardsHtml}</div>
    </div>`;
  }).join('');
  el.querySelectorAll('.member-card-chip').forEach(ch=>{
    ch.addEventListener('click',()=>openAccountDetail(ch.dataset.account,ch.dataset.member));
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
