// ═══════════════════════════════════════════════════════════════
// CONFIG — Firebase + глобальні константи, дефолти, state
// ═══════════════════════════════════════════════════════════════

// Firebase конфіг (публічні ключі — безпечно тримати у фронті)
export const FIREBASE_CONFIG = {
  apiKey: "AIzaSyCvIpAi23W4OIF4XpHwwxTeG7l66kn3kV8",
  authDomain: "familybudget-aa238.firebaseapp.com",
  projectId: "familybudget-aa238",
  storageBucket: "familybudget-aa238.firebasestorage.app",
  messagingSenderId: "391938954609",
  appId: "1:391938954609:web:d22a868a85070821cd92d0",
};

// Дефолтні імена (перевизначаються через налаштування)
let _familyMembers = null;
export function getFamilyMembers() {
  if (_familyMembers) return _familyMembers;
  try {
    const saved = localStorage.getItem('budget_members');
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed) && parsed.length > 0) {
        _familyMembers = parsed;
        return parsed;
      }
    }
  } catch(e) {}
  return ['Євген', 'Марина']; // дефолт
}
export function setFamilyMembers(members) {
  _familyMembers = members;
  localStorage.setItem('budget_members', JSON.stringify(members));
}
// Сумісність зі старим кодом (деякі модулі імпортують як const)
export const FAMILY_MEMBERS = new Proxy([], {
  get(target, prop) {
    const members = getFamilyMembers();
    if (prop === 'length') return members.length;
    if (prop === Symbol.iterator) return members[Symbol.iterator].bind(members);
    if (prop === 'forEach') return members.forEach.bind(members);
    if (prop === 'map') return members.map.bind(members);
    if (prop === 'filter') return members.filter.bind(members);
    if (prop === 'find') return members.find.bind(members);
    if (prop === 'includes') return members.includes.bind(members);
    if (prop === 'indexOf') return members.indexOf.bind(members);
    if (prop === 'join') return members.join.bind(members);
    if (prop === 'some') return members.some.bind(members);
    if (prop === 'every') return members.every.bind(members);
    if (prop === 'reduce') return members.reduce.bind(members);
    if (prop === 'slice') return members.slice.bind(members);
    if (typeof prop === 'string' && !isNaN(prop)) return members[Number(prop)];
    return members[prop];
  }
});

// localStorage ключі
export const APP_CONFIG = {
  THEME_KEY:       'budget_theme',
  EXP_CATS_KEY:    'budget_exp_cats',
  INC_CATS_KEY:    'budget_inc_cats',
  CARDS_KEY:       'budget_cards',
  PROFILES_KEY:    'budget_profiles',
  WALLET_TYPES_KEY:'budget_wallet_types',
  FAMILY_KEY:      'budget_family',
  LAST_SYNC_KEY:   'budget_last_sync',
};

// Дефолтні категорії витрат
export const DEFAULT_EXP_CATS = [
  { id: 'Продукти', icon: 'ti-shopping-cart', bg: '#E1F5EE', color: '#085041' },
  { id: 'Транспорт', icon: 'ti-car', bg: '#FAECE7', color: '#712B13' },
  { id: 'Комунальні', icon: 'ti-home', bg: '#E6F1FB', color: '#0C447C' },
  { id: 'Ресторани', icon: 'ti-tools-kitchen-2', bg: '#FEF3E2', color: '#633806' },
  { id: "Здоров'я", icon: 'ti-heart', bg: '#FBEAF0', color: '#72243E' },
  { id: 'Одяг', icon: 'ti-shirt', bg: '#EEEDFE', color: '#3C3489' },
  { id: 'Розваги', icon: 'ti-device-gamepad-2', bg: '#F0F4FF', color: '#2D4AB7' },
  { id: 'Дім', icon: 'ti-sofa', bg: '#E6F1FB', color: '#0C447C' },
  { id: 'Дитячі', icon: 'ti-baby-carriage', bg: '#FBEAF0', color: '#72243E' },
  { id: 'Інше', icon: 'ti-dots', bg: '#F0F0F0', color: '#555' },
];

// Дефолтні категорії доходів
export const DEFAULT_INC_CATS = [
  { id: 'Зарплата', icon: 'ti-briefcase', bg: '#EAF3DE', color: '#27500A' },
  { id: 'Підробіток', icon: 'ti-coin', bg: '#FEF3E2', color: '#633806' },
  { id: 'Пенсія', icon: 'ti-building-bank', bg: '#EAF3DE', color: '#27500A' },
  { id: 'Виплата', icon: 'ti-receipt', bg: '#EAF3DE', color: '#27500A' },
  { id: 'Інше', icon: 'ti-dots', bg: '#F0F0F0', color: '#555' },
];

// Дефолтні кошельки
export const DEFAULT_CARDS = [
  { id: 'Готівка', icon: 'ti-cash', bg: '#EAF3DE', color: '#27500A', walletType: 'cash', currency: 'UAH' },
  { id: 'Картка', icon: 'ti-credit-card', bg: '#E6F1FB', color: '#185FA5', walletType: 'card', currency: 'UAH' },
];

// Типи кошельків
export const DEFAULT_WALLET_TYPES = [
  { id: 'cash',    name: 'Готівка',      icon: 'ti-cash',            bg: '#EAF3DE', color: '#27500A' },
  { id: 'card',    name: 'Картка',       icon: 'ti-credit-card',     bg: '#E6F1FB', color: '#185FA5' },
  { id: 'credit',  name: 'Кредитна',     icon: 'ti-credit-card-pay', bg: '#FAEEDA', color: '#633806', hasLimit: true },
  { id: 'savings', name: 'Накопичення',  icon: 'ti-coins',           bg: '#FEF3E2', color: '#BA7517' },
];

// Іконки для вибору (icon-picker)
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

// Глобальний стейт (runtime)
export const state = {
  user: null,       // Firebase user object
  member: null,     // 'Євген' | 'Марина'
  token: null,      // сумісність зі старим кодом
  scriptUrl: '',    // не використовується, для сумісності
  familyId: null,   // поточний ID родини (замість FAMILY_ID константи)
  familyMembers: [], // список імен членів родини
  dashboard: null,
  operations: [],
  reserve: null,
  goals: [],
  transfers: [],
  fx: null,         // курси валют { USD: { buy, sale, mid }, EUR: { ... } }
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
  filterActive: 'all',
  editingGoalIdx: -1,
  activeAccountId: null,
  editingOp: null,
  openMember: undefined,
  walletFilter: 'all',
  walletTypeFilter: 'all',
};

// Допоміжний стейт для синхронізації
export const syncState = {
  pendingSettings: false,
};
