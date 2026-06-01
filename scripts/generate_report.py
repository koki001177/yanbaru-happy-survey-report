# -*- coding: utf-8 -*-
"""
やんばる国内観光客アンケート 月次レポート 自動生成オーケストレータ（GitHub Actions用）

毎月1日に GitHub Actions から実行され、以下を完全自動で行う:
  1. 対象月（既定=前月）を決定
  2. build_report.py で GitHub の全件 all.csv を取得・集計し summary.json を生成
  3. summary.json から当月レポート <YYYYMM>/index.html を生成
  4. reports.json マニフェストを更新し、トップ index.html（レポート一覧）を再生成

使い方:
    python scripts/generate_report.py            # 前月を対象
    python scripts/generate_report.py --month 2026-06
    python scripts/generate_report.py --month 2026-06 --csv local.csv

データが未更新で対象月の回答が0件の場合、build_report.py が非ゼロ終了するため、
本スクリプトも何も生成せずに終了する（＝空レポートを発行しない）。

仕様（やんばる確定仕様）:
  満足度＝「大変満足＋満足」／再来訪＝「必ず来たい＋来たい」／NPS＝推奨者(9-10)−批判者(0-6)
  号数 Vol.＝4月起点の連番（4月=Vol.1, 5月=Vol.2 …）／発行元＝一般社団法人沖縄やんばるDMO
注記: 本月から解釈文・要旨・提案はデータ連動の自動生成テキスト。事実（集計値）に基づき機械生成している。
"""
import argparse, json, os, sys, subprocess, calendar, datetime, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")

# ---------- ユーティリティ ----------
def prev_month(today=None):
    today = today or datetime.date.today()
    y, mo = today.year, today.month
    mo -= 1
    if mo == 0:
        mo = 12; y -= 1
    return f"{y:04d}-{mo:02d}"

def vol_of(month):
    y, mo = map(int, month.split("-"))
    # 2026年4月 = Vol.1
    return (y - 2026) * 12 + (mo - 4) + 1

def reiwa(year):
    return year - 2018  # 2019=令和1

def jp_period(month):
    y, mo = map(int, month.split("-"))
    last = calendar.monthrange(y, mo)[1]
    return y, mo, last

def short_pref(name):
    for suf in ["都", "府", "県"]:
        if name.endswith(suf):
            return name[:-1]
    if name == "北海道":
        return "北海道"
    return name

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def bars(items, key="n"):
    mx = max([x[key] for x in items], default=0) or 1
    return [round(x[key] / mx * 100) for x in items]

