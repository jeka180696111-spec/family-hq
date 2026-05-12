// ═══════════════════════════════
// EVENTS — bindEvents + utils
// ═══════════════════════════════
function bindEvents(){
  // Navigation
  document.querySelectorAll('[data-page]').forEach(el=>el.addEventListener('click',e=>{e.preventDefault();navigateTo(el.dataset.page);}));
  document.getElementById('menu-btn').addEventListener('click',openSidebar);
  document.getElementById('month-prev').addEventListener('click',prevMonth);
  document.getElementById('month-next').addEventListener('click',nextMonth);
  // Calendar nav
  document.getElementById('cal-prev').addEventListener('click',()=>{state.calMonth=new Date(state.calMonth.getFullYear(),state.calMonth.getMonth()-1,1);renderCalendar();});
  document.getElementById('cal-next').addEventListener('click',()=>{state.calMonth=new Date(state.calMonth.getFullYear(),state.calMonth.getMonth()+1,1);renderCalendar();});
  // Calendar period buttons
  document.querySelectorAll('.cal-period-btn').forEach(b=>b.addEventListener('click',()=>{
    document.querySelectorAll('.cal-period-btn').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
    state.calPeriod=b.dataset.period;
    renderCalendar();
  }));
  // FAB & add buttons
  document.getElementById('fab').addEventListener('click',openFabMenu);
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
