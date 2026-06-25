// 12306 API Proxy for Cloudflare Workers
// Deploy: npx wrangler deploy / copy-paste to dash.cloudflare.com
// License: MIT

const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";
const HDR = { "User-Agent": UA, "Accept": "application/json,*/*", "Accept-Language": "zh-CN,zh;q=0.9", "Referer": "https://kyfw.12306.cn/otn/leftTicket/init" };

// Persistent across requests (same isolate)
let cookies = "";
let apiType = "leftTicket/queryZ";
let stations = null;
let stationRev = null;
let cookieTs = 0;

const SEAT_TYPES = [
  ["商务座",32,"9"],["一等座",31,"M"],["二等座",30,"O"],["特等座",25,"P"],
  ["高级软卧",21,"6"],["软卧",23,"4"],["动卧",33,"F"],["硬卧",28,"3"],
  ["软座",24,"2"],["硬座",29,"1"],["无座",26,"W"],
];

const HUB_LIST = ["徐州","商丘","合肥","南京","郑州","武汉","长沙","北京","上海","广州","西安","济南","南昌","石家庄","天津"];

// ─── Session ────────────────────────
async function initSession(force) {
  if (!force && cookies && Date.now() - cookieTs < 600_000) return;
  const resp = await fetch("https://kyfw.12306.cn/otn/leftTicket/init", {
    headers: { "User-Agent": UA, "Accept": "text/html,*/*", "Accept-Language": "zh-CN,zh;q=0.9" }
  });
  const sc = resp.headers.get("set-cookie");
  if (sc) cookies = sc.split(",").map(s => s.trim().split(";")[0]).filter(p => p.includes("=")).join("; ");
  const html = await resp.text();
  const m = html.match(/var CLeftTicketUrl = '([^']+)'/);
  if (m) apiType = m[1];
  cookieTs = Date.now();
}

// ─── Stations ───────────────────────
async function loadStations() {
  if (stations) return;
  const resp = await fetch("https://kyfw.12306.cn/otn/resources/js/framework/station_name.js", {
    headers: { "User-Agent": UA }
  });
  let raw = await resp.text();
  raw = raw.replace(/^[^@]*/, "");
  const map = {}, rev = {};
  for (const item of raw.split("@")) {
    const p = item.split("|");
    if (p.length < 6) continue;
    map[p[1]] = p[2]; rev[p[2]] = p[1];
  }
  stations = map; stationRev = rev;
}

function resolveStation(s) {
  if (stations[s]) return [s, stations[s]];
  if (stationRev[s]) return [stationRev[s], s];
  for (const [n, c] of Object.entries(stations)) {
    if (s.includes(n) || n.includes(s)) return [n, c];
  }
  return [null, null];
}

// ─── Parse ──────────────────────────
function parsePrice(f39) {
  if (!f39 || f39.length < 20) return {};
  const prices = {};
  for (let i = 10; i < f39.length; i += 10) {
    const c = f39.substring(i, i + 10);
    if (c.length < 7) continue;
    const fen = parseInt(c.substring(1, 7));
    if (isNaN(fen) || fen <= 0 || fen > 999999) continue;
    for (const [label, , sc] of SEAT_TYPES) {
      if (sc === c[0]) { prices[label] = Math.round(fen) / 100; break; }
    }
  }
  return prices;
}

function parseTrain(f) {
  const s = (i, d = "") => (i < f.length ? f[i] : d);
  const seats = {};
  for (const [label, idx] of SEAT_TYPES) {
    const v = s(idx);
    if (v && v !== "" && v !== "无" && v !== "*" && v !== "--") seats[label] = v;
  }
  return {
    train_code: s(3), train_no: s(2),
    from: stationRev[s(6)] || s(6), to: stationRev[s(7)] || s(7),
    depart: s(8), arrive: s(9), duration: s(10),
    can_buy: s(11), order_text: s(1),
    seats, prices: parsePrice(s(39)),
  };
}

