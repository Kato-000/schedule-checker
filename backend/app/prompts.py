"""LLMに渡すプロンプトと出力スキーマ（検証スクリプト v3 を本番用に整理したもの）。"""

from __future__ import annotations

import datetime as dt
import json

from .dates import WEEKDAYS_JA, d_ja, parse_date, quick_ref

CATEGORIES = {
    "会議": "打ち合わせ、定例、1on1、面接",
    "プレゼン": "発表、説明会での登壇",
    "締切": "提出物・作業の期限",
    "手続き": "支払い、振込、申請、役所、車検、契約、税金・確定申告、保険",
    "通院": "病院、歯医者、健康診断",
    "試験": "資格試験、検定、テスト",
    "出張": "泊まりや遠方への仕事の移動",
    "仕事": "上記以外の仕事",
    "行事": "結婚式、式典、イベント、パーティー",
    "私用": "美容院、飲み会、買い物、家のことなど上記以外の私的な用事",
}
PRIORITIES = ("high", "medium", "low")

NULLABLE_STR = {"type": ["string", "null"]}

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "event": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_date": {"type": "string"},
                "start_time": NULLABLE_STR,
                "end_date": NULLABLE_STR,
                "end_time": NULLABLE_STR,
                "location": NULLABLE_STR,
                "category": {"type": "string", "enum": list(CATEGORIES)},
                "is_deadline": {"type": "boolean"},
            },
            "required": ["title", "start_date", "start_time", "end_date",
                         "end_time", "location", "category", "is_deadline"],
        },
        "questions": {"type": "array", "items": {"type": "string"}, "maxItems": 1},
    },
    "required": ["event", "questions"],
}

TODO_SCHEMA = {
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "due_date": {"type": "string"},
                    "due_time": NULLABLE_STR,
                    "priority": {"type": "string", "enum": list(PRIORITIES)},
                },
                "required": ["title", "due_date", "due_time", "priority"],
            },
        },
    },
    "required": ["todos"],
}

# 予定に結びつかないTodoを1件読み取る
SINGLE_TODO_SCHEMA = {
    "type": "object",
    "properties": {
        "todo": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "due_date": NULLABLE_STR,
                "due_time": NULLABLE_STR,
                "priority": {"type": "string", "enum": list(PRIORITIES)},
            },
            "required": ["title", "due_date", "due_time", "priority"],
        },
    },
    "required": ["todo"],
}

ADVICE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "suggestions": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
    "required": ["summary", "suggestions"],
}

EVENT_SYSTEM = """あなたは予定の読み取り係です。入力文から予定を1件だけ取り出し、指定のJSONで返してください。
文章はすべて自然な日本語で書き、中国語や英語の文を混ぜないでください。

規則:
- 日付は必ず「日付の早見表」から選ぶ。自分で曜日や日数を計算しない。
- 予定の日付は今日以降。「次の○曜」「今度の○曜」は早見表の「次の○曜」を使う。
- 「今週の○曜」「来週の○曜」「再来週の○曜」は、早見表の「曜日別」の行から、その曜日の該当する欄を使う。
- 「今週中」「今週末」「月末」「今月中」「来月末」「年内」「年末」は、早見表にある期間の最終日を start_date にし、is_deadline を true にする。
- 時刻は24時間表記の HH:MM。「午後3時」は15:00、「14時半」は14:30。「午前中」「夕方」のような幅のある表現や、時刻がないときは null。
- is_deadline: 提出・振込・支払い・送付・精算など「その日時までに終える」ものは true。会議・試験・通院・行事など「その日時に行く・参加する」ものは false。
- 終了時刻や所要時間が書かれていれば end_date / end_time を埋める。複数日にわたる予定は end_date に最終日。書かれていなければ null。
- location は入力に場所が書かれている場合のみ。なければ null。
- title は短く。入力に書かれていない事実（人名・場所・時刻）を作らない。
- questions には、予定の登録に不可欠なのに入力から決められない点だけを最大1件。なければ空配列。

category の選び方:
""" + "\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items())

