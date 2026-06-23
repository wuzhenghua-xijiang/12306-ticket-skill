#!/usr/bin/env python3
"""12306 票据检索 — 直达 + 中转一站式查询 + 表格化输出"""
import sys, json, re, time, http.cookiejar, urllib.request, urllib.parse, ssl
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── 会话管理 ──────────────────────────────────────
CTX = ssl.create_default_context()
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

class Session:
    """线程安全: 每个线程持有独立Session实例"""
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=CTX),
        )
        self.ready = False; self.api_type = None

    def init(self, force=False):
        if self.ready and not force: return
        if force: self.cj.clear()
        try:
            html = self.opener.open(urllib.request.Request(
                'https://kyfw.12306.cn/otn/leftTicket/init',
                headers={'User-Agent': UA, 'Accept': 'text/html,*/*', 'Accept-Language': 'zh-CN,zh;q=0.9'}
            ), timeout=12).read().decode('utf-8-sig')
            m = re.search(r"var CLeftTicketUrl = '([^']+)'", html)
            if m: self.api_type = m.group(1)
        except: pass
        if not self.api_type: self.api_type = 'leftTicket/queryZ'
        self.ready = True

_DEFAULT = None
def _sess():
    global _DEFAULT
    if _DEFAULT is None: _DEFAULT = Session()
    return _DEFAULT

def _init_session(force=False):
    _sess().init(force)

def _get(url, timeout=8, session=None):
    """GET with auto-retry. session=None 用全局单例，线程场景传入独立Session"""
    sess = session or _sess()
    sess.init()
    headers = {'User-Agent': UA, 'Accept': 'application/json,*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9', 'Referer': 'https://kyfw.12306.cn/otn/leftTicket/init'}
    for attempt in range(3):
        try:
            raw = sess.opener.open(urllib.request.Request(url, headers=headers), timeout=timeout).read()
            return json.loads(raw.decode('utf-8-sig'))
        except (json.JSONDecodeError, ValueError):
            if attempt < 2:
                sess.init(force=True)
                time.sleep(0.3)
            else:
                raise

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

def query_tickets(date, from_name, to_name, session=None):
    sess = session or _sess()
    sess.init()
    fn,fc = resolve_station(from_name); tn,tc = resolve_station(to_name)
    if not fc or not tc: return {'error': f'站点未识别: {from_name}→{to_name}'}
    params = urllib.parse.urlencode({'leftTicketDTO.train_date':date,'leftTicketDTO.from_station':fc,
        'leftTicketDTO.to_station':tc,'purpose_codes':'ADULT'})
    url = f'https://kyfw.12306.cn/otn/{sess.api_type}?{params}'
    for attempt in range(2):
        try:
            data = _get(url, session=sess)
            rows = data.get('data',{}).get('result',[]) or []
            return {'from':fn, 'to':tn, 'date':date, 'count':len(rows), 'trains':[parse_train(r) for r in rows]}
        except Exception:
            if attempt < 1: sess.init(force=True); time.sleep(0.3)
            else: return {'error': f'查询失败(已重试)', 'from':fn, 'to':tn, 'date':date}

def _dur_min(d):
    """历时字符串→分钟数，解析失败返回极大值"""
    try:
        p = d.split(':'); return int(p[0])*60+int(p[1])
    except: return 9999

def _get_train_stops(train_no, from_code, to_code, date):
    """查询一趟车的途经站列表（含首尾），失败返回空"""
    try:
        url = (f'https://kyfw.12306.cn/otn/czxx/queryByTrainNo'
               f'?train_no={train_no}'
               f'&from_station_telecode={from_code}'
               f'&to_station_telecode={to_code}'
               f'&depart_date={date}')
        data = _get(url, timeout=8)
        stops = data.get('data', {}).get('data', [])
        return [s.get('station_name', '') for s in stops if s.get('station_name')]
    except:
        return []

