// ═══════════════════════════════════════════════════════════════
// CONFIG — глобальні константи, дефолти, state
// ═══════════════════════════════════════════════════════════════

export const APP_CONFIG = {
  // ⚠️ ОНОВИ при зміні розгортання Apps Script
  SCRIPT_URL: 'https://script.google.com/macros/s/AKfycbyJcoxq4McYpb-MxcIiQ4wCLjdwH2N7uc8lebh_9M6ktpq57oxi6Bhy2e3O9xcTrZe4zA/exec',

  // Google OAuth (Sign in with Google)
  GOOGLE_CLIENT_ID: '459630045625-hns8b8q39rnga0vfqng16i3v0pp4cv5p.apps.googleusercontent.com',

  // localStorage ключі
  SCRIPT_URL_KEY: 'budget_script_url',
  TOKEN_KEY:      'budget_google_token',
  USER_KEY:       'budget_user',
  THEME_KEY:      'budget_theme',
  FONT_KEY:       'budget_font',
  AVATAR_KEY:     'budget_avatar',
  USERNAME_KEY:   'budget_username',
  FAMILY_KEY:     'budget_family',
  GOALS_KEY:      'budget_goals',
  EXP_CATS_KEY:   'budget_exp_cats',
  INC_CATS_KEY:   'budget_inc_cats',
  CARDS_KEY:      'budget_cards',
  MONO_EVGEN_KEY: 'budget_mono_evgen',
  MONO_MARINA_KEY:'budget_mono_marina',
  PROFILES_KEY:   'budget_profiles',
  LAST_SYNC_KEY:  'budget_last_sync',
  TRANSFERS_KEY:  'budget_transfers',
  WALLET_TYPES_KEY:'budget_wallet_types',

  // Секретний ключ для бекенду
  SECRET_KEY: 'budget2026koval',
};

// Учасники сім'ї (поки 2, легко розширити)
export const FAMILY_MEMBERS = ['Євген', 'Марина'];

// ── ДЕФОЛТНІ ДАНІ ───────────────────────────────────────────

export const DEFAULT_EXP_CATS = [
  {id:'Продукти',   icon:'ti-shopping-cart',       bg:'#E1F5EE', color:'#085041'},
  {id:'Транспорт',  icon:'ti-car',                 bg:'#FAECE7', color:'#712B13'},
  {id:'Комунальні', icon:'ti-home',                bg:'#E6F1FB', color:'#0C447C'},
  {id:'Ресторани',  icon:'ti-tools-kitchen-2',     bg:'#FEF3E2', color:'#633806'},
  {id:"Здоров'я",   icon:'ti-heart',               bg:'#FBEAF0', color:'#72243E'},
  {id:'Одяг',       icon:'ti-shirt',               bg:'#EEEDFE', color:'#3C3489'},
  {id:'Розваги',    icon:'ti-device-gamepad-2',    bg:'#F0F4FF', color:'#2D4AB7'},
  {id:'Дім',        icon:'ti-sofa',                bg:'#E6F1FB', color:'#0C447C'},
  {id:'Дитячі',     icon:'ti-baby-carriage',       bg:'#FBEAF0', color:'#72243E'},
  {id:'Інше',       icon:'ti-dots',                bg:'#F0F0F0', color:'#555555'},
];

export const DEFAULT_INC_CATS = [
  {id:'Зарплата',   icon:'ti-briefcase', bg:'#EAF3DE', color:'#27500A'},
  {id:'Підробіток', icon:'ti-coin',      bg:'#FEF3E2', color:'#633806'},
  {id:'Інше',       icon:'ti-dots',      bg:'#F0F0F0', color:'#555555'},
];

export const DEFAULT_CARDS = [
  {id:'Готівка',     icon:'ti-cash',         bg:'#EAF3DE', color:'#27500A', walletType:'cash'},
  {id:'Моно чорна',  icon:'ti-credit-card',  bg:'#1a1a2e', color:'#ffffff', walletType:'card'},
  {id:'ПУМБ',        icon:'ti-credit-card',  bg:'#E6F1FB', color:'#0C447C', walletType:'card'},
  {id:'Приват',      icon:'ti-credit-card',  bg:'#FBEAF0', color:'#72243E', walletType:'card'},
  {id:'Кредитна',    icon:'ti-credit-card',  bg:'#FAEEDA', color:'#633806', walletType:'credit'},
];

// Дефолтні типи рахунків (юзер може додавати/редагувати/видаляти)
export const DEFAULT_WALLET_TYPES = [
  {id:'cash',     name:'Готівка',     icon:'ti-cash',              bg:'#EAF3DE', color:'#27500A'},
  {id:'card',     name:'Картка',      icon:'ti-credit-card',       bg:'#E6F1FB', color:'#185FA5'},
  {id:'credit',   name:'Кредитна',    icon:'ti-credit-card-pay',   bg:'#FAEEDA', color:'#633806'},
  {id:'savings',  name:'Накопичення', icon:'ti-coins',             bg:'#FEF3E2', color:'#BA7517'},
  {id:'currency', name:'Валюта',      icon:'ti-currency-dollar',   bg:'#EEEDFE', color:'#7F77DD'},
];

// Доступний набір іконок (Tabler 3.x)
export const ICON_LIST = [
  'ti-cash','ti-credit-card','ti-credit-card-pay','ti-wallet','ti-coins','ti-currency-dollar',
  'ti-currency-euro','ti-currency-hryvnia','ti-shopping-cart','ti-shopping-bag','ti-basket',
  'ti-car','ti-bus','ti-train','ti-plane','ti-bike','ti-walk','ti-home','ti-building',
  'ti-tools-kitchen-2','ti-cup','ti-pizza','ti-meat','ti-apple','ti-heart','ti-medical-cross',
  'ti-pill','ti-shirt','ti-dress','ti-shoe','ti-device-gamepad-2','ti-music','ti-movie',
  'ti-book','ti-school','ti-baby-carriage','ti-dog','ti-cat','ti-flower','ti-tree','ti-bolt',
  'ti-flame','ti-droplet','ti-wifi','ti-device-mobile','ti-device-laptop','ti-tools','ti-paint',
  'ti-briefcase','ti-coin','ti-piggy-bank','ti-target','ti-gift','ti-cake','ti-star','ti-heart-filled',
  'ti-sofa','ti-bed','ti-bath','ti-key','ti-mail','ti-phone','ti-headphones','ti-camera',
  'ti-palette','ti-scissors','ti-needle','ti-paw','ti-dots',
];

// ── STATE — глобальний стан додатку ──────────────────────────
export const state = {
  user: null,
  token: null,
  scriptUrl: '',
  currentPage: 'dashboard',
  currentMonth: new Date(),
  calMonth: new Date(),
  calPeriod: 'month',
  currentType: 'Витрата',
  currentCurrency: 'UAH',
  reserveType: 'Поповнення',
  reserveCurrency: 'UAH',
  selectedCat: '',
  selectedCard: '',
  modalMember: null,
  dashboard: null,
  reserve: null,
  operations: [],
  goals: [],
  transfers: [],
  fx: null,
  filterActive: 'all',
  editingGoalIdx: -1,
  activeAccountId: null,
  editingOp: null,
  openMember: undefined,
  walletFilter: 'all', // 'all' | 'Євген' | 'Марина' | typeId
};

// Стан синхронізації (offline queue)
export const syncState = {
  pendingSettings: false,
  pendingOps: [],
  online: navigator.onLine,
};

window.addEventListener('online',  () => { syncState.online = true; });
window.addEventListener('offline', () => { syncState.online = false; });
