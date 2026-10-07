// Telegram webhook -> GitHub workflow_dispatch. Кнопка "Світло" = запустити svitlo.yml для того, хто натиснув.
const KB = { keyboard: [[{ text: "💡 Світло" }]], resize_keyboard: true, is_persistent: true };
const REPO = "Fizpop/svitlo";

const say = (env, chat_id, text) =>
  fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id, text, reply_markup: KB }),
  });

export default {
  async fetch(req, env) {
    if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET)
      return new Response("forbidden", { status: 403 });

    const m = (await req.json()).message;
    if (!m) return new Response("ok");
    const chat = String(m.chat.id);

    // CHAT_ID = список дозволених через кому: "111,222"
    if (!env.CHAT_ID.split(",").includes(chat)) {
      await say(env, chat, `Твій CHAT_ID: ${chat}\nПередай його власнику бота, щоб додав тебе.`);
    } else if (/^(\/svitlo|\/start|💡)/.test(m.text || "")) {
      const run = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/svitlo.yml/dispatches`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_TOKEN}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "svitlo-worker",
        },
        body: JSON.stringify({ ref: "main", inputs: { chat } }),
      });
      await say(env, chat, run.ok ? "Шукаю графік… ≈1 хв" : `❌ GitHub відповів ${run.status}`);
    }
    return new Response("ok");
  },
};
