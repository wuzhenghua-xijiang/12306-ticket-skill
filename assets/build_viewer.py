#!/usr/bin/env python3
"""生成内嵌12306查询数据的独立HTML文件，双击即可在浏览器查看"""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import query12306 as q

def build(date, from_s, to_s, hubs=None, max_gap=1440, out=None):
    q.load_stations()
    hubs_list = hubs.split(',') if hubs else None
    d = q.search_transfers(date, from_s, to_s, min_gap=20, max_gap=max_gap,
                           max_results=9999, hubs=hubs_list)
    data_json = json.dumps(d, ensure_ascii=False)

    viewer_path = os.path.join(os.path.dirname(__file__), 'viewer.html')
    html = open(viewer_path).read()

    html = html.replace(
        'loadData(src);',
        f'// embedded {len(d.get("transfers",[]))} results\n    loadData({data_json});')
    html = html.replace(
        "const src = params.get('src') || '/tmp/sample_data.json';",
        "const src = null;")
    html = html.replace(
        "const resp = await fetch(src);\n      json = await resp.json();",
        "json = src;")
    html = html.replace(
        '} else {\n      json = JSON.parse(await src.text());\n    }',
        '} else { json = src; }')

    out = out or f'/tmp/12306_{from_s}_{to_s}_{date}.html'
    with open(out, 'w') as f:
        f.write(html)
    print(f'✅ {out}  ({len(d.get("transfers",[]))} 方案)')
    return out

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='生成可浏览器打开的12306中转方案HTML')
    p.add_argument('-d', '--date', required=True)
    p.add_argument('-f', '--from', dest='from_s', required=True)
    p.add_argument('-t', '--to', dest='to_s', required=True)
    p.add_argument('--hubs')
    p.add_argument('--max-gap', type=int, default=1440)
    p.add_argument('-o', '--out')
    args = p.parse_args()
    path = build(args.date, args.from_s, args.to_s, args.hubs, args.max_gap, args.out)
    os.system(f'open "{path}"')
