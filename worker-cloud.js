/** Облачный бот: webhook + cron 18:00 / 9:00 + память чата с ИИ (Workers AI + D1). */
const MORNING = "Всем доброе утро, господа!\nХорошего рабочего дня";

const EXTRACT_PROMPT =
  "Ты — фильтр памяти рабочей группы в мессенджере. Выдели из сообщения ТОЛЬКО конкретные важные факты: " +
  "даты и сроки, адреса и объекты, номера телефонов и договоров, договорённости и назначения (кто что обещал), " +
  "задачи и изменения планов. НЕ сохраняй: приветствия, шутки, эмоции, вопросы, обсуждения, общую болтовню. " +
  "Если важных фактов нет — ответь ровно одним словом: НЕТ. " +
  "Иначе выведи каждый факт отдельной короткой строкой, без нумерации и пояснений.";

const ANSWER_PROMPT =
  "Ты — бот-помощник в рабочем чате. Тебе даны: ПАМЯТЬ (важные факты из переписки) и ПОСЛЕДНИЕ СООБЩЕНИЯ. " +
  "Отвечай на вопрос кратко (1-4 предложения), по-русски, только на основе этой информации. " +
  "Если информации нет — так и скажи: «В памяти этого нет». Не выдумывай.";

// Дневной лимит извлечения фактов (бесплатный тариф Workers AI ~10k нейронов/день)
const EXTRACT_DAILY_LIMIT = 300;
const MESSAGES_KEEP = 20000;

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

// ===== Память чата =====

function displayName(from) {
  if (!from) return "неизвестный";
  if (from.username) return "@" + from.username;
  return from.first_name || String(from.id);
}

async function aiRun(env, messages, maxTokens) {
  const model = env.AI_MODEL || "@cf/meta/llama-3.1-8b-instruct";
  const res = await env.AI.run(model, { messages, max_tokens: maxTokens });
  return ((res && res.response) || "").trim();
}

