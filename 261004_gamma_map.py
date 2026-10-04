"""
ガンママップ（モデルA: 符号なし）。docs/261004_spec.md「Phase 3」参照。

各ストライクについて「日経が100円動いたとき、そのストライクの建玉に対して必要になる
ヘッジ量の目安」を出す。

  ヘッジ量の目安 = ガンマ × 建玉 × 取引単位 × 100円        （仕様書の式そのまま）
  ガンマ         = ブラック・ショールズ（配当なし）。IVはJPX理論価格フィードのボラティリティ
                   （清算値段CSVと470ストライクで差ゼロを確認済み）。
  取引単位       = ラージ1,000倍 / ミニ100倍

**モデルAは符号なし。** 建玉の大きさだけを使うので、ヘッジが「買い」になるか「売り」になるかは
分からない。誰がどちら側のポジションを持っているかは、公開データからは現在値±2,000円の範囲で
特定できない（docs/261004_phase0_data_survey.md参照）。

加速ポイント候補の定義（Phase 4の検証前に固定。結果を見てから変えない）:
  現在値±CANDIDATE_WINDOW_YEN の範囲で、表示対象の限月（期近＋次限月）を合算した
  ヘッジ量の目安が大きい上位 CANDIDATE_TOP_N ストライク。
"""
import math
from datetime import date, datetime, timedelta

import pandas as pd

UNIT_MULTIPLIER = {"standard": 1000, "mini": 100}
MOVE_YEN = 100
RISK_FREE_RATE = 0.0108  # 清算値段CSV(2026-10-02)の金利1.0801%。ガンマへの影響は小さいので固定
MIN_IV = 0.011           # JPXフィードのIV下限プレースホルダー(0.01)は「IVなし」として除外
CANDIDATE_WINDOW_YEN = 2000
CANDIDATE_TOP_N = 5


def second_friday(year, month):
    d = date(year, month, 1)
    first_friday = d + timedelta(days=(4 - d.weekday()) % 7)
    return first_friday + timedelta(days=7)


def contract_sq_date(contract):
    """'2610' -> 2026-10-09（第2金曜。祝日による前倒しは考慮しない）。"""
    return second_friday(2000 + int(contract[:2]), int(contract[2:]))


def days_to_sq(contract, report_date_iso):
    rd = datetime.strptime(report_date_iso, "%Y-%m-%d").date()
    return (contract_sq_date(contract) - rd).days


def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_gamma(s, k, t_years, r, sigma):
    """ブラック・ショールズのガンマ（1円あたりのデルタ変化）。コール・プット共通。"""
    if t_years <= 0 or sigma <= 0 or s <= 0 or k <= 0:
        return 0.0
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * math.sqrt(t_years))
    return _norm_pdf(d1) / (s * sigma * math.sqrt(t_years))


def build_gamma_table(oi_df, iv_df, contracts, report_date_iso, spot, product="standard"):
    """
    oi_df: その日のOIスナップショット(列: product, put_call, contract, strike, oi)
    iv_df: その日のIV(列: contract, strike, call_iv, put_iv)
    戻り値: 行=ストライク×限月、列: contract, strike, call_oi, put_oi, call_gamma, put_gamma,
            call_hedge, put_hedge, hedge(合計=符号なし), futures_large(ラージ先物換算枚数)
    """
    unit = UNIT_MULTIPLIER[product]
    oi = oi_df[oi_df["product"] == product]
    rows = []
    for contract in contracts:
        t = days_to_sq(contract, report_date_iso) / 365.0
        if t <= 0:
            continue
        c_oi = oi[(oi["contract"] == contract) & (oi["put_call"] == "Call")].set_index("strike")["oi"]
        p_oi = oi[(oi["contract"] == contract) & (oi["put_call"] == "Put")].set_index("strike")["oi"]
        iv = iv_df[iv_df["contract"] == contract].set_index("strike")
        for k in sorted(set(c_oi.index) | set(p_oi.index)):
            if k not in iv.index:
                continue
            civ, piv = iv.at[k, "call_iv"], iv.at[k, "put_iv"]
            co, po = float(c_oi.get(k, 0)), float(p_oi.get(k, 0))
            cg = bs_gamma(spot, k, t, RISK_FREE_RATE, civ) if civ >= MIN_IV and co > 0 else 0.0
            pg = bs_gamma(spot, k, t, RISK_FREE_RATE, piv) if piv >= MIN_IV and po > 0 else 0.0
            if cg == 0 and pg == 0:
                continue
            ch, ph = cg * co * unit * MOVE_YEN, pg * po * unit * MOVE_YEN
            rows.append({
                "contract": contract, "strike": int(k), "call_oi": co, "put_oi": po,
                "call_iv": civ, "put_iv": piv, "call_gamma": cg, "put_gamma": pg,
                "call_hedge": ch, "put_hedge": ph, "hedge": ch + ph,
                # 先物ラージ(1,000倍)に換算した枚数 = ヘッジ量 / 1,000
                "futures_large": (ch + ph) / 1000.0,
            })
    return pd.DataFrame(rows)


def by_strike(table):
    """限月を合算した、ストライク別のヘッジ量（符号なし）。"""
    if table.empty:
        return table
    g = table.groupby("strike")[["call_oi", "put_oi", "call_hedge", "put_hedge", "hedge", "futures_large"]].sum()
    return g.reset_index().sort_values("strike")


def acceleration_candidates(strike_table, spot, window=CANDIDATE_WINDOW_YEN, top_n=CANDIDATE_TOP_N):
    """現在値±windowの範囲でヘッジ量が大きい上位top_nストライク（仕様書の「加速ポイント候補」）。"""
    if strike_table.empty:
        return strike_table
    d = strike_table[(strike_table["strike"] >= spot - window) & (strike_table["strike"] <= spot + window)]
    out = d.sort_values("hedge", ascending=False).head(top_n).copy()
    out["distance"] = out["strike"] - spot
    out["rank"] = range(1, len(out) + 1)
    return out