// ─── Query ──────────────────────────
async function queryTickets(date, fromName, toName) {
  await initSession(false);
  await loadStations();
  const [fn, fc] = resolveStation(fromName);
  const [tn, tc] = resolveStation(toName);
  if (!fc || !tc) return null;

  const url = `https://kyfw.12306.cn/otn/${apiType}?leftTicketDTO.train_date=${date}&leftTicketDTO.from_station=${fc}&leftTicketDTO.to_station=${tc}&purpose_codes=ADULT`;

  for (let i = 0; i < 2; i++) {
    try {
      const headers = { ...HDR };
      if (cookies) headers["Cookie"] = cookies;
      const resp = await fetch(url, { headers });
      if (!resp.ok) { if (i < 1) { await initSession(true); continue; } return null; }
      const data = await resp.json();
      const rows = data?.data?.result || [];
      return { count: rows.length, trains: rows.map(r => parseTrain(r.split("|"))) };
    } catch { if (i < 1) { await initSession(true); continue; } return null; }
  }
  return null;
}

// ─── Transfer ───────────────────────
function durMin(d) { const p = d.split(":"); return parseInt(p[0]) * 60 + parseInt(p[1] || "0"); }

async function searchTransfers(date, from, to, hubs) {
  await initSession(false);
  await loadStations();
  const fromBase = from.replace(/[东南西北]$/, "");
  const toBase = to.replace(/[东南西北]$/, "");
  const fromVars = [from], toVars = [to];
  for (const n of Object.keys(stations)) {
    if (n !== from && n.startsWith(fromBase) && n !== to) fromVars.push(n);
    if (n !== to && n.startsWith(toBase) && n !== from) toVars.push(n);
  }

  const results = [];
  for (const hub of hubs) {
    // l1
    let l1Trains = [];
    for (const fv of fromVars) {
      const r = await queryTickets(date, fv, hub);
      if (r && r.trains.length) { l1Trains = r.trains; break; }
    }
    if (!l1Trains.length) continue;

    // l2
    let l2Trains = [];
    for (const tv of toVars) {
      const r = await queryTickets(date, hub, tv);
      if (r) l2Trains.push(...r.trains);
    }
    if (!l2Trains.length) continue;

    // match
    for (const t1 of l1Trains) {
      const am = durMin(t1.arrive);
      for (const t2 of l2Trains) {
        const dm = durMin(t2.depart);
        let gap = dm - am;
        if (gap < 0) gap += 1440;
        if (gap < 20 || gap > 1440) continue;
        const td = gap + durMin(t1.duration) + durMin(t2.duration);
        results.push({ transfer: hub, leg1: t1, leg2: t2, gap_min: gap, total_duration: td });
      }
    }
  }
  results.sort((a, b) => a.total_duration - b.total_duration);
  return results.slice(0, 300);
}

// ─── Handler ────────────────────────
export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
      }});
    }

    const cors = { "Access-Control-Allow-Origin": "*", "Content-Type": "application/json; charset=utf-8" };

    const path = url.pathname;
    if (path !== "/api/query") {
      return new Response(JSON.stringify({ error: "GET /api/query?from=...&to=...&date=...&hubs=..." }), { status: 404, headers: cors });
    }

    const params = url.searchParams;
    const from = params.get("from") || "";
    const to = params.get("to") || "";
    const date = params.get("date") || "";
    const hubsParam = params.get("hubs") || "";

    if (!from || !to || !date) {
      return new Response(JSON.stringify({ error: "缺少参数 from/to/date" }), { status: 400, headers: cors });
    }

    const hubs = hubsParam ? hubsParam.split(",").map(h => h.trim()).filter(Boolean) : HUB_LIST;

    try {
      const direct = await queryTickets(date, from, to);
      const transfers = await searchTransfers(date, from, to, hubs);

      return new Response(JSON.stringify({
        from, to, date,
        direct: direct ? { count: direct.count, trains: direct.trains } : null,
        transfers: { checked_hubs: hubs.length, found: transfers.length, transfers },
      }), { headers: cors });
    } catch (e) {
      return new Response(JSON.stringify({ error: String(e) }), { status: 500, headers: cors });
    }
  }
};