# ---------- HTML部品 ----------
CSS = """
  :root {
    --text: #222; --text-mute: #555; --text-sub: #777;
    --rule: #cccccc; --rule-light: #e3e3e3;
    --bg: #ffffff; --bg-alt: #f6f5f1;
    --accent: #2f5a3f; --accent-dark: #1f3f2c; --warning: #8a3a26;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: "Noto Serif JP","ヒラギノ明朝 ProN","游明朝","Yu Mincho",serif; font-size: 15px; line-height: 1.9; -webkit-font-smoothing: antialiased; font-feature-settings: "palt"; }
  .container { max-width: 920px; margin: 0 auto; padding: 0 32px; }
  .page-header { border-bottom: 1px solid var(--rule); padding: 16px 0; font-family: "Noto Sans JP", sans-serif; font-size: 12px; color: var(--text-mute); }
  .page-header .container { display: flex; justify-content: space-between; align-items: center; }
  .cover { padding: 64px 0 48px; border-bottom: 2px solid var(--text); }
  .cover .category { font-family: "Noto Sans JP", sans-serif; font-size: 13px; color: var(--accent); font-weight: 500; margin-bottom: 16px; letter-spacing: 0.1em; }
  .cover h1 { font-family: "Noto Serif JP", serif; font-size: 30px; font-weight: 700; line-height: 1.55; color: var(--text); margin-bottom: 16px; }
  .cover .subtitle { font-family: "Noto Sans JP", sans-serif; font-size: 14px; color: var(--text-mute); font-weight: 400; margin-bottom: 32px; }
  .cover .meta { border-top: 1px solid var(--rule); padding-top: 20px; font-size: 13px; color: var(--text-mute); display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
  .cover .meta dt { font-family: "Noto Sans JP", sans-serif; font-size: 11px; color: var(--text-sub); margin-bottom: 4px; }
  .cover .meta dd { font-size: 14px; color: var(--text); }
  .toc { background: var(--bg-alt); padding: 28px 32px; margin: 40px 0; border: 1px solid var(--rule-light); }
  .toc h2 { font-family: "Noto Serif JP", serif; font-size: 16px; font-weight: 700; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid var(--rule); }
  .toc ol { list-style: none; counter-reset: toc; }
  .toc ol li { counter-increment: toc; padding: 6px 0; font-size: 14px; display: flex; align-items: baseline; gap: 12px; }
  .toc ol li::before { content: counter(toc) "."; font-family: "Noto Sans JP", sans-serif; color: var(--accent); font-weight: 500; width: 24px; flex-shrink: 0; }
  .toc ol li a { color: var(--text); text-decoration: none; }
  .toc ol li a:hover { color: var(--accent); text-decoration: underline; }
  main { padding: 24px 0 80px; }
  section.chapter { margin-bottom: 64px; }
  .chapter-head { border-top: 2px solid var(--accent); padding-top: 12px; margin-bottom: 24px; }
  .chapter-head .num { font-family: "Noto Sans JP", sans-serif; font-size: 12px; color: var(--accent); font-weight: 500; margin-bottom: 6px; }
  .chapter-head h2 { font-family: "Noto Serif JP", serif; font-size: 22px; font-weight: 700; color: var(--text); line-height: 1.5; }
  .lead { font-size: 15px; line-height: 2; margin-bottom: 24px; color: var(--text); }
  .lead b { font-weight: 700; color: var(--text); }
  h3.sub { font-family: "Noto Serif JP", serif; font-size: 17px; font-weight: 700; color: var(--text); border-left: 4px solid var(--accent); padding-left: 12px; margin: 32px 0 14px; }
  p { margin-bottom: 12px; font-size: 14.5px; line-height: 1.95; }
  .summary-box { border: 1px solid var(--rule); margin: 24px 0; }
  .summary-box .row { display: grid; grid-template-columns: repeat(4, 1fr); border-bottom: 1px solid var(--rule-light); }
  .summary-box .row:last-child { border-bottom: none; }
  .summary-box .cell { padding: 14px 16px; border-right: 1px solid var(--rule-light); font-size: 13px; }
  .summary-box .cell:last-child { border-right: none; }
  .summary-box .cell .label { font-family: "Noto Sans JP", sans-serif; font-size: 11px; color: var(--text-sub); margin-bottom: 4px; }
  .summary-box .cell .value { font-family: "Noto Serif JP", serif; font-size: 22px; font-weight: 700; color: var(--text); }
  .summary-box .cell .value .unit { font-size: 12px; color: var(--text-mute); font-weight: 400; margin-left: 2px; }
  .summary-box .cell .sub { font-size: 11px; color: var(--text-sub); margin-top: 4px; }
  .keypoint { background: var(--bg-alt); border: 1px solid var(--rule-light); padding: 20px 24px; margin: 20px 0; }
  .keypoint h4 { font-family: "Noto Sans JP", sans-serif; font-size: 12px; color: var(--accent); font-weight: 700; margin-bottom: 10px; letter-spacing: 0.05em; }
  .keypoint ol { list-style: none; counter-reset: kp; }
  .keypoint ol li { counter-increment: kp; padding: 6px 0 6px 28px; position: relative; font-size: 14px; line-height: 1.95; }
  .keypoint ol li::before { content: "(" counter(kp) ")"; position: absolute; left: 0; color: var(--accent); font-family: "Noto Sans JP", sans-serif; font-weight: 500; }
  table.data { width: 100%; border-collapse: collapse; margin: 16px 0 20px; font-size: 13.5px; }
  table.data th, table.data td { padding: 8px 12px; border: 1px solid var(--rule-light); text-align: left; vertical-align: middle; }
  table.data thead th { background: var(--bg-alt); font-family: "Noto Sans JP", sans-serif; font-size: 12px; font-weight: 500; color: var(--text-mute); border-bottom: 2px solid var(--text-mute); }
  table.data td.num { text-align: center; color: var(--text-mute); font-family: "Noto Sans JP", sans-serif; font-size: 12px; width: 40px; }
  table.data td.theme { font-weight: 500; }
  table.data td.cnt, table.data td.pct { text-align: right; font-family: "Noto Sans JP", sans-serif; width: 80px; }
  table.data td.bar { width: 160px; padding: 0 12px; }
  table.data td.bar .bar-inner { height: 8px; background: var(--accent); }
  table.data tr.warn td.bar .bar-inner { background: var(--warning); }
  table.data caption { caption-side: top; text-align: left; font-size: 12px; color: var(--text-sub); padding-bottom: 4px; }
  .voices { margin: 16px 0 20px; }
  .voice { background: var(--bg-alt); border-left: 3px solid var(--accent); padding: 12px 16px; margin-bottom: 8px; font-size: 13.5px; line-height: 1.85; color: var(--text); }
  .voice.warn { border-left-color: var(--warning); }
  .voice .meta { display: block; font-family: "Noto Sans JP", sans-serif; font-size: 11px; color: var(--text-sub); margin-top: 6px; }
  .chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin: 20px 0; }
  .chart-block { border: 1px solid var(--rule-light); padding: 20px; }
  .chart-block .ttl { font-family: "Noto Serif JP", serif; font-size: 14px; font-weight: 700; color: var(--text); margin-bottom: 6px; }
  .chart-block .note { font-family: "Noto Sans JP", sans-serif; font-size: 11px; color: var(--text-sub); margin-bottom: 12px; }
  .chart-box { position: relative; height: 260px; }
  .seg-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 20px 0; }
  .seg-card { border: 1px solid var(--rule-light); padding: 20px; }
  .seg-card h4 { font-family: "Noto Serif JP", serif; font-size: 16px; font-weight: 700; margin-bottom: 4px; }
  .seg-card .n { font-family: "Noto Sans JP", sans-serif; font-size: 11px; color: var(--text-sub); margin-bottom: 14px; padding-bottom: 8px; border-bottom: 1px solid var(--rule-light); }
  .seg-card .seg-section { margin-bottom: 14px; }
  .seg-card .seg-section h5 { font-family: "Noto Sans JP", sans-serif; font-size: 11px; color: var(--text-mute); font-weight: 500; margin-bottom: 6px; letter-spacing: 0.05em; }
  .seg-card .seg-section h5.warn { color: var(--warning); }
  .seg-card .seg-section ul { list-style: none; font-size: 13px; }
  .seg-card .seg-section ul li { padding: 4px 0; display: flex; justify-content: space-between; border-bottom: 1px dotted var(--rule-light); }
  .seg-card .seg-section ul li:last-child { border-bottom: none; }
  .seg-card .seg-section ul li b { font-family: "Noto Sans JP", sans-serif; font-weight: 500; color: var(--accent); }
  .seg-card .seg-note { font-size: 12px; color: var(--text-mute); line-height: 1.8; margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--rule-light); }
  .seg-5col { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin: 20px 0; }
  .seg-mini { border: 1px solid var(--rule-light); padding: 12px; font-size: 12px; }
  .seg-mini h5 { font-family: "Noto Serif JP", serif; font-size: 14px; font-weight: 700; margin-bottom: 2px; }
  .seg-mini .n { font-family: "Noto Sans JP", sans-serif; font-size: 10px; color: var(--text-sub); margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid var(--rule-light); }
  .seg-mini .lbl { font-family: "Noto Sans JP", sans-serif; font-size: 10px; color: var(--accent); margin-top: 8px; margin-bottom: 2px; }
  .seg-mini .lbl.warn { color: var(--warning); }
  .seg-mini ul { list-style: none; font-size: 11.5px; line-height: 1.6; }
  .seg-mini ul li b { font-family: "Noto Sans JP", sans-serif; color: var(--text-mute); margin-left: 4px; }
  .proposal-list { margin: 20px 0; }
  .proposal { border: 1px solid var(--rule-light); padding: 20px 24px; margin-bottom: 12px; }
  .proposal .head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid var(--rule-light); }
  .proposal .head .no { font-family: "Noto Sans JP", sans-serif; font-size: 11px; color: var(--accent); font-weight: 500; }
  .proposal .head .tag { font-family: "Noto Sans JP", sans-serif; font-size: 10px; background: var(--accent); color: white; padding: 2px 8px; }
  .proposal h4 { font-family: "Noto Serif JP", serif; font-size: 16px; font-weight: 700; margin-bottom: 8px; line-height: 1.6; }
  .proposal p { font-size: 13.5px; line-height: 1.9; color: var(--text); }
  .proposal .target { margin-top: 10px; font-family: "Noto Sans JP", sans-serif; font-size: 11px; color: var(--text-mute); background: var(--bg-alt); padding: 6px 10px; }
  .proposal .target strong { color: var(--text); margin-right: 6px; }
  footer { background: var(--bg-alt); border-top: 2px solid var(--text); padding: 32px 0; margin-top: 60px; font-size: 12px; color: var(--text-mute); }
  .footer-grid { display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 32px; padding-bottom: 20px; border-bottom: 1px solid var(--rule); }
  footer h5 { font-family: "Noto Sans JP", sans-serif; font-size: 11px; color: var(--text); font-weight: 700; margin-bottom: 8px; }
  footer p { font-size: 12px; line-height: 1.85; }
  .colophon { padding-top: 14px; font-family: "Noto Sans JP", sans-serif; font-size: 11px; color: var(--text-sub); display: flex; justify-content: space-between; }
  .autonote { font-family: "Noto Sans JP", sans-serif; font-size: 11px; color: var(--text-sub); background: var(--bg-alt); border: 1px solid var(--rule-light); padding: 10px 14px; margin: 16px 0; line-height: 1.7; }
  @media (max-width: 760px) {
    .container { padding: 0 16px; }
    .cover h1 { font-size: 22px; }
    .cover .meta { grid-template-columns: 1fr 1fr; }
    .summary-box .row { grid-template-columns: 1fr 1fr; }
    .summary-box .cell:nth-child(2) { border-right: none; }
    .chart-row, .seg-2col, .footer-grid { grid-template-columns: 1fr; }
    .seg-5col { grid-template-columns: 1fr 1fr; }
    .colophon { flex-direction: column; gap: 6px; }
    table.data td.bar { display: none; }
  }
"""