TODO_SYSTEM = """あなたは準備Todoを考える係です。確定した予定に対して、事前にやるべき準備を0〜4件、指定のJSONで返してください。
文章はすべて自然な日本語で書き、中国語や英語の文を混ぜないでください。

規則:
- 「ユーザーの手本」は、このユーザーが過去に承認したTodo。内容・粒度・期限の置き方を最優先で真似る。
  ただし「参考」と付いた手本は予定の内容が違うので、合わない部分は真似しない。
- 手本の時刻は「開始30分前」のように予定の開始時刻からの相対で書かれている。今回の予定の開始時刻に合わせて換算する。
- 「ユーザーのルール」は必ず守る。
- その予定に特有で、実際に役立つ準備だけを書く。必要なければ0件でよい。
- 入力に書かれていない事実（人名・場所・金額）を作らない。似た内容を重複させない。
- due_date は「今日」以降、予定の日付以前で、下の「目安日」から選ぶ。
  期限は手間に合わせて分散させる: 手配・購入・作成など時間のかかるものは早め、確認だけのものは前日。
  今日を期限にするのは、予定が近くて今日やらないと間に合わないものだけ。
- due_time は原則 null。予定当日に開始前までに終える必要があるTodoだけ時刻を入れ、予定の開始時刻より前にする。
- priority: high = やらないと予定が成り立たない・大きく困る / medium = やっておくと安心 / low = 余裕があれば。
- 期限型の予定（is_deadline が true）は、作業を分解して期限から逆算したTodoにする。"""

SINGLE_TODO_SYSTEM = """あなたはTodoの読み取り係です。入力文から、やることを1件だけ取り出し、指定のJSONで返してください。
文章はすべて自然な日本語で書き、中国語や英語の文を混ぜないでください。

規則:
- title は、やることを短く言い切る形にする。日付・期限・優先度を表す言葉（「明日までに」「急ぎで」など）は title から除く。
  入力に書かれていない事実（人名・場所・金額）を作らない。
- due_date は期限。入力に期限や日付が書かれているときだけ、必ず「日付の早見表」から選ぶ。自分で曜日や日数を計算しない。
  - 「今日中」は今日、「明日まで」は明日、「○曜までに」は早見表の「次の○曜」、「今週中」は今週末、「月末まで」「今月中」は月末。
  - 期限が書かれていなければ null（「そのうち」「いつか」「時間があるとき」も null）。
- due_time は「15時までに」のように時刻が書かれているときだけ HH:MM。なければ null。
- priority:
  - high = 「急ぎ」「至急」「必ず」「大事」などと書かれている、または期限が今日・明日で、やらないと困るもの
  - low = 「そのうち」「いつか」「余裕があれば」「時間があるとき」など
  - それ以外は medium"""

ADVICE_SYSTEM = """あなたは個人の予定管理アシスタントです。今日の予定と、今後1週間の予定・未完了のTodoを見て、
朝のひとことと「やったほうがいいこと」を指定のJSONで返してください。文章はすべて自然な日本語で書いてください。

規則:
- summary は今日の状況を1〜2文で。忙しさや、最優先のことを伝える。
- suggestions は、一覧にまだ無いが今日やっておくと後が楽になることを最大3件。短く具体的に。
  既にあるTodoの言い換えや、一般論（早く寝る、水を飲む など）は書かない。思いつかなければ空配列。
- 入力にない事実（人名・場所・金額）を作らない。
- 曜日や日付を自分で計算しない。今日の曜日は入力の「今日」に書かれたものだけを使う。
  ほかの日に触れるときは、一覧に書かれた「明日」「3日後」「10/28（水）」などの言い方をそのまま使う。"""

