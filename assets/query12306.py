#!/usr/bin/env python3
"""12306 票据检索 — 直达 + 中转一站式查询 + 表格化输出"""
import sys, json, re, time, http.cookiejar, urllib.request, urllib.parse, ssl
from datetime import datetime, timedelta

# ─── 会话管理 ──────────────────────────────────────
CTX = ssl.create_default_context()
CJ = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(CJ),
    urllib.request.HTTPSHandler(context=CTX),
)
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
_SESSION_READY = False; API_TYPE = None

def _init_session():
    global _SESSION_READY, API_TYPE
    if _SESSION_READY: return
    try:
        html = OPENER.open(urllib.request.Request(
            'https://kyfw.12306.cn/otn/leftTicket/init',
            headers={'User-Agent': UA, 'Accept': 'text/html,*/*', 'Accept-Language': 'zh-CN,zh;q=0.9'}
        ), timeout=12).read().decode('utf-8-sig')
        m = re.search(r"var CLeftTicketUrl = '([^']+)'", html)
        if m: API_TYPE = m.group(1)
    except: pass
    if not API_TYPE: API_TYPE = 'leftTicket/queryZ'
    _SESSION_READY = True

def _get(url, timeout=15):
    _init_session()
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json,*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9', 'Referer': 'https://kyfw.12306.cn/otn/leftTicket/init'})
    return json.loads(OPENER.open(req, timeout=timeout).read().decode('utf-8-sig'))

# ─── 站点数据 ──────────────────────────────────────
STATIONS = {}; STATION_REV = {}; STATION_BY_PINYIN = {}

def load_stations(path=None):
    global STATIONS, STATION_REV, STATION_BY_PINYIN
    raw = open(path, encoding='utf-8').read() if path else urllib.request.urlopen(
        urllib.request.Request('https://kyfw.12306.cn/otn/resources/js/framework/station_name.js',
        headers={'User-Agent': UA}), context=CTX, timeout=10).read().decode('utf-8')
    raw = re.sub(r'^[^@]*', '', raw)
    for item in raw.split('@'):
        p = item.split('|')
        if len(p) < 6: continue
        STATIONS[p[1]] = p[2]; STATION_REV[p[2]] = p[1]; STATION_BY_PINYIN[p[3]] = p[1]

def resolve_station(s):
    if s in STATIONS: return s, STATIONS[s]
    if s in STATION_REV: return STATION_REV[s], s
    py = s.lower().replace(' ','')
    if py in STATION_BY_PINYIN: return STATION_BY_PINYIN[py], STATIONS.get(STATION_BY_PINYIN[py],'')
    for n,c in STATIONS.items():
        if s in n or n in s: return n,c
    return None,None

# ─── 余票查询 + 价格解析 ──────────────────────────
SEAT_TYPES = [
    ('商务座',32,'9'),('特等座',25,'P'),('一等座',31,'M'),('二等座',30,'O'),
    ('高级软卧',21,'6'),('软卧',23,'4'),('动卧',33,'F'),('硬卧',28,'3'),
    ('软座',24,'2'),('硬座',29,'1'),('无座',26,'W'),
]

def parse_price_field(field39):
    if not field39 or len(field39) < 20: return {}
    prices = {}
    for i in range(10, len(field39), 10):
        chunk = field39[i:i+10]
        if len(chunk) < 7: continue
        try: price_fen = int(chunk[1:7])
        except: continue
        if price_fen <= 0 or price_fen > 999999: continue
        for label, idx, sc in SEAT_TYPES:
            if sc == chunk[0]:
                prices[label] = round(price_fen / 100, 1); break
    return prices

def parse_train(raw):
    f = raw.split('|')
    seats = {}
    for label, idx, _ in SEAT_TYPES:
        if idx < len(f):
            v = f[idx]
            if v and v not in ('', '无', '*', '--'):
                seats[label] = v
    prices = parse_price_field(f[39] if len(f) > 39 else '')
    def s(i,d=''): return f[i] if i < len(f) else d
    return {
        'train_code': s(3), 'train_no': s(2),
        'from': STATION_REV.get(s(6), s(6)),
        'to': STATION_REV.get(s(7), s(7)),
        'depart': s(8), 'arrive': s(9), 'duration': s(10),
        'can_buy': s(11), 'date': s(13), 'order_text': s(1),
        'seats': seats, 'prices': prices,
    }

def query_tickets(date, from_name, to_name):
    _init_session()
    fn,fc = resolve_station(from_name); tn,tc = resolve_station(to_name)
    if not fc or not tc: return {'error': f'站点未识别: {from_name}→{to_name}'}
    params = urllib.parse.urlencode({'leftTicketDTO.train_date':date,'leftTicketDTO.from_station':fc,
        'leftTicketDTO.to_station':tc,'purpose_codes':'ADULT'})
    try: data = _get(f'https://kyfw.12306.cn/otn/{API_TYPE}?{params}')
    except Exception as e: return {'error': str(e), 'from':fn, 'to':tn, 'date':date}
    rows = data.get('data',{}).get('result',[]) or []
    return {'from':fn, 'to':tn, 'date':date, 'count':len(rows), 'trains':[parse_train(r) for r in rows]}

