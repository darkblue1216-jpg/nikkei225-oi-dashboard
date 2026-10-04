"""
IV・手口データの取得（2026-10-04追加。docs/261004_phase0_data_survey.md参照）。

data/oi_history/ にある日付それぞれについて、未取得のものだけを埋める（冪等）。
初回実行がそのままバックフィルになり、GitHub Actionsでの毎日実行も同じコードで動く。

  1. data/iv_history/YYYY-MM-DD.csv
       JPX「オプション理論価格等情報」(ose{yyyymmdd}tp.csv)から日経225オプション(ラージ)の
       権利行使価格別IV・理論価格・原資産終値。約2ヶ月分さかのぼれる（建玉データの8/19以降は全部取れる）。
  2. data/participant_volume/YYYY-MM-DD.csv
       「取引参加者別取引高（手口上位一覧）」日次。ラージオプションの銘柄(ストライク×P/C)別の
       参加者ランキング。**取引高のみで売買区分はない。** ナイト/日中を別々に保存。
  3. data/participant_oi_weekly/YYYY-MM-DD.csv
       「取引参加者別建玉残高」週次（前週末時点）。売超/買超の参加者と枚数。
       **期近限月のATM近傍5ストライクしか載らない。**

どのデータも取得に失敗しても他を止めない（欠損は次回実行で埋まる）。
"""
import csv
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
OI_DIR = os.path.join(DATA, "oi_history")
IV_DIR = os.path.join(DATA, "iv_history")
PV_DIR = os.path.join(DATA, "participant_volume")
WK_DIR = os.path.join(DATA, "participant_oi_weekly")
JPX = "https://www.jpx.co.jp"

IV_FIELDS = ["report_date", "contract", "strike", "call_iv", "put_iv", "call_theo", "put_theo",
             "call_close", "put_close", "underlying", "base_vol"]
PV_FIELDS = ["report_date", "session", "contract", "put_call", "strike", "rank",
             "participant_code", "participant_en", "participant_jp", "volume"]
WK_FIELDS = ["asof_date", "contract", "put_call", "strike", "side", "rank",
             "participant_code", "participant_jp", "qty"]