def theme_table(items, total_for_pct, warn=False, pct_field=None):
    """テーマ表（No./テーマ/件数/比率/分布バー）を生成。"""
    rows = []
    ws = bars(items)
    cls = ' class="warn"' if warn else ""
    for i, (it, w) in enumerate(zip(items, ws), 1):
        pct = it.get(pct_field) if pct_field else round(it["n"] / max(total_for_pct, 1) * 100, 1)
        rows.append(
            f'<tr{cls}><td class="num">{i}</td><td class="theme">{esc(it["theme"])}</td>'
            f'<td class="cnt">{it["n"]}</td><td class="pct">{pct}%</td>'
            f'<td class="bar"><span class="bar-inner" style="width: {w}%;"></span></td></tr>'
        )
    return (
        '<table class="data"><thead><tr><th>No.</th><th>テーマ</th><th>件数</th>'
        '<th>比率</th><th>分布</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>"
    )


def voice_blocks(voices_dict, themes, k=3, warn=False):
    """上位テーマからクリーンな実ボイスを1件ずつ拾って引用ブロックにする。"""
    out = []
    for t in themes[:k]:
        name = t["theme"]
        arr = voices_dict.get(name) or []
        if not arr:
            continue
        v = arr[0]
        meta = "／".join([x for x in [v.get("性別", ""), v.get("年代", ""), v.get("同行者", "")] if x and x != "nan"])
        wc = " warn" if warn else ""
        out.append(f'<div class="voice{wc}">{esc(v["text"])}<span class="meta">{esc(meta)}</span></div>')
    if not out:
        return ""
    return '<div class="voices">' + "".join(out) + "</div>"


def seg_list(items, warn=False):
    lis = "".join(f'<li>{esc(x["theme"])}<b>{x["n"]}件</b></li>' for x in items)
    return f"<ul>{lis}</ul>"