RULES_SCHEMA = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "category": {"type": "string", "enum": ["全般", *CATEGORIES]},
                    "reason": {"type": "string"},
                },
                "required": ["text", "category", "reason"],
            },
        },
    },
    "required": ["rules"],
}

RULES_SYSTEM = """あなたは、ユーザーがTodoの案をどう直したかを分析する係です。
修正の記録から、このユーザーに共通する好み・傾向を「Todoを作るときのルール」として最大3件、指定のJSONで返してください。
文章はすべて自然な日本語で書いてください。

規則:
- 2回以上くり返し現れる傾向だけをルールにする。1回だけの修正からは作らない。
- ルールは短く具体的に、Todoを作る人への指示の形で書く（例: 「会議の前日に議題を確認するTodoは不要」「プレゼン資料の作成は1週間前を期限にする」）。
- 特定の種類の予定だけに当てはまるなら category にその種類を、全体に当てはまるなら「全般」を入れる。
- reason には、根拠になった修正を短く書く（例: 「会議3件で同じTodoを削除」）。
- 「既にあるルール」と同じ内容や、却下済みの内容は出さない。
- 当てはまる傾向がなければ空配列を返す。"""

ANCHOR_LABELS = {14: "2週間前", 7: "1週間前", 3: "3日前", 1: "前日", 0: "当日"}


def event_messages(text: str, base: dt.date) -> list[dict]:
    return [{"role": "system", "content": EVENT_SYSTEM},
            {"role": "user", "content": f"日付の早見表:\n{quick_ref(base)}\n\n入力: {text}"}]


def days_label(n: int) -> str:
    return ANCHOR_LABELS.get(n, f"{n}日前")


def format_example(ex: dict) -> str:
    tags = [ex["category"]] + (["期限"] if ex.get("is_deadline") else [])
    ref = "（参考）" if ex.get("reference") else ""
    head = f"予定「{ex['text']}」{ref}（{'・'.join(tags)}）"
    if not ex.get("todos"):
        return head + "\n  → Todoなし"
    lines = []
    for t in ex["todos"]:
        if t.get("minutes_before_start") is not None:
            when = f"当日・開始{t['minutes_before_start']}分前"
        else:
            when = days_label(int(t.get("days_before", 0))) + (f" {t['time']}" if t.get("time") else "")
        lines.append(f"  - [{t.get('priority', 'medium')}] {t['title']}（{when}）")
    return head + "\n" + "\n".join(lines)


def todo_messages(text: str, event: dict, base: dt.date,
                  examples: list[dict], rules: list[str]) -> list[dict]:
    ev_date = parse_date(event.get("start_date")) or base
    anchors = {base: "今日"}
    for days, label in ANCHOR_LABELS.items():
        d = ev_date - dt.timedelta(days)
        if d >= base:
            anchors[d] = anchors[d] + "・" + label if d in anchors else label
    anchor_lines = [f"{label}: {d_ja(d)}" for d, label in sorted(anchors.items())]
    parts = [f"今日: {d_ja(base)}\n元の入力: {text}\n確定した予定: {json.dumps(event, ensure_ascii=False)}",
             "目安日:\n" + "\n".join(anchor_lines)]
    if rules:
        parts.append("ユーザーのルール:\n" + "\n".join(f"- {r}" for r in rules))
    if examples:
        parts.append("ユーザーの手本（似た予定で過去に承認したTodo）:\n"
                     + "\n".join(format_example(e) for e in examples))
    return [{"role": "system", "content": TODO_SYSTEM},
            {"role": "user", "content": "\n\n".join(parts)}]


