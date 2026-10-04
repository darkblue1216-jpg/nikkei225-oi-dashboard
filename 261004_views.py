"""
Phase 1・2・3のチャート/テーブル生成（plotly/pandasのみ。Streamlitには依存しない）。
配色・レイアウトは既存のダークテーマ(app.pyのCOLORS)に合わせる。
"""
import importlib
import os

import pandas as pd
import plotly.graph_objects as go

gm = importlib.import_module("261004_gamma_map")  # ファイル名が数字始まりのためimportlibで読む
pt = importlib.import_module("261004_participants")

BASE = os.path.dirname(os.path.abspath(__file__))
IV_DIR = os.path.join(BASE, "data", "iv_history")

C = {
    "call": "#3fb950", "put": "#f85149", "position": "#58a6ff", "bg": "#0d1117", "panel": "#161b22",
    "text": "#e6edf3", "grid": "#21262d", "up": "#3fb950", "down": "#f85149", "spot": "#e6edf3",
    "cand": "#f0883e", "dealer": "#a371f7",
}


def _layout(fig, title, height=380, xtitle=None, ytitle=None, legend=False):
    fig.update_layout(
        title=dict(text=title, font=dict(size=14, color=C["text"])), height=height,
        paper_bgcolor=C["bg"], plot_bgcolor=C["panel"], font=dict(color=C["text"]),
        xaxis=dict(gridcolor=C["grid"], title=xtitle), yaxis=dict(gridcolor=C["grid"], title=ytitle),
        showlegend=legend, margin=dict(l=60, r=20, t=60, b=40),
    )
    if legend:
        fig.update_layout(legend=dict(orientation="h", y=1.1))
    return fig


def _empty(msg="データなし"):
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
    return _layout(fig, "", height=260)