def build_month_html(s, month):
    y, mo, last = jp_period(month)
    r = reiwa(y)
    vol = vol_of(month)
    N = s["meta"]["N"]
    osp = s["origin_split"]
    sat = s["satisfaction"]; rev = s["revisit"]; nps = s["nps"]
    ft = s["free_text"]
    exp = ft["experience"]; food = ft["food"]; issues = ft["issues"]
    exp_top = [x for x in exp if x["n"] > 0]
    food_top = [x for x in food if x["n"] > 0]
    issue_top = [x for x in issues if x["n"] > 0]
    gender = s["gender"]; age = s["age"]
    age_order = ["20代以下", "30代", "40代", "50代", "60代以上"]
    vcs = s["visit_count_summary"]
    en_month = datetime.date(y, mo, 1).strftime("%B %Y")

    female = gender.get("女性", 0); male = gender.get("男性", 0)
    fpct = round(female / N * 100, 1); mpct = round(male / N * 100, 1)
    genyou = age.get("30代", 0) + age.get("40代", 0) + age.get("50代", 0)
    genyou_pct = round(genyou / N * 100, 1)
    comp = s["companion"]
    comp_top = comp[0]["name"] if comp else "—"
    comp_top_pct = round(comp[0]["n"] / N * 100, 1) if comp else 0

    # ---- 第1章 lead ----
    exp_names = "・".join(f'「{x["theme"]}」({x["pct"]}%)' for x in exp_top[:3])
    issue_name = issue_top[0]["theme"] if issue_top else "—"
    lead1 = (
        f'本月、やんばるハッピーアンケートには県内外より<b>{N:,}件</b>の有効回答が寄せられた。'
        f'回答者の<b>体験・サービス満足度{sat["satisfied_pct"]}％</b>（「大変満足」「満足」の合計）、'
        f'<b>再来訪意向{rev["intent_pct"]}％</b>（「必ず来たい」「来たい」の合計）、'
        f'<b>NPS＋{nps["nps"]}</b>（推奨者{nps["promoter_pct"]}％・批判者{nps["detractor_pct"]}％）を記録し、'
        f'やんばる体験への評価は引き続き高い水準にある。自由記述では感動の中核として{exp_names}が上位を占め、'
        f'課題側では<b>「{issue_name}」</b>を筆頭に受入環境への要望が寄せられた。'
    )

    # ---- summary box ----
    summary_box = f'''
    <div class="summary-box"><div class="row">
      <div class="cell"><div class="label">有効回答数</div><div class="value">{N:,}<span class="unit">件</span></div><div class="sub">県外 {osp["県外pct"]}% ／ 県内 {osp["県内pct"]}%</div></div>
      <div class="cell"><div class="label">体験・サービス満足度</div><div class="value">{sat["satisfied_pct"]}<span class="unit">%</span></div><div class="sub">「大変満足」{sat["very_satisfied_pct"]}% を含む</div></div>
      <div class="cell"><div class="label">再来訪意向</div><div class="value">{rev["intent_pct"]}<span class="unit">%</span></div><div class="sub">「必ず来たい」{rev["must_pct"]}% を含む</div></div>
      <div class="cell"><div class="label">NPS（推奨度）</div><div class="value">+{nps["nps"]}</div><div class="sub">推奨者 {nps["promoter_pct"]}% ／ 批判者 {nps["detractor_pct"]}%</div></div>
    </div></div>'''

    # ---- keypoints ----
    kp = []
    kp.append(f'有効回答は<b>{N:,}件</b>。県外 {osp["県外pct"]}%・県内 {osp["県内pct"]}% で構成され、満足度 {sat["satisfied_pct"]}%・再来訪意向 {rev["intent_pct"]}%・NPS＋{nps["nps"]} と高評価が維持された。')
    if exp_top:
        kp.append(f'感動の中核は「{exp_top[0]["theme"]}」（自由記述の{exp_top[0]["pct"]}%が言及）。' + (f'これに{exp_names}が続き、やんばる体験の価値構造を形成している。' if len(exp_top) >= 2 else ''))
    if food_top:
        kp.append(f'食では「{food_top[0]["theme"]}」（{food_top[0]["pct"]}%）が中心。' + (f'「{food_top[1]["theme"]}」など地元食材・体験型の食への言及も見られる。' if len(food_top) >= 2 else ''))
    if issue_top:
        names = "・".join(f'「{x["theme"]}」' for x in issue_top[:3])
        kp.append(f'課題（改善要望ありは全体の{ft["kaizen_ari_pct"]}%）は{names}に集中。受入環境の整備が継続テーマ。')
    kp.append(f'訪問回数では初回 {vcs["first_pct"]}% に対し、4回目以上のリピーターが {vcs["rep4plus_pct"]}%（11回目以上 {vcs["rep11_pct"]}%）。やんばるが「来るほど深まる土地」である構図が確認された。')
    keypoints = '<div class="keypoint"><h4>本月の要旨</h4><ol>' + "".join(f"<li>{x}</li>" for x in kp) + "</ol></div>"

    # ---- 第2章 ----
    top_prefs = "・".join(short_pref(x["name"]) for x in s["origin_top10"][1:5]) if len(s["origin_top10"]) >= 5 else ""
    lead2 = (
        f'本月の回答者は、沖縄県内 {osp["県内"]:,}件（{osp["県内pct"]}%）、県外 {osp["県外"]:,}件（{osp["県外pct"]}%）で構成された。'
        f'県外では<b>{top_prefs}</b>などが上位を占めた。性別構成は女性{fpct}%・男性{mpct}%、'
        f'年代は<b>30〜50代の現役層が{genyou_pct}%</b>を占める。同行者構成は<b>「{comp_top}」が{comp_top_pct}%</b>で最大セグメントとなった。'
    )
    visit_para = (
        f'訪問回数では、初回来訪が{vcs["first_pct"]}%にとどまる一方、'
        f'<b>4回目以上のリピーターが{vcs["rep4plus_pct"]}%</b>（うち11回目以上が{vcs["rep11_pct"]}%）を占めた。'
        f'やんばるが「初訪で出会い、リピートで深まる」性質を持つ観光地であることが、本月の母数でも裏付けられた。'
    )

    # ---- 第3章 ----
    lead3 = (
        f'本月の自由記述（ポジティブ n={ft["pos_n"]:,}／改善要望 n={ft["neg_n"]:,}）から、'
        f'感動を<b>「観光・体験」「食」</b>に、課題を<b>「改善要望」</b>に分けてキーワード抽出により整理した。'
        f'観光・体験では「{exp_top[0]["theme"]}」が{exp_top[0]["n"]}件と最多で、食・課題もそれぞれ下表のテーマに意見が集まった。'
    )
    exp_table = theme_table(exp_top, N)
    food_table = theme_table(food_top, N)
    issue_table = theme_table(issue_top, ft["kaizen_ari"], warn=True, pct_field="pct")
    exp_voices = voice_blocks(s["voices_exp"], exp_top, k=3)
    food_voices = voice_blocks(s["voices_food"], food_top, k=2)
    issue_voices = voice_blocks(s["voices_neg"], issue_top, k=4, warn=True)
    exp_p = (f'最も多く語られた「{exp_top[0]["theme"]}」（{exp_top[0]["pct"]}%）を中心に、' +
             ("、".join(f'「{x["theme"]}」' for x in exp_top[1:3]) if len(exp_top) >= 2 else "") +
             'などがやんばる体験の感動を構成している。')
    food_p = (f'食の感動は「{food_top[0]["theme"]}」を筆頭に、地元食材・カフェ・郷土料理など複数の領域に分散して語られた。' if food_top else "")
    issue_p = (f'改善要望は「{issue_top[0]["theme"]}」（{issue_top[0]["n"]}件）を最多に、移動・滞在の選択肢に関する声が中心を占めた。改善要望「あり」は全回答の{ft["kaizen_ari_pct"]}%。' if issue_top else "")

    # ---- 第4章（性別） ----
    sg = s["seg_gender"]
    def gender_card(label, key):
        d = sg[key]
        sec = f'<div class="seg-section"><h5>ポジティブ感動 ── 観光・体験</h5>{seg_list(d["exp"])}</div>'
        if d.get("food"):
            sec += f'<div class="seg-section"><h5>ポジティブ感動 ── 食</h5>{seg_list(d["food"])}</div>'
        sec += f'<div class="seg-section"><h5 class="warn">課題・改善要望</h5>{seg_list(d["issue"])}</div>'
        top_e = d["exp"][0]["theme"] if d["exp"] else "—"
        top_i = d["issue"][0]["theme"] if d["issue"] else "—"
        note = f'感動の最上位は「{top_e}」、課題の最上位は「{top_i}」。この層の関心の重心を示す。'
        return f'<div class="seg-card"><h4>{label}</h4><div class="n">n={d["n"]:,}</div>{sec}<p class="seg-note">{note}</p></div>'
    lead4 = '性別による感動・課題の構造を、自由記述のテーマ別件数で比較した。男女に共通する価値と、層ごとに異なる関心・困りごとが読み取れる。'
    ch4 = f'<div class="seg-2col">{gender_card("女性回答者","女性")}{gender_card("男性回答者","男性")}</div>'

    # ---- 第5章（年代） ----
    sa = s["seg_age"]
    minis = []
    for a in age_order:
        d = sa[a]
        exp_ul = "".join(f'<li>{esc(x["theme"])}<b>{x["n"]}</b></li>' for x in d["exp"][:3]) or "<li>—</li>"
        iss_ul = "".join(f'<li>{esc(x["theme"])}<b>{x["n"]}</b></li>' for x in d["issue"][:3]) or "<li>—</li>"
        minis.append(f'<div class="seg-mini"><h5>{a}</h5><div class="n">n={d["n"]:,}</div>'
                     f'<div class="lbl">体験</div><ul>{exp_ul}</ul>'
                     f'<div class="lbl warn">課題</div><ul>{iss_ul}</ul></div>')
    lead5 = '年代別に感動と課題のテーマを比較した。共通の感動軸を持ちつつ、年代によって課題の重心（移動・施設・案内など）が移ろう様子が見える。'
    ch5 = '<div class="seg-5col">' + "".join(minis) + "</div>"

    # ---- 第6章（同行者） ----
    sc = s["seg_companion"]
    comp_keys = ["パートナー", "家族", "ひとり旅", "友人"]
    def comp_card(key):
        d = sc[key]
        exp_sec = f'<div class="seg-section"><h5>体験</h5>{seg_list(d["exp"][:3])}</div>'
        iss_sec = f'<div class="seg-section"><h5 class="warn">課題</h5>{seg_list(d["issue"][:3])}</div>'
        top_e = d["exp"][0]["theme"] if d["exp"] else "—"
        return f'<div class="seg-card"><h4>{key}</h4><div class="n">n={d["n"]:,}</div>{exp_sec}{iss_sec}<p class="seg-note">この層の感動の中心は「{top_e}」。</p></div>'
    lead6 = '同行者構成別に感動と課題を整理した。誰と訪れるかによって、求める体験と直面する課題が異なることが分かる。'
    ch6 = (f'<div class="seg-2col">{comp_card("パートナー")}{comp_card("家族")}</div>'
           f'<div class="seg-2col" style="margin-top:16px;">{comp_card("ひとり旅")}{comp_card("友人")}</div>')

    # ---- 第7章（提案・データ連動の自動生成） ----
    proposals = []
    if exp_top:
        proposals.append(("情報発信", f'感動の最上位「{exp_top[0]["theme"]}」を本月の主題に編集する',
            f'本月、自由記述で最も多く語られた感動は「{exp_top[0]["theme"]}」（{exp_top[0]["pct"]}%・{exp_top[0]["n"]}件）であった。'
            + (f'これに「{exp_top[1]["theme"]}」「{exp_top[2]["theme"]}」が続く。' if len(exp_top) >= 3 else '')
            + 'この感動軸を核に、特集ページ・SNS・宿泊施設の発信を統一テーマで束ねる。',
            f'女性{fpct}%・現役層中心／「{comp_top}」層'))
    if issue_top:
        proposals.append(("受入環境", f'最多の課題「{issue_top[0]["theme"]}」への対応を優先検討する',
            f'改善要望で最も多かったのは「{issue_top[0]["theme"]}」（{issue_top[0]["n"]}件）。改善要望「あり」は全回答の{ft["kaizen_ari_pct"]}%にのぼる。'
            '自由記述の具体的な声を起点に、関係機関と連携した受入環境の改善を検討する。',
            'レンタカー利用者／滞在型観光客'))
    # 交通系の課題があれば
    transit = next((x for x in issue_top if "交通" in x["theme"] or "道路" in x["theme"]), None)
    if transit:
        proposals.append(("交通・受入", f'「{transit["theme"]}」の緩和に向けた段階的施策を検討する',
            f'「{transit["theme"]}」は{transit["n"]}件と移動面の主要課題。運行情報のデジタル化・周遊ルートの工夫など、実装可能な打ち手から着手する。',
            'パートナー層／ひとり旅層／公共交通利用客'))
    if food_top:
        proposals.append(("商品開発", f'食の感動「{food_top[0]["theme"]}」を体験商品として磨く',
            f'食では「{food_top[0]["theme"]}」（{food_top[0]["n"]}件）が中心。地元食材・体験型の食を周遊コースに組み込み、滞在価値を高める。',
            '家族・友人層／滞在型観光客'))
    # リピーター提案
    proposals.append(("リピーター", 'リピーターの厚みを活かした継続来訪施策を設計する',
        f'4回目以上のリピーターが{vcs["rep4plus_pct"]}%（11回目以上{vcs["rep11_pct"]}%）と厚い。再来訪意向も{rev["intent_pct"]}%と高く、'
        '季節ごとの新体験・限定情報の発信で来訪頻度の維持・向上を図る。',
        '既存リピーター／パートナー・ひとり旅層'))
    proposals = proposals[:5]
    prop_html = ""
    for i, (tag, title, body, target) in enumerate(proposals, 1):
        prop_html += (f'<div class="proposal"><div class="head"><div class="no">提案{i}</div>'
                      f'<div class="tag">{tag}</div></div><h4>{esc(title)}</h4><p>{esc(body)}</p>'
                      f'<div class="target"><strong>主要ターゲット</strong>{esc(target)}</div></div>')
    lead7 = '本月の集計・分析（自由記述のテーマ別件数）に直接の根拠を持つアクションを提案する。各提案には主要ターゲットを併記した。'

    # ---- Chart.js データ ----
    origin_labels = [short_pref(x["name"]) for x in s["origin_top10"]]
    origin_data = [x["n"] for x in s["origin_top10"]]
    ag = s["age_gender"]
    age_f = [ag[a]["女性"] for a in age_order]
    age_m = [ag[a]["男性"] for a in age_order]
    age_o = [ag[a]["その他・無回答"] for a in age_order]
    comp_labels = [x["name"] for x in comp[:9]]
    comp_data = [x["n"] for x in comp[:9]]
    vc_keys = ["初めて", "2-3回目", "4-5回目", "6-10回目", "11回目以上"]
    vc_data = [s["visit_count"].get(k, 0) for k in vc_keys]

    chart_js = f'''
Chart.defaults.font.family = '"Noto Sans JP", sans-serif';
Chart.defaults.font.size = 11; Chart.defaults.color = '#555'; Chart.defaults.borderColor = '#e3e3e3';
const ACCENT='#2f5a3f', ACCENT_LIGHT='#6e8d77', ACCENT_PALE='#a8baa9';
new Chart(document.getElementById('chartOrigin'),{{type:'bar',data:{{labels:{json.dumps(origin_labels, ensure_ascii=False)},datasets:[{{data:{origin_data},backgroundColor:ACCENT,borderWidth:0,barThickness:14}}]}},options:{{maintainAspectRatio:false,indexAxis:'y',scales:{{x:{{grid:{{color:'#eee'}}}},y:{{grid:{{display:false}}}}}},plugins:{{legend:{{display:false}}}}}}}});
new Chart(document.getElementById('chartAge'),{{type:'bar',data:{{labels:{json.dumps(age_order, ensure_ascii=False)},datasets:[{{label:'女性',data:{age_f},backgroundColor:ACCENT,borderWidth:0}},{{label:'男性',data:{age_m},backgroundColor:ACCENT_LIGHT,borderWidth:0}},{{label:'その他・無回答',data:{age_o},backgroundColor:ACCENT_PALE,borderWidth:0}}]}},options:{{maintainAspectRatio:false,scales:{{x:{{stacked:true,grid:{{display:false}}}},y:{{stacked:true,grid:{{color:'#eee'}}}}}},plugins:{{legend:{{position:'bottom',labels:{{boxWidth:12,padding:12}}}}}}}}}});
new Chart(document.getElementById('chartCompanion'),{{type:'bar',data:{{labels:{json.dumps(comp_labels, ensure_ascii=False)},datasets:[{{data:{comp_data},backgroundColor:ACCENT,borderWidth:0,barThickness:12}}]}},options:{{maintainAspectRatio:false,indexAxis:'y',scales:{{x:{{grid:{{color:'#eee'}}}},y:{{grid:{{display:false}}}}}},plugins:{{legend:{{display:false}}}}}}}});
new Chart(document.getElementById('chartVisitCount'),{{type:'bar',data:{{labels:{json.dumps(vc_keys, ensure_ascii=False)},datasets:[{{data:{vc_data},backgroundColor:ACCENT,borderWidth:0,barThickness:34}}]}},options:{{maintainAspectRatio:false,scales:{{x:{{grid:{{display:false}}}},y:{{grid:{{color:'#eee'}}}}}},plugins:{{legend:{{display:false}}}}}}}});
'''

    issue_date = f'令和{reiwa(datetime.date.today().year)}年{datetime.date.today().month}月{datetime.date.today().day}日'

    html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>やんばるハッピーアンケート月次レポート — 令和{r}年{mo}月</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&family=Noto+Serif+JP:wght@400;500;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>{CSS}</style>
