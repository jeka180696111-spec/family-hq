// Personal bot — uses TELEGRAM_BOT_TOKEN
const createHandler = require('./_telegram-core');
module.exports = createHandler(process.env.TELEGRAM_BOT_TOKEN);