# ------------------------------------------------------------------
# データ
# ------------------------------------------------------------------
def load_iv(date_iso):
    path = os.path.join(IV_DIR, f"{date_iso}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"contract": str})


def underlying_close(date_iso):
    iv = load_iv(date_iso)
    return float(iv["underlying"].iloc[0]) if not iv.empty else None


def near_contracts(snapshot, date_iso, n=2):
    """期近と次限月（ラージ、SQ前のもの）。"""
    cs = sorted(snapshot[snapshot["product"] == "standard"]["contract"].unique())
    cs = [c for c in cs if gm.days_to_sq(c, date_iso) >= 0]
    return cs[:n]


def label(contract, date_iso=None):
    s = f"20{contract[:2]}年{contract[2:]}月限"
    if date_iso:
        s += f"（SQまで{gm.days_to_sq(contract, date_iso)}日）"
    return s


# ------------------------------------------------------------------
# Phase 1: 建玉の増減
# ------------------------------------------------------------------
def oi_bars(df, contract, spot, xrange):
    d = df[(df["product"] == "standard") & (df["contract"] == contract)]
    fig = go.Figure()
    for pc, color, name in (("Put", C["put"], "プット建玉"), ("Call", C["call"], "コール建玉")):
        s = d[d["put_call"] == pc].sort_values("strike")
        fig.add_trace(go.Bar(x=s["strike"], y=s["oi"], name=name, marker_color=color, opacity=0.85))
    fig.add_vline(x=spot, line_color=C["spot"], line_dash="dash", annotation_text=f"現在値 {spot:,.0f}",
                  annotation_font_color=C["spot"], annotation_position="top")
    fig.update_layout(barmode="overlay")
    fig = _layout(fig, f"権利行使価格別 建玉残高（{label(contract)}）", 420, "権利行使価格（円）", "建玉残高（枚）", True)
    fig.update_xaxes(range=list(xrange))
    return fig


def oi_change_bars(df, contract, spot, xrange):
    """前日比の増減。増えたストライクは緑、減ったストライクは赤。コール/プットを左右に並べる。"""
    from plotly.subplots import make_subplots
    d = df[(df["product"] == "standard") & (df["contract"] == contract)]
    fig = make_subplots(rows=1, cols=2, subplot_titles=("コール 前日比", "プット 前日比"), shared_yaxes=True)
    for i, pc in enumerate(("Call", "Put"), start=1):
        s = d[(d["put_call"] == pc) & (d["strike"] >= xrange[0]) & (d["strike"] <= xrange[1])
              & (d["oi_change"] != 0)].sort_values("strike")
        colors = [C["up"] if v > 0 else C["down"] for v in s["oi_change"]]
        fig.add_trace(go.Bar(y=s["strike"], x=s["oi_change"], orientation="h", marker_color=colors,
                              hovertemplate="%{y:,}円<br>前日比 %{x:+,}枚<extra></extra>", showlegend=False),
                      row=1, col=i)
        fig.add_hline(y=spot, line_color=C["spot"], line_dash="dash", row=1, col=i)
    fig = _layout(fig, f"前日比 建玉増減（緑=増加 / 赤=減少、{label(contract)}）", 520)
    fig.update_yaxes(range=list(xrange), tickformat=",", nticks=14)
    fig.update_xaxes(gridcolor=C["grid"])
    return fig


def oi_heatmap(snapshots, contract, pc, spot, xrange):
    """直近の営業日ごとのストライク別建玉（ヒートマップ）。snapshots: {date_iso: df}"""
    cols = {}
    for date_iso, df in snapshots.items():
        d = df[(df["product"] == "standard") & (df["contract"] == contract) & (df["put_call"] == pc)]
        cols[date_iso] = d.set_index("strike")["oi"]
    if not cols:
        return _empty()
    m = pd.DataFrame(cols).fillna(0)
    m = m[(m.index >= xrange[0]) & (m.index <= xrange[1])]
    m = m[(m.sum(axis=1) > 0)].sort_index()
    if m.empty:
        return _empty("表示範囲に建玉なし")
    fig = go.Figure(go.Heatmap(
        z=m.values, x=list(m.columns), y=[str(int(k)) for k in m.index],
        colorscale=[[0, C["panel"]], [1, C["call"] if pc == "Call" else C["put"]]],
        hovertemplate="%{y}円 %{x}<br>%{z:,.0f}枚<extra></extra>", colorbar=dict(title="枚")))
    fig = _layout(fig, f"{'コール' if pc == 'Call' else 'プット'}建玉 直近{m.shape[1]}営業日の推移（{label(contract)}）", 520)
    fig.update_yaxes(type="category", autorange=True)
    fig.update_xaxes(type="category")  # 営業日のみ（土日の空白を入れない）
    return fig


def top5_table(df, contract, pc):
    d = df[(df["product"] == "standard") & (df["contract"] == contract) & (df["put_call"] == pc)]
    t = d.sort_values("oi", ascending=False).head(5)[["strike", "oi", "oi_change", "volume"]]
    t.columns = ["権利行使価格", "建玉(枚)", "前日比", "取引高"]
    t.insert(0, "順位", range(1, len(t) + 1))
    return t


# ------------------------------------------------------------------
# Phase 3: ガンママップ（モデルA）
# ------------------------------------------------------------------
def gamma_map_chart(strike_table, spot, candidates, xrange):
    t = strike_table[(strike_table["strike"] >= xrange[0]) & (strike_table["strike"] <= xrange[1])]
    if t.empty:
        return _empty()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=t["strike"], y=t["call_hedge"] / 1000, name="コール分", marker_color=C["call"], opacity=0.85))
    fig.add_trace(go.Bar(x=t["strike"], y=t["put_hedge"] / 1000, name="プット分", marker_color=C["put"], opacity=0.85))
    fig.update_layout(barmode="stack")
    fig.add_vrect(x0=spot - gm.CANDIDATE_WINDOW_YEN, x1=spot + gm.CANDIDATE_WINDOW_YEN,
                  fillcolor=C["cand"], opacity=0.07, line_width=0)
    fig.add_vline(x=spot, line_color=C["spot"], line_dash="dash", annotation_text=f"現在値 {spot:,.0f}",
                  annotation_font_color=C["spot"], annotation_position="top")
    for _, r in candidates.iterrows():
        fig.add_annotation(x=r["strike"], y=r["hedge"] / 1000, text=f"候補{int(r['rank'])}", showarrow=True,
                           arrowhead=2, arrowcolor=C["cand"], font=dict(color=C["cand"], size=11), ay=-28)
    return _layout(fig, "ガンママップ モデルA（符号なし）: 日経100円の動きで必要になるヘッジ量の目安",
                   460, "権利行使価格（円）", "ヘッジ量の目安（先物ラージ換算 枚）", True)


