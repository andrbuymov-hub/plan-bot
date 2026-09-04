/** Облачный бот: webhook + cron 18:00 / 9:00 */
const MORNING = "Всем доброе утро, господа!\nХорошего рабочего дня";

async function tg(env, method, body) {
  const r = await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

async function send(env, chatId, text, topicId) {
  const body = { chat_id: chatId, text };
  if (topicId) body.message_thread_id = Number(topicId);
  return tg(env, "sendMessage", body);
}

function parseCsv(text) {
  const rows = [];
  let row = [], field = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else q = false;
      } else field += c;
    } else if (c === '"') q = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n" || (c === "\r" && text[i + 1] === "\n")) {
      if (c === "\r") i++;
      row.push(field); field = "";
      rows.push(row); row = [];
    } else field += c;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  return rows;
}

async function getPlan(env, dateStr) {
  const url = `https://docs.google.com/spreadsheets/d/${env.SHEET_ID}/gviz/tq?tqx=out:csv&gid=${env.SHEET_GID}`;
  const csv = await (await fetch(url)).text();
  const rows = parseCsv(csv);
  const items = [];
  for (let r = 0; r < rows.length; r++) {
    for (let c = 0; c < rows[r].length; c++) {
      if (rows[r][c] !== dateStr) continue;
      const addrCol = c + 1;
      for (let rr = r + 1; rr < rows.length; rr++) {
        const names = (rows[rr][c] || "").trim();
        if (/^\d{2}\.\d{2}\.\d{4}$/.test(names)) break;
        const addr = (rows[rr][addrCol] || "").trim();
        if (!names && !addr) continue;
        items.push({ names, addr });
      }
      return { date: dateStr, items };
    }
  }
  return { date: dateStr, items };
}

function buildPlain(plan) {
  const lines = [`На ${plan.date}`];
  for (const it of plan.items) {
    if (it.names && it.addr) lines.push(`${it.names} - ${it.addr}`);
    else if (it.names) lines.push(it.names);
    else if (it.addr) lines.push(it.addr);
  }
  if (lines.length === 1) lines.push("(нет данных в таблице)");
  return lines.join("\n");
}

function tomorrowStr(tz) {
  const fmt = new Intl.DateTimeFormat("ru-RU", { timeZone: tz, day: "2-digit", month: "2-digit", year: "numeric" });
  const p = fmt.formatToParts(new Date(Date.now() + 86400000));
  const d = Object.fromEntries(p.filter(x => x.type !== "literal").map(x => [x.type, x.value]));
  return `${d.day}.${d.month}.${d.year}`;
}

function todayKey(tz) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(new Date());
}

async function eveningJob(env) {
  const chat = env.CHAT_PLANNING_ID;
  if (!chat) return "no planning chat";
  const plan = await getPlan(env, tomorrowStr(env.TIMEZONE || "Asia/Novokuznetsk"));
  await send(env, chat, buildPlain(plan), env.PLANNING_TOPIC_ID);
  return `evening ok ${plan.date}`;
}

async function morningJob(env) {
  const chat = env.CHAT_MORNING_ID;
  if (!chat) return "no morning chat";
  const tz = env.TIMEZONE || "Asia/Novokuznetsk";
  const wd = new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short" }).format(new Date());
  if (wd === "Sat" || wd === "Sun") return "weekend skip";
  await send(env, chat, MORNING, env.MORNING_TOPIC_ID);
  return "morning ok";
}

async function handleCmd(env, msg) {
  const text = msg.text || "";
  if (!text.startsWith("/")) return;
  const chatId = msg.chat.id;
  const topic = msg.message_thread_id;
  const cmd = text.split(/\s/)[0].split("@")[0].toLowerCase();
  const reply = (t) => send(env, chatId, t, topic);

  if (cmd === "/setplanning") {
    await env.CONFIG_KV.put("planning_chat_id", String(chatId));
    if (topic) await env.CONFIG_KV.put("planning_topic_id", String(topic));
    return reply(`Планирование: chat ${chatId}${topic ? ` topic ${topic}` : ""}`);
  }
  if (cmd === "/setmorning") {
    await env.CONFIG_KV.put("morning_chat_id", String(chatId));
    if (topic) await env.CONFIG_KV.put("morning_topic_id", String(topic));
    return reply(`Утро: chat ${chatId}${topic ? ` topic ${topic}` : ""}`);
  }
  if (cmd === "/chatid") {
    return reply(`chat ${chatId}${topic ? ` topic ${topic}` : ""}`);
  }
  if (cmd === "/planplain") {
    const plan = await getPlan(env, tomorrowStr(env.TIMEZONE || "Asia/Novokuznetsk"));
    return reply(buildPlain(plan));
  }
}

async function loadEnv(env) {
  const e = { ...env };
  const kv = env.CONFIG_KV;
  if (!kv) return e;
  const pc = await kv.get("planning_chat_id");
  const mc = await kv.get("morning_chat_id");
  const pt = await kv.get("planning_topic_id");
  const mt = await kv.get("morning_topic_id");
  if (pc) e.CHAT_PLANNING_ID = pc;
  if (mc) e.CHAT_MORNING_ID = mc;
  if (pt) e.PLANNING_TOPIC_ID = pt;
  if (mt) e.MORNING_TOPIC_ID = mt;
  return e;
}

export default {
  async scheduled(event, env) {
    const e = await loadEnv(env);
    if (event.cron === "0 11 * * *") await eveningJob(e);
    if (event.cron === "0 2 * * 1-5") await morningJob(e);
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/" ) return new Response("plan-bot cloud ok");

    if (request.method === "POST" && url.pathname === `/webhook/${env.BOT_TOKEN}`) {
      const e = await loadEnv(env);
      const data = await request.json();
      const msg = data.message || data.edited_message;
      if (msg) await handleCmd(e, msg);
      return new Response("ok");
    }

    if (url.pathname === "/cron/evening" && request.headers.get("Authorization") === `Bearer ${env.CRON_SECRET}`) {
      return new Response(await eveningJob(await loadEnv(env)));
    }
    if (url.pathname === "/cron/morning" && request.headers.get("Authorization") === `Bearer ${env.CRON_SECRET}`) {
      return new Response(await morningJob(await loadEnv(env)));
    }

    return new Response("not found", { status: 404 });
  },
};