# ─── 中转检索 ──────────────────────────────────────
HUB_STATIONS = [
    '北京','上海','广州','深圳','成都','重庆','武汉','南京','杭州','西安',
    '郑州','长沙','济南','青岛','天津','沈阳','哈尔滨','长春','大连',
    '昆明','贵阳','南宁','兰州','乌鲁木齐','太原','石家庄','呼和浩特',
    '合肥','福州','南昌','厦门','苏州','无锡','宁波','温州','徐州',
    '洛阳','宜昌','襄阳','珠海','佛山','东莞','惠州','中山',
    '海口','三亚','拉萨','西宁','银川','九江',
]

def search_transfers(date, from_name, to_name, min_gap=20, max_gap=240, max_results=10, hubs=None):
    """暴力中转检索 — 自动展开同城多站"""
    fn,fc = resolve_station(from_name); tn,tc = resolve_station(to_name)
    if not fc or not tc: return {'error': f'站点未识别: {from_name}→{to_name}'}
    
    # 自动展开同城多站: '徐州'→['徐州','徐州东'], '兰考'→['兰考','兰考南']
    def expand(name, exclude=set()):
        found = [name]
        for sn in STATIONS:
            if sn.startswith(name) and sn != name and sn not in exclude:
                found.append(sn)
        return found
    
    from_variants = expand(fn)
    to_variants = expand(tn)
    
    raw_hubs = hubs or HUB_STATIONS
    hub_list, seen_codes = [], set()
    for h in raw_hubs:
        for eh in expand(h, exclude={fn,tn}):
            ec = STATIONS.get(eh)
            if ec and ec not in seen_codes:
                hub_list.append(eh); seen_codes.add(ec)
    
    results, errors, checked = [], [], 0
    for hn in hub_list:
        hc = STATIONS.get(hn); checked += 1
        if not hc: continue
        # 合并所有出发站变体（兰考+兰考南）的车次
        l1_trains, l2_trains = [], []
        for fv in from_variants:
            l1 = query_tickets(date, fv, hn)
            if 'error' not in l1:
                l1_trains.extend(l1.get('trains',[]))
            time.sleep(0.3)
        if not l1_trains: continue
        for tv in to_variants:
            l2 = query_tickets(date, hn, tv)
            if 'error' not in l2:
                l2_trains.extend(l2.get('trains',[]))
            time.sleep(0.3)
        if not l2_trains: continue
        time.sleep(0.3)
        for t1 in l1_trains:
            if t1.get('can_buy')!='Y' or t1.get('order_text')!='预订': continue
            arr = t1.get('arrive','')
            if ':' not in arr: continue
            am = int(arr[:2])*60+int(arr[3:])
            for t2 in l2_trains:
                if t2.get('can_buy')!='Y' or t2.get('order_text')!='预订': continue
                dep = t2.get('depart','')
                if ':' not in dep: continue
                dm = int(dep[:2])*60+int(dep[3:]); gap = dm-am
                if min_gap <= gap <= max_gap:
                    dur_total = _calc_total(t1,t2,gap)
                    # 去重: 同一组车次只保留换乘最短的
                    key = (t1['train_code'], t2['train_code'], hn)
                    existing = next((r for r in results if (r['leg1']['train_code'],r['leg2']['train_code'],r['transfer'])==key), None)
                    if existing:
                        if gap < existing['gap_min']:
                            existing.update({'gap_min':gap,'total_duration':dur_total,'leg1':t1,'leg2':t2})
                    else:
                        results.append({'transfer':hn,'leg1':t1,'leg2':t2,'gap_min':gap,'total_duration':dur_total})
    results.sort(key=lambda x: x['total_duration'] or 9999)
    return {'from':fn,'to':tn,'date':date,'checked_hubs':checked,'found':len(results),'errors':len(errors),'transfers':results[:max_results]}

def _calc_total(t1,t2,gap=0):
    """全程耗时(分) = 第1程历时 + 换乘等待 + 第2程历时"""
    try:
        def pd(d):
            p=d.split(':'); return int(p[0])*60+int(p[1])
        return pd(t1['duration']) + gap + pd(t2['duration'])
    except: return None

# ─── 格式化输出 紧凑表格样式 ──────────────
_SEAT_KEYS = ['商务座','特等座','一等座','二等座','高级软卧','软卧','动卧','硬卧','软座','硬座','无座']

def _seat_str(seats, prices):
    items = []
    for lb in _SEAT_KEYS:
        v = seats.get(lb, '')
        if not v or v in ('','无','*','--'): continue
        s = '有' if v=='有' else f'{v}张'
        p = prices.get(lb)
        items.append(f'{lb}{s}' + (f'¥{p}' if p else ''))
    return '  '.join(items) if items else '无票'