def candidates_table(candidates):
    if candidates.empty:
        return candidates
    t = candidates[["rank", "strike", "distance", "call_oi", "put_oi", "hedge", "futures_large"]].copy()
    t["hedge"] = t["hedge"].round(0)
    t["futures_large"] = t["futures_large"].round(1)
    t.columns = ["順位", "権利行使価格", "現在値との差(円)", "コール建玉", "プット建玉",
                 "ヘッジ量の目安(1000倍×100円)", "先物ラージ換算(枚)"]
    return t


# ------------------------------------------------------------------
# Phase 2: 手口（限定版）
# ------------------------------------------------------------------
def volume_by_group_chart(vol_df, contracts, spot, xrange, session="day"):
    """ストライク別の参加者グループ別取引高。向きは不明（売買区分がない）。"""
    d = vol_df[(vol_df["session"] == session) & (vol_df["contract"].isin(contracts))
               & (vol_df["strike"] >= xrange[0]) & (vol_df["strike"] <= xrange[1])]
    if d.empty:
        return _empty("この範囲に手口の掲載銘柄なし")
    g = d.groupby(["strike", "group"])["volume"].sum().unstack(fill_value=0)
    colors = {"業者側": C["dealer"], "清算業者": "#8b949e", "その他": C["position"]}
    fig = go.Figure()
    for grp in ("業者側", "清算業者", "その他"):
        if grp in g.columns:
            fig.add_trace(go.Bar(x=g.index, y=g[grp], name=grp, marker_color=colors[grp]))
    fig.update_layout(barmode="stack")
    fig.add_vline(x=spot, line_color=C["spot"], line_dash="dash")
    return _layout(fig, f"手口 ストライク別の取引高（{'日中立会' if session == 'day' else 'ナイト'}、"
                        "参加者グループ別・売買の向きは不明）", 400, "権利行使価格（円）", "取引高（枚）", True)


def volume_ranking_table(vol_df, contracts, session="day", top=15):
    d = vol_df[(vol_df["session"] == session) & (vol_df["contract"].isin(contracts))]
    if d.empty:
        return pd.DataFrame()
    d = d.copy()
    d["銘柄"] = d["contract"] + " " + d["put_call"].map({"Call": "C", "Put": "P"}) + d["strike"].astype(str)
    t = d.groupby("銘柄").apply(lambda g: pd.Series({
        "取引高(掲載分合計)": g["volume"].sum(),
        "1位": f"{g.sort_values('rank').iloc[0]['participant_jp']}（{g.sort_values('rank').iloc[0]['volume']}枚）",
        "業者側の取引高": g.loc[g["group"] == "業者側", "volume"].sum(),
        "業者側の比率%": round(100 * g.loc[g["group"] == "業者側", "volume"].sum() / max(g["volume"].sum(), 1), 1),
    })).reset_index()
    return t.sort_values("取引高(掲載分合計)", ascending=False).head(top)


def weekly_net_table(weekly_df, asof):
    """週次の売超/買超（ATM近傍5ストライクのみ）。業者側の売超を強調できるよう群を付ける。"""
    d = weekly_df[weekly_df["asof_date"] == asof]
    if d.empty:
        return pd.DataFrame()
    t = d.sort_values(["contract", "put_call", "strike", "side", "rank"])[
        ["contract", "put_call", "strike", "side", "rank", "participant_jp", "group", "qty"]]
    t.columns = ["限月", "P/C", "権利行使価格", "売超/買超", "順位", "参加者", "区分", "枚数"]
    return t
