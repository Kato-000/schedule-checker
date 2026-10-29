"""足りない情報（場所・住所・時刻）をネットで調べる。

1. 予定から検索語を作る（画面で「送る内容」として先に見せる）
2. Web検索（Ollama）で結果を受け取る
3. 結果を読むのはPCのLLM。候補を作るだけで、反映は本人が選ぶ
"""

from __future__ import annotations

from . import config, llm, net, prompts
from .dates import norm_time, parse_date


def build_queries(event: dict) -> list[str]:
    title = (event.get("title") or "").strip()
    location = (event.get("location") or "").strip()
    address = (event.get("address") or "").strip()
    d = parse_date(event.get("start_date"))
    day = f"{d.month}月{d.day}日" if d else ""
    qs: list[str] = []
    if location and not address:
        qs.append(f"{location} 住所")
    if not location and title:
        qs.append(f"{title} 場所")
    if not event.get("start_time") and not event.get("is_deadline") and title:
        qs.append(" ".join(x for x in (title, location, day, "開始時間") if x))
    if not qs and title:
        qs.append(" ".join(x for x in (title, location) if x))
    seen, out = set(), []
    for q in qs:
        q = " ".join(q.split())[:80]
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[: config.LOOKUP_MAX_QUERIES]


def run(event: dict, queries: list[str] | None = None) -> dict:
    """検索してLLMで候補を作る。queries は画面に見せたものをそのまま使う（変えて送らない）。"""
    expected = build_queries(event)
    queries = [q for q in (queries or expected) if q in expected] or expected
    if not queries:
        raise net.NetError("調べる手がかりがありません。予定の名前か場所を入れてください")
    results: list[dict] = []
    seen_urls = set()
    for q in queries:
        for r in net.search(q, config.LOOKUP_RESULTS_PER_QUERY):
            if r["url"] in seen_urls:
                continue
            seen_urls.add(r["url"])
            results.append(r)
    if not results:
        return {"queries": queries, "candidates": [], "hours": None, "note": "検索結果がありませんでした",
                "sources": []}
    a, _ = llm.client.chat(prompts.lookup_messages(event, results), prompts.LOOKUP_SCHEMA)

    def text(v, n=120):
        v = (v or "").strip() if isinstance(v, str) else ""
        return v[:n] or None

    cands = []
    place = text(a.get("place_name"), 60)
    if place and place != (event.get("location") or ""):
        cands.append({"field": "location", "label": "場所", "value": place})
    addr = text(a.get("address"))
    if addr and addr != (event.get("address") or ""):
        cands.append({"field": "address", "label": "住所", "value": addr})
    for field, label in (("start_time", "開始"), ("end_time", "終了")):
        t = norm_time(a.get(field))
        if t and t != event.get(field):
            cands.append({"field": field, "label": label, "value": t})
    src = a.get("source")
    sources = [{"title": r["title"], "url": r["url"]} for r in results]
    main = sources[src - 1] if isinstance(src, int) and 1 <= src <= len(sources) else None
    return {"queries": queries, "candidates": cands, "hours": text(a.get("hours")), "note": text(a.get("note")),
            "source": main, "sources": sources[:6]}