def http_get(url, timeout=60):
    """成功時はbytes、404等はNone。JPXは存在しないファイルにHTML(404)を返す。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if data[:9].lower() == b"<!doctype" or data[:5].lower() == b"<html":
        return None
    return data


def oi_dates():
    return sorted(f[:-4] for f in os.listdir(OI_DIR) if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.csv", f))


def write_csv(path, fields, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def standard_contracts(date_iso):
    """その日のOIファイルにあるラージオプションの限月(YYMM)。"""
    out = set()
    with open(os.path.join(OI_DIR, f"{date_iso}.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["product"] == "standard":
                out.add(r["contract"])
    return out


# ============================================================
# 1. IV（理論価格等情報）
# ============================================================
def fetch_iv(date_iso):
    path = os.path.join(IV_DIR, f"{date_iso}.csv")
    if os.path.exists(path):
        return "skip"
    d = date_iso.replace("-", "")
    raw = http_get(f"{JPX}/automation/markets/derivatives/option-price/files/ose{d}tp.csv")
    if raw is None:
        return "未公開/取得不可"
    want = standard_contracts(date_iso)
    rows = []
    for r in csv.reader(io.StringIO(raw.decode("cp932", errors="replace"))):
        if len(r) < 17 or r[0].strip() != "NK225E":
            continue
        contract = r[2].strip()[2:6]  # 202610 -> 2610
        if contract not in want:
            continue
        rows.append({
            "report_date": d, "contract": contract, "strike": int(float(r[3])),
            "call_iv": float(r[14]), "put_iv": float(r[9]),
            "call_theo": float(r[13]), "put_theo": float(r[8]),
            "call_close": float(r[11]), "put_close": float(r[6]),
            "underlying": float(r[15]), "base_vol": float(r[16]),
        })
    if not rows:
        return "対象限月なし"
    write_csv(path, IV_FIELDS, rows)
    return f"{len(rows)}行"


# ============================================================
# 2. 取引参加者別取引高（手口、日次）
# ============================================================
ISSUE_RE = re.compile(r"NIKKEI 225 OOP ([PC])(\d{4})-(\d+)")


def parse_pv_xlsx(raw, date_iso, session):
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(raw), data_only=True).worksheets[0]
    rows = []
    for r in ws.iter_rows(min_row=9, values_only=True):
        if not r[0] or r[0] != "NK225E":
            continue
        m = ISSUE_RE.match(str(r[2]))
        if not m:
            continue
        rows.append({
            "report_date": date_iso.replace("-", ""), "session": session, "contract": m.group(2),
            "put_call": "Put" if m.group(1) == "P" else "Call", "strike": int(m.group(3)),
            "rank": int(r[3]), "participant_code": str(r[4]), "participant_jp": r[5],
            "participant_en": r[6], "volume": int(r[7]),
        })
    return rows


def fetch_participant_volume(date_iso, month_cache):
    path = os.path.join(PV_DIR, f"{date_iso}.csv")
    if os.path.exists(path):
        return "skip"
    d = date_iso.replace("-", "")
    month = d[:6]
    if month not in month_cache:
        raw = http_get(f"{JPX}/automation/markets/derivatives/participant-volume/json/participant_volume_{month}.json")
        month_cache[month] = {t["TradeDate"]: t for t in json.loads(raw)["TableDatas"]} if raw else {}
    entry = month_cache[month].get(d)
    if not entry:
        return "未公開/取得不可"
    rows = []
    for key, session in (("WholeDay", "day"), ("Night", "night")):
        if key not in entry:
            continue
        raw = http_get(JPX + entry[key])
        if raw:
            rows += parse_pv_xlsx(raw, date_iso, session)
    if not rows:
        return "対象銘柄なし"
    write_csv(path, PV_FIELDS, rows)
    return f"{len(rows)}行"


# ============================================================
# 3. 取引参加者別建玉残高（週次、売超/買超）
# ============================================================
def parse_weekly_xlsx(raw, asof_iso):
    """
    レイアウト: 列0=順位, 列1=プットのストライク, 列2-4=売超(コード,名,枚数), 列5-7=買超,
                列10=順位, 列11=コールのストライク, 列12-14=売超, 列15-17=買超。
    ストライクは順位1の行にだけ入っており、続く順位2〜15の行は同じストライクに属する。
    """
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(raw), data_only=True).worksheets[0]
    rows, contract = [], None
    put_strike = call_strike = None
    for r in ws.iter_rows(values_only=True):
        r = list(r) + [None] * (18 - len(r))
        if isinstance(r[1], str) and "プット" in r[1]:
            m = re.search(r"(\d{4})年(\d{1,2})月限月", r[1])
            contract = f"{m.group(1)[2:]}{int(m.group(2)):02d}" if m else None
            put_strike = call_strike = None
            continue
        if contract is None or not isinstance(r[0], (int, float)):
            continue
        if isinstance(r[1], (int, float)):
            put_strike = int(r[1])
        if isinstance(r[11], (int, float)):
            call_strike = int(r[11])
        rank = int(r[0])
        for pc, strike, blocks in (("Put", put_strike, ((("売超", 2),), (("買超", 5),))),
                                    ("Call", call_strike, ((("売超", 12),), (("買超", 15),)))):
            if strike is None:
                continue
            for ((side, c0),) in blocks:
                if r[c0] is None or r[c0 + 2] is None:
                    continue
                rows.append({
                    "asof_date": asof_iso.replace("-", ""), "contract": contract, "put_call": pc,
                    "strike": strike, "side": side, "rank": rank, "participant_code": str(r[c0]),
                    "participant_jp": r[c0 + 1], "qty": int(r[c0 + 2]),
                })
    return rows


def fetch_weekly(first_date_iso):
    results = []
    years = sorted({first_date_iso[:4], str(__import__("datetime").date.today().year)})
    for year in years:
        raw = http_get(f"{JPX}/automation/markets/derivatives/open-interest/json/open_interest_{year}.json")
        if not raw:
            continue
        for t in json.loads(raw)["TableDatas"]:
            d = t["TradeDate"]
            iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            if iso < first_date_iso:
                continue
            path = os.path.join(WK_DIR, f"{iso}.csv")
            if os.path.exists(path):
                continue
            xl = http_get(JPX + t["IndexOptions"])
            if not xl:
                results.append((iso, "取得不可"))
                continue
            rows = parse_weekly_xlsx(xl, iso)
            if rows:
                write_csv(path, WK_FIELDS, rows)
            results.append((iso, f"{len(rows)}行"))
    return results


def main():
    dates = oi_dates()
    if len(sys.argv) > 1:  # 例: python 261004_fetch_market_data.py 2026-10-01
        dates = [d for d in dates if d >= sys.argv[1]]
    month_cache = {}
    for d in dates:
        for name, fn in (("iv", lambda x: fetch_iv(x)),
                          ("手口", lambda x: fetch_participant_volume(x, month_cache))):
            try:
                res = fn(d)
            except Exception as e:  # 1つの失敗で全体を止めない
                res = f"エラー: {e}"
            if res != "skip":
                print(f"{d} {name}: {res}")
    try:
        for iso, res in fetch_weekly(dates[0]):
            print(f"{iso} 週次参加者別建玉: {res}")
    except Exception as e:
        print(f"週次参加者別建玉: エラー: {e}")


if __name__ == "__main__":
    main()