async function saveMessage(env, msg) {
  try {
    const text = msg.text || "";
    await env.DB.prepare(
      `INSERT OR REPLACE INTO messages (chat_id, msg_id, user_id, username, first_name, text, text_s, ts)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
    ).bind(
      msg.chat.id, msg.message_id, (msg.from && msg.from.id) || 0,
      (msg.from && msg.from.username) || "", displayName(msg.from),
      text, text.toLowerCase(), Math.floor(Date.now() / 1000)
    ).run();
    // изредка подрезаем историю, чтобы база не росла бесконечно
    if (Math.random() < 0.02) {
      await env.DB.prepare(
        `DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY id DESC LIMIT ${MESSAGES_KEEP})`
      ).run();
    }
  } catch (e) {
    console.error("saveMessage:", e);
  }
}

async function getBotUid(env) {
  let uid = await env.CONFIG_KV.get("bot_uid");
  if (!uid) {
    const me = await tg(env, "getMe", {});
    if (!me || !me.ok) return null;
    uid = String(me.result.id);
    await env.CONFIG_KV.put("bot_uid", uid);
  }
  return Number(uid);
}

async function isReplyToBot(env, msg) {
  const r = msg.reply_to_message;
  if (!r || !r.from) return false;
  const botUid = await getBotUid(env);
  return botUid !== null && r.from.id === botUid;
}

async function extractFacts(env, msg) {
  const text = (msg.text || "").trim();
  // шум пропускаем без запроса к ИИ
  if (text.length < 12) return;
  // дневной лимит ИИ-вызовов
  const key = `ai_cnt:${todayKey("UTC")}`;
  const cnt = Number((await env.CONFIG_KV.get(key)) || 0);
  if (cnt >= EXTRACT_DAILY_LIMIT) return;
  await env.CONFIG_KV.put(key, String(cnt + 1), { expirationTtl: 172800 });
  try {
    const out = await aiRun(env, [
      { role: "system", content: EXTRACT_PROMPT },
      { role: "user", content: `Автор: ${displayName(msg.from)}\nСообщение: ${text}` },
    ], 150);
    if (!out) return;
    const author = displayName(msg.from);
    const now = Math.floor(Date.now() / 1000);
    for (const line of out.split("\n").map(s => s.trim()).filter(Boolean).slice(0, 3)) {
      if (/^(нет|no)/i.test(line)) continue;
      const fact = line.slice(0, 300);
      await env.DB.prepare(
        "INSERT INTO facts (chat_id, fact, fact_s, source, ts) VALUES (?, ?, ?, ?, ?)"
      ).bind(msg.chat.id, fact, fact.toLowerCase(), author, now).run();
    }
  } catch (e) {
    console.error("extractFacts:", e);
  }
}

async function relevantFacts(env, chatId, question) {
  const words = [...new Set((question.toLowerCase().match(/[\p{L}\p{N}]{4,}/gu) || []).slice(0, 6))];
  let byWords = [];
  if (words.length) {
    const likes = words.map(() => "fact_s LIKE ?").join(" OR ");
    const r = await env.DB.prepare(
      `SELECT id, fact, source, ts FROM facts WHERE chat_id = ? AND (${likes}) ORDER BY id DESC LIMIT 25`
    ).bind(chatId, ...words.map(w => `%${w}%`)).all();
    byWords = r.results || [];
  }
  const r2 = await env.DB.prepare(
    "SELECT id, fact, source, ts FROM facts WHERE chat_id = ? ORDER BY id DESC LIMIT 15"
  ).bind(chatId).all();
  const seen = new Set();
  const out = [];
  for (const f of [...byWords, ...(r2.results || [])]) {
    if (!seen.has(f.id)) { seen.add(f.id); out.push(f); }
  }
  return out.slice(0, 30);
}

async function recentMessages(env, chatId, limit) {
  const r = await env.DB.prepare(
    "SELECT first_name, text, ts FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?"
  ).bind(chatId, limit).all();
  return (r.results || []).reverse();
}

function fmtTs(ts) {
  return new Date(ts * 1000).toLocaleString("ru-RU", { timeZone: "Asia/Novokuznetsk", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

async function answerQuestion(env, msg) {
  const botName = (env.BOT_USERNAME || "Vafikk_bot").toLowerCase();
  const question = (msg.text || "")
    .replace(new RegExp("@" + botName, "gi"), "")
    .replace(/^\/ask\S*\s*/i, "")
    .trim();
  if (!question) return;
  try {
    const [facts, recent] = await Promise.all([
      relevantFacts(env, msg.chat.id, question),
      recentMessages(env, msg.chat.id, 20),
    ]);
    let context = "";
    if (facts.length) {
      context += "ПАМЯТЬ (факты из переписки):\n" + facts.map(f => `- [${fmtTs(f.ts)}] ${f.fact} (${f.source})`).join("\n") + "\n\n";
    }
    if (recent.length) {
      context += "ПОСЛЕДНИЕ СООБЩЕНИЯ:\n" + recent.map(m => `[${fmtTs(m.ts)}] ${m.first_name}: ${m.text}`).join("\n").slice(0, 3000) + "\n\n";
    }
    const answer = await aiRun(env, [
      { role: "system", content: ANSWER_PROMPT },
      { role: "user", content: (context || "Память пока пуста.\n\n") + "Вопрос: " + question },
    ], 300);
    await send(env, msg.chat.id, answer || "Не смог сформулировать ответ, попробуй ещё раз.", msg.message_thread_id);
  } catch (e) {
    console.error("answerQuestion:", e);
    await send(env, msg.chat.id, "⚠️ Ошибка при обработке вопроса, попробуй ещё раз.", msg.message_thread_id).catch(() => {});
  }
}

// Любое некомандное сообщение: сохранить → ответить или вытащить факты
async function processUpdate(env, msg) {
  const text = (msg.text || "").trim();
  if (text.startsWith("/")) {
    await handleCmd(env, msg);
    return;
  }
  if (!text) return; // стикеры, фото и прочее — не запоминаем
  await saveMessage(env, msg);
  const mentioned = text.toLowerCase().includes("@" + (env.BOT_USERNAME || "Vafikk_bot").toLowerCase());
  if (mentioned || (await isReplyToBot(env, msg))) {
    await answerQuestion(env, msg);
    return;
  }
  await extractFacts(env, msg);
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
  if (cmd === "/ask") {
    return answerQuestion(env, msg);
  }
  if (cmd === "/find" || cmd === "/найди") {
    const q = text.split(/\s/).slice(1).join(" ").trim().toLowerCase();
    if (!q) return reply("Использование: /найди слово");
    const r = await env.DB.prepare(
      "SELECT first_name, text, ts FROM messages WHERE chat_id = ? AND text_s LIKE ? ORDER BY id DESC LIMIT 10"
    ).bind(chatId, `%${q}%`).all();
    if (!r.results || !r.results.length) return reply("В памяти ничего не нашлось.");
    return reply(r.results.reverse().map(m => `[${fmtTs(m.ts)}] ${m.first_name}: ${m.text}`).join("\n").slice(0, 3500));
  }
  if (cmd === "/facts" || cmd === "/факты") {
    const r = await env.DB.prepare(
      "SELECT id, fact, ts FROM facts WHERE chat_id = ? ORDER BY id DESC LIMIT 10"
    ).bind(chatId).all();
    if (!r.results || !r.results.length) return reply("Память пока пуста.");
    return reply(r.results.reverse().map(f => `${f.id}) [${fmtTs(f.ts)}] ${f.fact}`).join("\n").slice(0, 3500));
  }
  if (cmd === "/forget" || cmd === "/забыть") {
    const arg = text.split(/\s/).slice(1).join(" ").trim();
    if (!arg) return reply("Использование: /забыть N (номер факта) или /забыть всё");
    if (arg.toLowerCase() === "всё" || arg.toLowerCase() === "все") {
      await env.DB.prepare("DELETE FROM facts WHERE chat_id = ?").bind(chatId).run();
      return reply("Память очищена.");
    }
    const id = Number(arg);
    if (!Number.isInteger(id)) return reply("Нужно число — номер факта (см. /факты) или «всё».");
    await env.DB.prepare("DELETE FROM facts WHERE chat_id = ? AND id = ?").bind(chatId, id).run();
    return reply(`Факт ${id} удалён (если существовал).`);
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

  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/" ) return new Response("plan-bot cloud ok");

    if (request.method === "POST" && url.pathname === `/webhook/${env.BOT_TOKEN}`) {
      const data = await request.json();
      const msg = data.message || data.edited_message;
      if (msg) {
        const e = await loadEnv(env);
        // отвечаем Telegram мгновенно, вся работа — в фоне (иначе ретраи вебхука задвоят ответы)
        ctx.waitUntil(processUpdate(e, msg).catch(err => console.error("processUpdate:", err)));
      }
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
