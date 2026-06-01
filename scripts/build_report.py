# -*- coding: utf-8 -*-
"""
やんばる国内観光客アンケート 月次集計スクリプト（汎用版）

GitHub( yambarudmo/yanbaru-oki-survey )の国内データを取得し、指定した月（YYYY-MM）の
回答を抽出して、レポートに必要な全指標 + 自由記述コーディング結果を summary.json に出力する。

使い方:
    python build_report.py --month 2026-05 --out ./out [--csv /path/to/local.csv]

データ取得の重要な注意:
  - トップの yanbaru_domestic_survey/all.csv は更新が遅れ、直近月を含まないことがある。
  - 直近月は yanbaru_domestic_survey/<最新の YYYYMMDD~ フォルダ>/all.csv に入っている。
  - 本スクリプトは --csv 未指定時、両方を取得して結合し、指定月で抽出する（重複は除去）。
集計値はすべて N・算出方法を併記する思想。事実（集計）と解釈（示唆）は分離してレポート側で記述する。
"""
import argparse, json, os, io, sys, urllib.request, re
import pandas as pd

RAW_BASE = "https://raw.githubusercontent.com/yambarudmo/yanbaru-oki-survey/main"
API_BASE = "https://api.github.com/repos/yambarudmo/yanbaru-oki-survey/contents"
DOM_DIR = "yanbaru_domestic_survey"

# ---- 満足度の定義（やんばる確定仕様: 「大変満足＋満足」）----
SATISFIED_LABELS = ["大変満足", "満足"]


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "yanbaru-report"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def load_domestic(local_csv=None):
    """国内データを取得して DataFrame で返す。"""
    if local_csv:
        return pd.read_csv(local_csv, low_memory=False)
    frames = []
    # 1) トップの all.csv
    try:
        frames.append(pd.read_csv(io.BytesIO(_fetch(f"{RAW_BASE}/{DOM_DIR}/all.csv")), low_memory=False))
    except Exception as e:
        print("warn: top all.csv 取得失敗:", e, file=sys.stderr)
    # 2) 最新の "YYYYMMDD~" サブフォルダの all.csv（直近月を含む）
    try:
        listing = json.loads(_fetch(f"{API_BASE}/{DOM_DIR}").decode("utf-8"))
        subdirs = sorted([x["name"] for x in listing if x["type"] == "dir" and re.match(r"\d{8}~", x["name"])])
        for sd in subdirs[-2:]:  # 直近2フォルダを念のため取得
            try:
                frames.append(pd.read_csv(io.BytesIO(_fetch(f"{RAW_BASE}/{DOM_DIR}/{sd}/all.csv")), low_memory=False))
            except Exception as e:
                print(f"warn: {sd}/all.csv 取得失敗:", e, file=sys.stderr)
    except Exception as e:
        print("warn: サブフォルダ一覧取得失敗:", e, file=sys.stderr)
    if not frames:
        sys.exit("国内データを取得できませんでした。--csv でローカルファイルを指定してください。")
    df = pd.concat(frames, ignore_index=True)
    # 重複除去（Synergy!ID + HistoryID があれば優先）
    keys = [c for c in ["Synergy!ID", "HistoryID"] if c in df.columns]
    if keys:
        df = df.drop_duplicates(subset=keys, keep="last")
    return df


def age_band(birth, base_year):
    try:
        a = base_year - int(birth)
    except Exception:
        return "不明"
    if a <= 29: return "20代以下"
    if a <= 39: return "30代"
    if a <= 49: return "40代"
    if a <= 59: return "50代"
    return "60代以上"


def code(series, themes):
    series = series.fillna("").astype(str)
    res = []
    for name, pat in themes:
        hit = series.str.contains(pat, regex=True, na=False) & series.str.strip().ne("")
        res.append({"theme": name, "n": int(hit.sum())})
    res.sort(key=lambda x: -x["n"])
    return res