# ─── 中转检索 ──────────────────────────────────────
def _process_one_hub(hn, from_variants, to_variants, date, direct_min, min_gap, max_gap, l2_hubs=None):
    """单枢纽处理（线程安全）。l2_hubs=同城所有变体, 用于跨站匹配如徐州→徐州东"""
    l2_hubs = l2_hubs or [hn]
    sess = Session()
    # 第1程: 从出发站变体→枢纽（查到即停）
    l1_trains = []
    for fv in from_variants:
        l1 = query_tickets(date, fv, hn, session=sess)
        if 'error' not in l1:
            t = l1.get('trains',[])
            l1_trains.extend(t)
            if t: break
    if not l1_trains: return None, False
    if direct_min:
        l1_durs = [_dur_min(t.get('duration','')) for t in l1_trains]
        l1_durs = [d for d in l1_durs if d < 9999]
        if l1_durs and min(l1_durs) >= direct_min * 0.85:
            return None, True
    # 第2程: 枢纽→到达站变体（含同城跨站: 徐州→徐州东 等）
    l2_trains = []
    for hvn in l2_hubs:
        for tv in to_variants:
            l2 = query_tickets(date, hvn, tv, session=sess)
            if 'error' not in l2:
                l2_trains.extend(l2.get('trains',[]))
    if not l2_trains: return None, False
    # 配对匹配
    results = []
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
            if gap < 0: gap += 1440  # 过夜换乘（如22:30到→次日07:38发）
            if min_gap <= gap <= max_gap:
                dur_total = _calc_total(t1,t2,gap)
                key = (t1['train_code'], t2['train_code'], hn)
                existing = next((r for r in results if (r['leg1']['train_code'],r['leg2']['train_code'],r['transfer'])==key), None)
                if existing:
                    if gap < existing['gap_min']:
                        existing.update({'gap_min':gap,'total_duration':dur_total,'leg1':t1,'leg2':t2})
                else:
                    results.append({'transfer':hn,'leg1':t1,'leg2':t2,'gap_min':gap,'total_duration':dur_total})
    return results, False

HUB_STATIONS = [
    '北京','上海','广州','深圳','成都','重庆','武汉','南京','杭州','西安',
    '郑州','长沙','济南','青岛','天津','沈阳','哈尔滨','长春','大连',
    '昆明','贵阳','南宁','兰州','乌鲁木齐','太原','石家庄','呼和浩特',
    '合肥','福州','南昌','厦门','苏州','无锡','宁波','温州','徐州',
    '洛阳','宜昌','襄阳','珠海','佛山','东莞','惠州','中山',
    '海口','三亚','拉萨','西宁','银川','九江',
    '商丘','蚌埠','衡阳','柳州','宝鸡',
]

_WORKERS = 5

