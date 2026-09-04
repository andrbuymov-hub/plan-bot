/**
 * Прокси для Telegram Bot API.
 * Cloudflare Dashboard → Workers → Create → вставить код → Deploy.
 * URL worker'а впишите в .env как TELEGRAM_API_URL
 */
export default {
  async fetch(request, env) {
    const secret = env.BOT_SECRET || "plan-bot-secret-change-me";
    if (request.headers.get("X-Bot-Secret") !== secret) {
      return new Response("Forbidden", { status: 403 });
    }
    const url = new URL(request.url);
    const target =
      "https://api.telegram.org" + url.pathname + url.search;
    const headers = new Headers(request.headers);
    headers.delete("X-Bot-Secret");
    headers.delete("Host");
    return fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
    });
  },
};