def _dur_str(d):
    if not d or d == '99:59': return '—'
    return d

def print_direct(data):
    if 'error' in data: print(f'错误: {data["error"]}'); return
    print(f'\n  {data["from"]}→{data["to"]}  {data["date"]}  共{data["count"]}趟')
    print(f'  {"─"*56}')
    buyable = [t for t in data['trains'] if t['can_buy']=='Y' and t['order_text']=='预订']
    others = [t for t in data['trains'] if not (t['can_buy']=='Y' and t['order_text']=='预订')]
    for t in buyable:
        f = t['from']; to = t['to']
        s = _seat_str(t['seats'], t.get('prices',{}))
        d = _dur_str(t['duration'])
        print(f'  ✓ {t["train_code"]:<6s} {f}→{to}  {t["depart"]}→{t["arrive"]}  {d:>5s}  {s}')
    if others:
        print(f'  ─ 以下无票 ─')
        for t in others:
            print(f'  ✗ {t["train_code"]:<6s} {t["from"]}→{t["to"]}  {t["depart"]}→{t["arrive"]}')

def print_transfers(data):
    if 'error' in data: print(f'错误: {data["error"]}'); return
    print(f'\n  中转 {data["from"]}→{data["to"]}  {data["date"]}  经{data["checked_hubs"]}站查得{data["found"]}方案')
    print(f'  {"─"*56}')
    for i,s in enumerate(data['transfers'],1):
        t1,t2 = s['leg1'],s['leg2']
        td = s.get('total_duration')
        td_str = f'{td//60}h{td%60}m' if td else '—'
        print(f'  ─ 方案{i}: 经{s["transfer"]}换乘 (等{s["gap_min"]}分 全程{td_str})')
        d1 = _dur_str(t1['duration'])
        d2 = _dur_str(t2['duration'])
        s1 = _seat_str(t1['seats'], t1.get('prices',{}))
        s2 = _seat_str(t2['seats'], t2.get('prices',{}))
        print(f'    {t1["train_code"]:<6s} {t1["depart"]}→{t1["arrive"]}  {d1:>5s}  {s1}')
        print(f'    {t2["train_code"]:<6s} {t2["depart"]}→{t2["arrive"]}  {d2:>5s}  {s2}')

def print_combined(dd, dt):
    print_direct(dd)
    if 'error' not in dt and dt.get('found',0) > 0:
        print_transfers(dt)

# ─── CLI ────────────────────────────────────────────
def main():
    import argparse
    p = argparse.ArgumentParser(description='12306 票据检索 · 直达+中转一站式')
    p.add_argument('mode', choices=['direct','transfer','all','stations'], default='all', nargs='?',
        help='all=直达+中转(direct+transfer)一站输出')
    p.add_argument('-d','--date'); p.add_argument('-f','--from',dest='from_s'); p.add_argument('-t','--to',dest='to_s')
    p.add_argument('--hubs'); p.add_argument('--min-gap',type=int,default=20); p.add_argument('--max-gap',type=int,default=360)
    p.add_argument('--max-results',type=int,default=10); p.add_argument('--station-file'); p.add_argument('--json',action='store_true')
    args = p.parse_args(); load_stations(args.station_file)

    if args.mode == 'stations':
        q = args.from_s or ''
        m = [(n,c) for n,c in STATIONS.items() if q in n]
        for n,c in (m if q else list(STATIONS.items())[:50]): print(f'  {n} ({c})')
        print(f'共{len(STATIONS)}个站点'); return

    if not args.date or not args.from_s or not args.to_s:
        print('错误: 需要 --date, --from, --to'); sys.exit(1)

    if args.mode == 'direct':
        d = query_tickets(args.date, args.from_s, args.to_s)
        if args.json: print(json.dumps(d, ensure_ascii=False, indent=2))
        else: print_direct(d)

    elif args.mode == 'transfer':
        hubs = args.hubs.split(',') if args.hubs else None
        d = search_transfers(args.date, args.from_s, args.to_s,
            min_gap=args.min_gap, max_gap=args.max_gap, max_results=args.max_results, hubs=hubs)
        if args.json: print(json.dumps(d, ensure_ascii=False, indent=2))
        else:
            _print_header(f'中转 {d["from"]}→{d["to"]}  {d["date"]}')
            if d.get('found',0)>0: _print_transfers(d)
            else: print('  未找到可行中转方案')

    elif args.mode == 'all':
        # 直达
        d_direct = query_tickets(args.date, args.from_s, args.to_s)
        # 中转（智能选hubs或默认）
        hubs = args.hubs.split(',') if args.hubs else None
        d_transfer = search_transfers(args.date, args.from_s, args.to_s,
            min_gap=args.min_gap, max_gap=args.max_gap, max_results=args.max_results, hubs=hubs)
        if args.json:
            print(json.dumps({'direct':d_direct,'transfer':d_transfer}, ensure_ascii=False, indent=2))
        else:
            print_combined(d_direct, d_transfer)

if __name__ == '__main__':
    main()