def search_transfers(date, from_name, to_name, min_gap=20, max_gap=240, max_results=10, hubs=None, direct_min=None):
    """并发中转检索: ThreadPoolExecutor 多线程处理枢纽"""
    fn,fc = resolve_station(from_name); tn,tc = resolve_station(to_name)
    if not fc or not tc: return {'error': f'站点未识别: {from_name}→{to_name}'}
    
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
    
    from_codes = {STATIONS.get(fv) for fv in from_variants}
    to_codes = {STATIONS.get(tv) for tv in to_variants}
    hub_list = [h for h in hub_list if STATIONS.get(h) not in (from_codes | to_codes)]
    
    # 过滤掉无telecode的无效枢纽
    hub_list = [h for h in hub_list if STATIONS.get(h)]
    if not hub_list:
        return {'from':fn,'to':tn,'date':date,'checked_hubs':0,'skipped':0,'found':0,'transfers':[]}
    
    # 同城分组: {徐州: [徐州,徐州东], 南京: [南京,南京南], ...}
    base_re = re.compile(r'[东南西北]$')
    city_map = {}
    for hn in hub_list:
        city_map.setdefault(base_re.sub('', hn), []).append(hn)
    
    all_results, skipped, checked = [], 0, 0
    with ThreadPoolExecutor(max_workers=min(_WORKERS, len(hub_list))) as ex:
        futures = {}
        for hn in hub_list:
            base = base_re.sub('', hn)
            l2_variants = city_map.get(base, [hn])
            futures[ex.submit(_process_one_hub, hn, from_variants, to_variants, date, direct_min, min_gap, max_gap, l2_variants)] = hn
        for f in as_completed(futures):
            checked += 1
            try:
                r, filtered = f.result()
                if filtered: skipped += 1
                if r: all_results.extend(r)
            except Exception:
                pass
    all_results.sort(key=lambda x: x['total_duration'] or 9999)
    return {'from':fn,'to':tn,'date':date,'checked_hubs':checked,'skipped':skipped,'found':len(all_results),'transfers':all_results[:max_results]}

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
    skipped = data.get('skipped', 0)
    extra = f'（过滤{skipped}个过头枢纽）' if skipped else ''
    print(f'\n  中转 {data["from"]}→{data["to"]}  {data["date"]}  经{data["checked_hubs"]}站查得{data["found"]}方案{extra}')
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
    if 'error' in dd:
        print(f'\n  {dd.get("from","?")}→{dd.get("to","?")}  直达查询失败，仅显示中转结果')
    else:
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
        _init_session(force=True)  # 刷新session防过期
        d = search_transfers(args.date, args.from_s, args.to_s,
            min_gap=args.min_gap, max_gap=args.max_gap, max_results=args.max_results, hubs=hubs)
        if args.json: print(json.dumps(d, ensure_ascii=False, indent=2))
        else: print_transfers(d)

    elif args.mode == 'all':
        # 直达
        d_direct = query_tickets(args.date, args.from_s, args.to_s)
        hubs = args.hubs.split(',') if args.hubs else None
        # 计算最快直达耗时，用于中转枢纽智能过滤
        direct_min = None
        if 'error' not in d_direct:
            durs = []
            for t in d_direct.get('trains',[]):
                dm = _dur_min(t.get('duration',''))
                if dm < 9999: durs.append(dm)
            if durs: direct_min = min(durs)
        else:
            # 直达失败会污染session，重置后再跑中转
            _init_session(force=True)
            # 无直达参考时用精简枢纽列表 + 保守耗时阈值, 避免全量80站慢查询
            if not hubs:
                hubs = ['北京','上海','广州','武汉','南京','西安','郑州','长沙',
                        '济南','成都','重庆','合肥','南昌','徐州','商丘','石家庄']
                direct_min = _dur_min('8:00')
        # 中转枢纽: 优先从直达车途经站提取
        if not hubs and 'error' not in d_direct and d_direct.get('trains'):
            # 取最快可购直达，查途经站列表
            trains = sorted(d_direct['trains'], key=lambda t: _dur_min(t.get('duration','')))
            best = next((t for t in trains if t.get('can_buy')=='Y'), trains[0]) if trains else None
            if best:
                fn_code = STATIONS.get(d_direct.get('from',''), '')
                tn_code = STATIONS.get(d_direct.get('to',''), '')
                stops = _get_train_stops(best['train_no'], fn_code, tn_code, args.date)
                if stops and len(stops) > 2:
                    # 排除首尾（出发/到达），去方向后缀→取全国主要枢纽交集
                    base_name = re.compile(r'[东南西北]$')
                    fn_base = base_name.sub('', d_direct.get('from',''))
                    tn_base = base_name.sub('', d_direct.get('to',''))
                    stops_raw = [base_name.sub('', s) for s in stops[1:-1] if s]
                    stops_dedup = list(dict.fromkeys(stops_raw))
                    # 只保留全国主要枢纽（有大量车次的中转站），小站跳过
                    major = set(HUB_STATIONS)
                    hubs = [h for h in stops_dedup if h not in (fn_base, tn_base) and h in major]
                    # 如果没有主要枢纽命中，兜底用全部途经站
                    if not hubs:
                        hubs = [h for h in stops_dedup if h not in (fn_base, tn_base)]
        _init_session(force=True)  # 中转前刷新session
        d_transfer = search_transfers(args.date, args.from_s, args.to_s,
            min_gap=args.min_gap, max_gap=args.max_gap, max_results=args.max_results, hubs=hubs, direct_min=direct_min)
        if args.json:
            print(json.dumps({'direct':d_direct,'transfer':d_transfer}, ensure_ascii=False, indent=2))
        else:
            print_combined(d_direct, d_transfer)

if __name__ == '__main__':
    main()
