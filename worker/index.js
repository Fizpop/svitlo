// Telegram webhook -> GitHub workflow_dispatch. Кнопка "Світло" = запустити svitlo.yml.
const KB = { keyboard: [[{ text: "💡 Світло" }]], resize_keyboard: true, is_persistent: true };
const REPO = "Fizpop/svitlo";

export default {
  async fetch(req, env) {
    if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET)
      return new Response("forbidden", { status: 403 });

    const m = (await req.json()).message;
    if (m && String(m.chat.id) === env.CHAT_ID && /^(\/svitlo|\/start|💡)/.test(m.text || "")) {
      const run = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/svitlo.yml/dispatches`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_TOKEN}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "svitlo-worker",
        },
        body: JSON.stringify({ ref: "main" }),
      });
      await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: m.chat.id,
          text: run.ok ? "Шукаю графік… ≈1 хв" : `❌ GitHub відповів ${run.status}`,
          reply_markup: KB,
        }),
      });
    }
    return new Response("ok");
  },
};