</head>
<body>
<header class="page-header"><div class="container">
  <div>一般社団法人沖縄やんばるDMO</div>
  <div>やんばるハッピーアンケート月次レポート　Vol. {vol}（令和{r}年{mo}月）</div>
</div></header>
<div class="container">
  <section class="cover">
    <div class="category">やんばるハッピーアンケート月次レポート</div>
    <h1>令和{r}年{mo}月度<br/>やんばるハッピーアンケート 集計報告</h1>
    <div class="subtitle">YAMBARU HAPPY SURVEY ／ MONTHLY REPORT — {en_month}</div>
    <dl class="meta">
      <div><dt>号数</dt><dd>Vol. {vol}</dd></div>
      <div><dt>集計期間</dt><dd>令和{r}年{mo}月1日〜{last}日</dd></div>
      <div><dt>有効回答数</dt><dd>{N:,}件</dd></div>
      <div><dt>発行日</dt><dd>{issue_date}</dd></div>
    </dl>
  </section>
  <nav class="toc"><h2>目　次</h2><ol>
    <li><a href="#c1">{mo}月の概況と要旨</a></li>
    <li><a href="#c2">回答者プロフィール</a></li>
    <li><a href="#c3">{mo}月を彩るトピック（観光・体験／食／課題）</a></li>
    <li><a href="#c4">性別で見る感動と課題</a></li>
    <li><a href="#c5">年代で見る感動と課題</a></li>
    <li><a href="#c6">同行者で見る感動と課題</a></li>
    <li><a href="#c7">アクション提案</a></li>
  </ol></nav>
  <main>
  <section class="chapter" id="c1"><div class="chapter-head"><div class="num">第1章</div><h2>{mo}月の概況と要旨</h2></div>
    <p class="lead">{lead1}</p>
    {summary_box}
    {keypoints}
    <div class="autonote">本レポートの集計値は GitHub 公開データ（yambarudmo/yanbaru-oki-survey）を毎月1日に自動取得し、機械的に算出・生成したものです。本文・要旨・提案はデータ連動の自動生成テキストであり、事実（集計値）に基づきます。</div>
  </section>
  <section class="chapter" id="c2"><div class="chapter-head"><div class="num">第2章</div><h2>回答者プロフィール</h2></div>
    <p class="lead">{lead2}</p>
    <h3 class="sub">2-1　居住地・年代</h3>
    <div class="chart-row">
      <div class="chart-block"><div class="ttl">居住地（上位10）</div><div class="note">n={N:,}　単位：件</div><div class="chart-box"><canvas id="chartOrigin"></canvas></div></div>
      <div class="chart-block"><div class="ttl">年代別構成</div><div class="note">n={N:,}　単位：件</div><div class="chart-box"><canvas id="chartAge"></canvas></div></div>
    </div>
    <h3 class="sub">2-2　同行者・訪問回数</h3>
    <div class="chart-row">
      <div class="chart-block"><div class="ttl">同行者構成</div><div class="note">n={N:,}　単位：件</div><div class="chart-box"><canvas id="chartCompanion"></canvas></div></div>
      <div class="chart-block"><div class="ttl">訪問回数</div><div class="note">n={N:,}　単位：件</div><div class="chart-box"><canvas id="chartVisitCount"></canvas></div></div>
    </div>
    <p style="font-size:13.5px;color:var(--text-mute);margin-top:16px;">{visit_para}</p>
  </section>
  <section class="chapter" id="c3"><div class="chapter-head"><div class="num">第3章</div><h2>{mo}月を彩るトピック</h2></div>
    <p class="lead">{lead3}</p>
    <h3 class="sub">3-1　ポジティブな感動 ── 観光・体験</h3>
    {exp_table}<p>{exp_p}</p>{exp_voices}
    <h3 class="sub">3-2　ポジティブな感動 ── 食</h3>
    {food_table}<p>{food_p}</p>{food_voices}
    <h3 class="sub">3-3　課題・改善要望</h3>
    <p style="font-size:13.5px;color:var(--text-mute);">改善要望「あり」と回答した{ft["kaizen_ari"]:,}名（全回答の{ft["kaizen_ari_pct"]}%）の自由記述から分類。</p>
    {issue_table}<p>{issue_p}</p>{issue_voices}
  </section>
  <section class="chapter" id="c4"><div class="chapter-head"><div class="num">第4章</div><h2>性別で見る感動と課題</h2></div>
    <p class="lead">{lead4}</p>{ch4}
  </section>
  <section class="chapter" id="c5"><div class="chapter-head"><div class="num">第5章</div><h2>年代で見る感動と課題</h2></div>
    <p class="lead">{lead5}</p>{ch5}
  </section>
  <section class="chapter" id="c6"><div class="chapter-head"><div class="num">第6章</div><h2>同行者で見る感動と課題</h2></div>
    <p class="lead">{lead6}</p>{ch6}
  </section>
  <section class="chapter" id="c7"><div class="chapter-head"><div class="num">第7章</div><h2>アクション提案</h2></div>
    <p class="lead">{lead7}</p>
    <div class="proposal-list">{prop_html}</div>
  </section>
  </main>