# ====== テーマ辞書（必要に応じて毎月見直す。新トピックは追加すること）======
EXP_THEMES = [
    ("やんばるの森・自然", r"自然|森|大自然|緑|ジャングル|木々"),
    ("海・ビーチ", r"(?<!美ら)海|ビーチ|青い海|ウミガメ|シュノーケ|マリン|海岸|サンゴ|珊瑚"),
    ("のんびり・癒し・静けさ", r"のんびり|癒|静か|ゆっくり|落ち着|混んでな|空いて|リラックス|ゆったり|穏やか"),
    ("美ら海水族館・海洋博公園", r"美ら海|水族館|海洋博|ジンベ"),
    ("ヤンバルクイナ・固有種", r"クイナ|やんばるくいな|固有種|生き物|野生動物|希少"),
    ("リゾート・宿泊体験", r"リゾート|ホテル|宿|プール|滞在|泊"),
    ("テーマパーク（ジャングリア等）", r"ジャングリア|JUNGLIA|パイナップルパーク|パーク|テーマパーク"),
    ("ドライブ・絶景", r"ドライブ|絶景|景色|眺め|ロケーション|景観"),
]
FOOD_THEMES = [
    ("道の駅・地元食材", r"道の駅|地元の|地元食材|野菜|果物|パイナップル(?!パーク)|マンゴー|農産|直売"),
    ("オリオンビール・工場見学", r"オリオン|ビール工場|工場見学"),
    ("カフェ・コーヒー", r"カフェ|コーヒー|喫茶"),
    ("沖縄そば・郷土料理", r"沖縄そば|そば|郷土料理|沖縄料理|タコライス|ソーキ"),
    ("ホテル・リゾート飲食", r"ホテルの(食|料理|朝食|レストラン)|朝食|ディナー|ビュッフェ"),
    ("食事全般・美味しさ", r"美味|おいし|グルメ|食事が|料理が|飲食"),
]
NEG_THEMES = [
    ("道路・渋滞", r"渋滞|道路|舗装|混雑|車が多|道が狭"),
    ("公共交通の少なさ", r"バス|公共交通|電車|モノレール|交通機関|タクシー|二次交通"),
    ("店・食の選択肢／営業時間", r"営業時間|閉ま|店が少な|飲食店|お店|早く閉|夜の|食事(?:処|どころ|の選択)|外食"),
    ("案内・標識の不明瞭さ", r"看板|標識|案内|分かりづら|わかりにく|ナビ|地図"),
    ("トイレ・休憩所", r"トイレ|休憩|お手洗"),
    ("駐車場", r"駐車"),
    ("雨天対応・屋根動線", r"雨|屋根|屋内"),
    ("施設・観光地の少なさ", r"少ない|施設が|遊ぶ場所|アクティビティ"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True, help="対象月 YYYY-MM 例: 2026-05")
    ap.add_argument("--out", default="./out", help="出力ディレクトリ")
    ap.add_argument("--csv", default=None, help="ローカルCSV（指定時はGitHub取得を行わない）")
    args = ap.parse_args()
    base_year = int(args.month.split("-")[0])
    os.makedirs(args.out, exist_ok=True)

    df = load_domestic(args.csv)
    df["dt"] = pd.to_datetime(df["回答日時"], errors="coerce")
    m = df[df["dt"].dt.to_period("M").astype(str) == args.month].copy()
    N = len(m)
    if N == 0:
        sys.exit(f"対象月 {args.month} の回答が0件でした。データの更新状況を確認してください。")
    m["年代"] = m["生年"].apply(lambda b: age_band(b, base_year))

    out = {"meta": {"N": int(N), "month": args.month,
                    "source": "yambarudmo/yanbaru-oki-survey yanbaru_domestic_survey",
                    "satisfied_def": "＋".join(SATISFIED_LABELS)}}

    # 居住地
    ken = m["都道府県"].fillna("不明")
    ok = int((ken == "沖縄県").sum())
    out["origin_split"] = {"県内": ok, "県外": int(N - ok),
                           "県内pct": round(ok / N * 100, 1), "県外pct": round((N - ok) / N * 100, 1)}
    out["origin_top10"] = [{"name": k, "n": int(v)} for k, v in ken.value_counts().head(10).items()]

    # 満足度
    sat = m["体験・サービス満足度(やんばるエリア)"].value_counts()
    sat_pos = int(sum(sat.get(l, 0) for l in SATISFIED_LABELS))
    out["satisfaction"] = {"counts": {k: int(v) for k, v in sat.items()},
                           "satisfied_pct": round(sat_pos / N * 100, 1),
                           "very_satisfied_pct": round(int(sat.get("大変満足", 0)) / N * 100, 1)}
    # 再来訪
    rev = m["今後の来訪意向(やんばるエリア)"].value_counts()
    rev_pos = int(rev.get("必ず来たい", 0) + rev.get("来たい", 0))
    out["revisit"] = {"counts": {k: int(v) for k, v in rev.items()},
                      "intent_pct": round(rev_pos / N * 100, 1),
                      "must_pct": round(int(rev.get("必ず来たい", 0)) / N * 100, 1)}
    # NPS
    nps = pd.to_numeric(m["推奨度(やんばるエリア)"], errors="coerce").dropna()
    n2 = len(nps); pro = int((nps >= 9).sum()); det = int((nps <= 6).sum())
    out["nps"] = {"n": n2, "promoters": pro, "detractors": det,
                  "promoter_pct": round(pro / n2 * 100, 1), "detractor_pct": round(det / n2 * 100, 1),
                  "nps": round((pro - det) / n2 * 100, 1)}
    # 属性
    out["gender"] = {k: int(v) for k, v in m["性別"].fillna("無回答").value_counts().items()}
    age_order = ["20代以下", "30代", "40代", "50代", "60代以上"]
    out["age"] = {k: int((m["年代"] == k).sum()) for k in age_order}
    out["age_gender"] = {a: {"女性": int(((m["年代"] == a) & (m["性別"] == "女性")).sum()),
                              "男性": int(((m["年代"] == a) & (m["性別"] == "男性")).sum()),
                              "その他・無回答": int(((m["年代"] == a) & (~m["性別"].isin(["女性", "男性"]))).sum())}
                         for a in age_order}
    out["companion"] = [{"name": k, "n": int(v)} for k, v in m["同行者(やんばるエリア)"].fillna("無回答").value_counts().items()]
    vc_order = ["初めて", "2-3回目", "4-5回目", "6-10回目", "11回目以上"]
    vc = m["訪問回数(やんばるエリア)"].value_counts()
    out["visit_count"] = {k: int(vc.get(k, 0)) for k in vc_order}
    rep4 = int(sum(vc.get(k, 0) for k in ["4-5回目", "6-10回目", "11回目以上"]))
    out["visit_count_summary"] = {"first_pct": round(int(vc.get("初めて", 0)) / N * 100, 1),
                                   "rep4plus_pct": round(rep4 / N * 100, 1),
                                   "rep11_pct": round(int(vc.get("11回目以上", 0)) / N * 100, 1)}

    # 自由記述
    pos = (m["体験・サービス満足度の理由(やんばるエリア)"].fillna("") + " " +
           m["推奨項目(やんばるエリア)"].fillna("")).str.strip()
    neg = m["改善点の内容(やんばるエリア)"].fillna("").astype(str).str.strip()
    kaizen = int((m["改善点(やんばるエリア)"] == "ある").sum())
    out["free_text"] = {
        "pos_n": int(pos.ne("").sum()), "neg_n": int(neg.ne("").sum()),
        "kaizen_ari": kaizen, "kaizen_ari_pct": round(kaizen / N * 100, 1),
        "experience": [{**r, "pct": round(r["n"] / N * 100, 1)} for r in code(pos, EXP_THEMES)],
        "food": [{**r, "pct": round(r["n"] / N * 100, 1)} for r in code(pos, FOOD_THEMES)],
        "issues": [{**r, "pct": round(r["n"] / max(kaizen, 1) * 100, 1)} for r in code(neg, NEG_THEMES)],
    }

    # セグメント
    def segbd(sub, themes, s):
        return [x for x in code(sub[s], themes) if x["n"] > 0][:5]
    m["_pos"] = pos; m["_neg"] = neg
    m["_compg"] = m["同行者(やんばるエリア)"].fillna("").apply(
        lambda v: "パートナー" if "パートナー" in v else "家族" if "家族" in v
        else "ひとり旅" if "ひとり" in v else "友人" if "友人" in v else "その他")
    out["seg_gender"] = {g: {"n": int((m["性別"] == g).sum()),
                              "exp": segbd(m[m["性別"] == g], EXP_THEMES, "_pos"),
                              "food": segbd(m[m["性別"] == g], FOOD_THEMES, "_pos"),
                              "issue": segbd(m[m["性別"] == g], NEG_THEMES, "_neg")} for g in ["女性", "男性"]}
    out["seg_age"] = {a: {"n": int((m["年代"] == a).sum()),
                          "exp": segbd(m[m["年代"] == a], EXP_THEMES, "_pos")[:3],
                          "issue": segbd(m[m["年代"] == a], NEG_THEMES, "_neg")[:3]} for a in age_order}
    out["seg_companion"] = {g: {"n": int((m["_compg"] == g).sum()),
                                "exp": segbd(m[m["_compg"] == g], EXP_THEMES, "_pos")[:3],
                                "issue": segbd(m[m["_compg"] == g], NEG_THEMES, "_neg")[:3]}
                            for g in ["パートナー", "家族", "ひとり旅", "友人"]}

    # 代表ボイス（テーマ別の実記述。クリーンな短文を優先）
    def voices(themes, col, k=8):
        v = {}
        for name, pat in themes:
            hit = m[m[col].str.contains(pat, regex=True, na=False) & m[col].str.strip().ne("")]
            arr = []
            for _, r in hit.iterrows():
                t = r[col].strip().replace("\n", " ")
                if 8 <= len(t) <= 70:
                    arr.append({"text": t, "性別": str(r["性別"]), "年代": r["年代"],
                                "同行者": str(r["同行者(やんばるエリア)"])})
                if len(arr) >= k: break
            v[name] = arr
        return v
    out["voices_exp"] = voices(EXP_THEMES, "_pos")
    out["voices_food"] = voices(FOOD_THEMES, "_pos")
    out["voices_neg"] = voices(NEG_THEMES, "_neg")

    path = os.path.join(args.out, "summary.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"N={N}  満足度={out['satisfaction']['satisfied_pct']}%  再来訪={out['revisit']['intent_pct']}%  NPS={out['nps']['nps']}")
    print("saved:", path)


if __name__ == "__main__":
    main()