def advice_messages(base: dt.date, today_events: list[dict], week_events: list[dict],
                    open_todos: list[dict]) -> list[dict]:
    # 日付には「今日・明日・◯日後」と曜日を付けて渡す（LLMに曜日や日数を計算させない）
    def when(iso):
        d = parse_date(iso)
        if not d:
            return iso or ""
        diff = (d - base).days
        rel = {0: "今日", 1: "明日", 2: "明後日", -1: "昨日"}.get(diff, f"{diff}日後" if diff > 0 else f"{-diff}日前")
        return f"{rel}・{d.month}/{d.day}（{WEEKDAYS_JA[d.weekday()]}）"

    def ev_line(e):
        t = f" {e['start_time']}" if e.get("start_time") else ""
        return f"- {when(e['start_date'])}{t} {e['title']}（{e['category']}{'・期限' if e.get('is_deadline') else ''}）"

    def todo_line(t):
        due = f"期限 {when(t['due_date'])}" if t.get("due_date") else "期限なし"
        return f"- [{t['priority']}] {t['title']}（{due}）"

    body = [f"今日: {base.year}年{base.month}月{base.day}日 {WEEKDAYS_JA[base.weekday()]}曜日",
            "今日の予定:\n" + ("\n".join(map(ev_line, today_events)) or "なし"),
            "今後1週間の予定:\n" + ("\n".join(map(ev_line, week_events)) or "なし"),
            "未完了のTodo:\n" + ("\n".join(map(todo_line, open_todos)) or "なし")]
    return [{"role": "system", "content": ADVICE_SYSTEM},
            {"role": "user", "content": "\n\n".join(body)}]


def single_todo_messages(text: str, base: dt.date) -> list[dict]:
    return [{"role": "system", "content": SINGLE_TODO_SYSTEM},
            {"role": "user", "content": f"日付の早見表:\n{quick_ref(base)}\n\n入力: {text}"}]


# ---------------------------------------------------------------------------
# ネットで調べた結果から、足りない情報を拾う（ネット連携）
# ---------------------------------------------------------------------------
LOOKUP_SCHEMA = {
    "type": "object",
    "properties": {
        "place_name": NULLABLE_STR,
        "address": NULLABLE_STR,
        "start_time": NULLABLE_STR,
        "end_time": NULLABLE_STR,
        "hours": NULLABLE_STR,
        "source": {"type": ["integer", "null"]},
        "note": NULLABLE_STR,
    },
    "required": ["place_name", "address", "start_time", "end_time", "hours", "source", "note"],
}

LOOKUP_SYSTEM = """あなたは予定の情報を補う係です。予定と、ネットで検索した結果（番号付き）を見て、予定に足りない情報を指定のJSONで返してください。
文章はすべて自然な日本語で書いてください。

規則:
- 検索結果に書かれていることだけを使う。推測や一般知識で埋めない。見つからない項目は null。
- place_name: 予定の会場・お店・施設の正式な名前。
- address: その場所の住所（都道府県か市区町村から番地まで）。検索結果に住所が書かれているときだけ。
- start_time / end_time: その予定の日付の、開始・終了時刻（HH:MM）。検索結果にその日付の催しの時刻が書かれているときだけ。
  開場と開演が両方あれば start_time は開演。
- hours: お店・施設の営業時間や受付時間（例: 「9:00〜18:00（水曜休み）」）。予定の時刻ではないもの。
- source: いちばん根拠にした検索結果の番号。なければ null。
- note: 注意点があれば1文（例: 「同じ名前の施設が複数あります」）。なければ null。
- 別の場所・別の日の催しの情報を、この予定の情報として使わない。"""


def lookup_messages(event: dict, results: list[dict]) -> list[dict]:
    ev = {k: event.get(k) for k in ("title", "start_date", "start_time", "end_time", "location", "address")}
    lines = []
    for i, r in enumerate(results, 1):
        content = " ".join((r.get("content") or "").split())[:500]
        lines.append(f"[{i}] {r.get('title', '')}\n{r.get('url', '')}\n{content}")
    return [{"role": "system", "content": LOOKUP_SYSTEM},
            {"role": "user", "content": f"予定: {json.dumps(ev, ensure_ascii=False)}\n\n検索結果:\n" + "\n\n".join(lines)}]