</div>
<footer><div class="container">
  <div class="footer-grid">
    <div><h5>本レポートについて</h5><p>本レポートは、やんばるエリア（沖縄本島北部）の宿泊施設・観光拠点・飲食店に設置されたQRコードから回答された国内観光ウェブアンケートを集計し、自由記述を含めてテーマ別に編集したものです。毎月1日に前月分を自動生成・公開しています。</p></div>
    <div><h5>調査概要</h5><p>集計期間：令和{r}年{mo}月1日〜{last}日<br/>有効回答数：n＝{N:,}件<br/>対象：国内居住者<br/>内訳：沖縄県内 {osp["県内pct"]}% ／ 県外 {osp["県外pct"]}%<br/>集計方法：単純集計・自由記述キーワード抽出</p></div>
    <div><h5>ご利用にあたって</h5><p>宿泊・飲食・観光・交通事業者／自治体・観光協会・DMO／商品開発・プロモーション・企画立案にあたる方々の根拠データとして自由にご活用いただけます。</p></div>
  </div>
  <div class="colophon"><div>発行：一般社団法人沖縄やんばるDMO</div><div>YAMBARU HAPPY SURVEY ／ Vol. {vol} — {issue_date}発行</div></div>
</div></footer>
<script>{chart_js}</script>
</body>
</html>'''
    return html


def build_landing(manifest):
    cards = []
    for e in sorted(manifest, key=lambda x: x["month"], reverse=True):
        y, mo, last = jp_period(e["month"])
        r = reiwa(y)
        ym = e["month"].replace("-", "")
        cards.append(
            f'      <li>\n        <a class="card" href="{ym}/">\n'
            f'          <div class="vol">Vol. {e["vol"]} ／ 国内観光客</div>\n'
            f'          <div class="t">令和{r}年{mo}月度 集計報告</div>\n'
            f'          <div class="m">集計期間：{y}年{mo}月1日〜{last}日　／　有効回答 n＝{e["n"]:,}件</div>\n'
            f'        </a>\n      </li>'
        )
    cards_html = "\n".join(cards)
    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>やんばるハッピーアンケート 月次レポート</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&family=Noto+Serif+JP:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root{{ --text:#222; --mute:#555; --sub:#777; --rule:#ccc; --rule-light:#e3e3e3; --bg:#fff; --bg-alt:#f6f5f1; --accent:#2f5a3f; }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:"Noto Serif JP","游明朝",serif;line-height:1.9;font-feature-settings:"palt"}}
  .container{{max-width:920px;margin:0 auto;padding:0 32px}}
  header{{border-bottom:1px solid var(--rule);padding:16px 0;font-family:"Noto Sans JP",sans-serif;font-size:12px;color:var(--mute)}}
  .hero{{padding:64px 0 40px;border-bottom:2px solid var(--text)}}
  .hero .cat{{font-family:"Noto Sans JP",sans-serif;font-size:13px;color:var(--accent);font-weight:500;letter-spacing:.1em;margin-bottom:14px}}
  .hero h1{{font-size:30px;font-weight:700;line-height:1.5;margin-bottom:14px}}
  .hero p{{font-family:"Noto Sans JP",sans-serif;font-size:14px;color:var(--mute)}}
  main{{padding:40px 0 80px}}
  h2{{font-size:16px;font-weight:700;border-bottom:1px solid var(--rule);padding-bottom:8px;margin-bottom:20px}}
  .list{{list-style:none;display:grid;gap:14px}}
  .card{{border:1px solid var(--rule-light);padding:20px 24px;display:block;text-decoration:none;color:var(--text);transition:border-color .2s}}
  .card:hover{{border-color:var(--accent)}}
  .card .vol{{font-family:"Noto Sans JP",sans-serif;font-size:11px;color:var(--accent);font-weight:500;margin-bottom:4px}}
  .card .t{{font-size:18px;font-weight:700;margin-bottom:6px}}
  .card .m{{font-family:"Noto Sans JP",sans-serif;font-size:12px;color:var(--sub)}}
  footer{{background:var(--bg-alt);border-top:2px solid var(--text);padding:28px 0;margin-top:40px;font-family:"Noto Sans JP",sans-serif;font-size:11px;color:var(--sub)}}
  .footer-row{{display:flex;justify-content:space-between}}
  @media(max-width:760px){{.container{{padding:0 16px}}.hero h1{{font-size:22px}}.footer-row{{flex-direction:column;gap:6px}}}}
</style>
</head>
<body>
<header><div class="container">一般社団法人沖縄やんばるDMO</div></header>
<div class="container">
  <section class="hero">
    <div class="cat">YAMBARU HAPPY SURVEY ／ MONTHLY REPORT</div>
    <h1>やんばるハッピーアンケート<br/>月次レポート</h1>
    <p>やんばるエリアの国内観光ウェブアンケートを月次で集計・分析したレポートを公開しています。</p>
  </section>
  <main>
    <h2>レポート一覧</h2>
    <ul class="list">
{cards_html}
    </ul>
  </main>
</div>
<footer>
  <div class="container">
    <div class="footer-row">
      <div>発行：一般社団法人沖縄やんばるDMO</div>
      <div>YAMBARU HAPPY SURVEY MONTHLY REPORT</div>
    </div>
  </div>
</footer>
</body>
</html>
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default=None, help="対象月 YYYY-MM（既定=前月）")
    ap.add_argument("--csv", default=None, help="ローカルCSV（テスト用）")
    args = ap.parse_args()
    month = args.month or prev_month()
    print(f"[generate] 対象月 = {month}")

    # 1) 集計（build_report.py）。N=0 なら build_report が非ゼロ終了 → 例外伝播で停止
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [sys.executable, os.path.join(SCRIPTS, "build_report.py"), "--month", month, "--out", tmp]
        if args.csv:
            cmd += ["--csv", args.csv]
        res = subprocess.run(cmd)
        if res.returncode != 0:
            # 対象月のデータ未更新（N=0）等。無人運用では「正常終了して何もしない」
            # → 後続日のリトライ実行で拾う（空レポートは発行しない）。
            print("[generate] SKIP: 対象月のデータが未取得/0件のため発行を見送ります（翌日以降に再試行）。", file=sys.stderr)
            sys.exit(0)
        with open(os.path.join(tmp, "summary.json"), encoding="utf-8") as f:
            s = json.load(f)

    N = s["meta"]["N"]; vol = vol_of(month)

    # 2) 当月HTML
    ym = month.replace("-", "")
    out_dir = os.path.join(REPO, ym)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_month_html(s, month))
    print(f"[generate] {ym}/index.html を生成（N={N:,}, Vol.{vol}）")

    # 3) マニフェスト更新 + トップ再生成
    mpath = os.path.join(REPO, "reports.json")
    manifest = []
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as f:
            manifest = json.load(f)
    manifest = [e for e in manifest if e["month"] != month]
    manifest.append({"month": month, "vol": vol, "n": N})
    manifest.sort(key=lambda x: x["month"])
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(os.path.join(REPO, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_landing(manifest))
    print(f"[generate] index.html（一覧）を再生成（{len(manifest)}件）")
    print(f"[generate] DONE  N={N:,}  満足度={s['satisfaction']['satisfied_pct']}%  再来訪={s['revisit']['intent_pct']}%  NPS=+{s['nps']['nps']}")


if __name__ == "__main__":
    main()
