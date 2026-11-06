const REPO = "hex-forge/effective-meme";
const WORKFLOW = "seat-check.yml";
const LIVE_BRANCH = "main"; // change to "main" after you merge
const STATE_BRANCH = "main";                // where the cron commits state.json
const STATE_PATH = "state.json";

async function reply(env, chatId, text) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
  console.log("telegram:", r.status, await r.text());
}

function formatState(s) {
  const h = Array.isArray(s.history) ? s.history : [];
  const last = h[h.length - 1];
  const prev = h[h.length - 2];
  const sign = (n) => (n > 0 ? "+" : "") + n;

  const lines = [`🚆 Seats available: ${s.last_available}`];

  if (last?.timestamp) {
    const when = String(last.timestamp).replace("T", " ").slice(0, 16);
    const diff = prev ? ` (${sign(last.available - prev.available)})` : "";
    lines.push(`Last change: ${when}${diff}`);
  }

  const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
  const old = [...h].reverse().find((e) => Date.parse(e.timestamp + "Z") < weekAgo) ?? h[0];
  if (old) {
    lines.push(`Past 7 days: ${sign(s.last_available - old.available)} (was ${old.available})`);
  }

  return lines.join("\n");
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("ok");

    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET)
      return new Response("forbidden", { status: 403 });

    const update = await request.json();
    const msg = update.message;
    if (!msg?.text) return new Response("ok");
    if (String(msg.chat.id) !== env.ALLOWED_CHAT_ID) return new Response("ok");

    const cmd = msg.text.trim().split(/\s+/)[0].split("@")[0].toLowerCase();
    const gh = {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "User-Agent": "seat-hook",
    };

    if (cmd === "/seat") {
      const r = await fetch(
        `https://api.github.com/repos/${REPO}/contents/${STATE_PATH}?ref=${STATE_BRANCH}`,
        { headers: { ...gh, Accept: "application/vnd.github.raw+json" } }
      );
      console.log("state fetch:", r.status);

      if (!r.ok) {
        await reply(env, msg.chat.id, `Could not read the last check (GitHub ${r.status}).`);
      } else {
        try {
          const state = await r.json();
          await reply(env, msg.chat.id, formatState(state));
        } catch (e) {
          console.log("format error:", String(e));
          await reply(env, msg.chat.id, "Error reading state: " + String(e));
        }
      }
    } else if (["/seat_live", "/seat-live", "/seatlive"].includes(cmd)) {
      await reply(env, msg.chat.id, "Checking live, this takes about a minute…");
      const r = await fetch(
        `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
        {
          method: "POST",
          headers: { ...gh, Accept: "application/vnd.github+json" },
          body: JSON.stringify({ ref: LIVE_BRANCH, inputs: { mode: "reply" } }),
        }
      );
      console.log("dispatch:", r.status, await r.text());
    }

    return new Response("ok");
  },
};