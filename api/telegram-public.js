// Public bot @MANY_BUDGET_BOT — uses TELEGRAM_BOT_TOKEN_PUBLIC
const createHandler = require('./_telegram-core');
module.exports = createHandler(process.env.TELEGRAM_BOT_TOKEN_PUBLIC);
