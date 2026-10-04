"""
日経225オプション 建玉残高ダッシュボード
データ: JPX「デリバティブ建玉残高表」(https://www.jpx.co.jp/markets/derivatives/trading-volume/)
"""
import glob
import importlib
import os
import re
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# 2026-10-04追加分（ファイル名が日付プレフィックス付きのためimportlibで読み込む）
views = importlib.import_module("261004_views")
importlib.import_module("261004_chart_style").install()  # 全グラフの凡例を白文字・透明背景にする共通設定

st.set_page_config(
    page_title="日経225オプション 建玉残高ダッシュボード",
    page_icon="📊",
    layout="wide",
)

# ============================================================
# スタイル（nikkei-liquidity-dashboardと同系統のダークテーマ）
# ============================================================
COLORS = {
    "call": "#3fb950",
    "put": "#f85149",
    "position": "#58a6ff",
    "bg": "#0d1117",
    "panel": "#161b22",
    "text": "#e6edf3",
    "grid": "#21262d",
    "up": "#3fb950",
    "down": "#f85149",
    # C-P差分チャート専用配色（参考画像に合わせる: コール優位=青、プット優位=オレンジ）
    "cp_call_dominant": "#3b82f6",
    "cp_put_dominant": "#f97316",
    "current_price": "#e6edf3",
}

RANGE_WIDTH_OPTIONS = [5000, 10000, 15000, 20000]

BASE = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE, "data")
HISTORY_DIR = os.path.join(DATA_DIR, "oi_history")


# ============================================================
# データ読み込み
# ============================================================
@st.cache_data(ttl=1800)
def list_available_dates():
    files = glob.glob(os.path.join(HISTORY_DIR, "*.csv"))
    dates = sorted(
        m.group(1) for m in (re.search(r"(\d{4}-\d{2}-\d{2})\.csv$", f) for f in files) if m
    )
    return dates


@st.cache_data(ttl=1800)
def load_snapshot(date_str):
    path = os.path.join(HISTORY_DIR, f"{date_str}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, dtype={"contract": str})
    for col in ("strike", "volume", "oi", "oi_change", "oi_prev"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


@st.cache_data(ttl=1800)
def load_history(dates):
    frames = []
    for d in dates:
        df = load_snapshot(d)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fmt_contract_label(product, contract):
    """
    標準オプションのcontractは"YYMM"（限月そのもの）。
    ミニオプションのcontractは"YYMMDD"だが、これはSQ日ではなく「取引最終日」を表す
    JPXの内部コード（金曜限月なら前営業日=木曜、水曜限月なら前営業日=火曜が最終取引日
    になる規則に対応）。SQ日は基本的に最終取引日の翌暦日だが、祝日を挟む場合はズレる
    可能性があるため、ここでは参考表示として（推定）と明記する。
    """
    if product == "standard":
        yy, mm = contract[:2], contract[2:]
        return f"20{yy}年{int(mm):02d}月限"
    yy, mm, dd = contract[:2], contract[2:4], contract[4:]
    try:
        import datetime as _dt
        last_trade_day = _dt.date(2000 + int(yy), int(mm), int(dd))
        est_sq = last_trade_day + _dt.timedelta(days=1)
        return f"最終取引日20{yy}-{mm}-{dd}（週次、推定SQ日{est_sq.month}/{est_sq.day}）"
    except ValueError:
        return f"最終取引日20{yy}-{mm}-{dd}（週次）"


# ============================================================
# チャート
# ============================================================
def oi_bar_chart(df, product, contract, position_strikes=None, price_range=None):
    d = df[(df["product"] == product) & (df["contract"] == contract)].copy()
    if d.empty:
        fig = go.Figure()
        fig.add_annotation(text="データなし", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig

    puts = d[d["put_call"] == "Put"].sort_values("strike")
    calls = d[d["put_call"] == "Call"].sort_values("strike")

    fig = go.Figure()
    fig.add_trace(go.Bar(x=puts["strike"], y=puts["oi"], name="プット建玉残高",
                          marker_color=COLORS["put"], opacity=0.85))
    fig.add_trace(go.Bar(x=calls["strike"], y=calls["oi"], name="コール建玉残高",
                          marker_color=COLORS["call"], opacity=0.85))

    if position_strikes:
        for label, strike in position_strikes:
            if strike:
                fig.add_vline(x=strike, line_color=COLORS["position"], line_width=2, line_dash="dash",
                              annotation_text=label, annotation_font_color=COLORS["position"],
                              annotation_position="top left")

    xaxis_opts = dict(gridcolor=COLORS["grid"])
    if price_range:
        xaxis_opts["range"] = list(price_range)

    fig.update_layout(
        barmode="overlay",
        title=dict(text=f"権利行使価格別 建玉残高（{fmt_contract_label(product, contract)}）",
                    font=dict(size=14, color=COLORS["text"])),
        xaxis_title="権利行使価格（円）",
        yaxis_title="建玉残高（枚）",
        height=480,
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["panel"],
        font=dict(color=COLORS["text"]),
        legend=dict(orientation="h", x=1, xanchor="right", y=1.08),  # 右寄せ: ポジション線のラベルと重ならないように
        xaxis=xaxis_opts,
        yaxis=dict(gridcolor=COLORS["grid"]),
        margin=dict(l=50, r=20, t=70, b=40),
    )
    return fig


def oi_change_bar_chart(df, product, contract, top_n=20):
    d = df[(df["product"] == product) & (df["contract"] == contract)].copy()
    if d.empty:
        fig = go.Figure()
        fig.add_annotation(text="データなし", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig
    d = d.reindex(d["oi_change"].abs().sort_values(ascending=False).index).head(top_n)
    d = d.sort_values("strike")
    d["label"] = d["put_call"].str[0] + d["strike"].astype(int).astype(str)
    colors = [COLORS["up"] if v >= 0 else COLORS["down"] for v in d["oi_change"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=d["label"], y=d["oi_change"], marker_color=colors))
    fig.update_layout(
        title=dict(text="前日比 建玉残高増減（上位・絶対値順）", font=dict(size=13, color=COLORS["text"])),
        xaxis_title="銘柄（P/C+権利行使価格）", yaxis_title="前日比（枚）",
        height=360, paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["panel"],
        font=dict(color=COLORS["text"]), showlegend=False,
        xaxis=dict(gridcolor=COLORS["grid"]), yaxis=dict(gridcolor=COLORS["grid"]),
        margin=dict(l=50, r=20, t=50, b=60),
    )
    return fig


def cp_diff_series(df, product, contract):
    """権利行使価格ごとの C-P（コール建玉残高 - プット建玉残高）を計算する。"""
    d = df[(df["product"] == product) & (df["contract"] == contract)]
    if d.empty:
        return pd.DataFrame(columns=["strike", "call_oi", "put_oi", "cp"])
    g = d.groupby(["strike", "put_call"])["oi"].sum().unstack(fill_value=0)
    for col in ("Call", "Put"):
        if col not in g.columns:
            g[col] = 0
    g = g.rename(columns={"Call": "call_oi", "Put": "put_oi"}).reset_index()
    g["cp"] = g["call_oi"] - g["put_oi"]
    return g.sort_values("strike")


def cp_diff_bar_chart(df, product, contract, current_price=None, range_width=None, position_strikes=None):
    """
    C-P差分（コール建玉残高-プット建玉残高）の横向きバーチャート。
    ストライクを縦軸（降順=上が高い価格）、C-Pを横軸に取り、現在値近辺のC-Pバランスを一目で見せる。
    """
    g = cp_diff_series(df, product, contract)
    if g.empty:
        fig = go.Figure()
        fig.add_annotation(text="データなし", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig

    if current_price is not None and range_width is not None:
        g = g[(g["strike"] >= current_price - range_width) & (g["strike"] <= current_price + range_width)]
    if g.empty:
        fig = go.Figure()
        fig.add_annotation(text="表示レンジ内にデータがありません（レンジを広げてください）",
                            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig

    g = g.sort_values("strike")  # 数値y軸なので昇順で渡せば上に高い価格が来る
    colors = [COLORS["cp_call_dominant"] if v >= 0 else COLORS["cp_put_dominant"] for v in g["cp"]]
    customdata = g[["call_oi", "put_oi"]].to_numpy()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=g["cp"], y=g["strike"], orientation="h",
        marker_color=colors, customdata=customdata,
        hovertemplate=(
            "権利行使価格: %{y:,}円<br>"
            "コール残: %{customdata[0]:,.0f}枚<br>"
            "プット残: %{customdata[1]:,.0f}枚<br>"
            "C-P: %{x:,.0f}枚<extra></extra>"
        ),
    ))
    fig.add_vline(x=0, line_color=COLORS["grid"], line_width=1)

    if current_price is not None:
        fig.add_hline(y=current_price, line_color=COLORS["current_price"], line_width=1.5, line_dash="dash",
                      annotation_text=f"現在値 {current_price:,.2f}", annotation_font_color=COLORS["current_price"],
                      annotation_position="top right")

    if position_strikes:
        for label, strike in position_strikes:
            if strike:
                fig.add_hline(y=strike, line_color=COLORS["position"], line_width=1, line_dash="dot",
                              annotation_text=label, annotation_font_color=COLORS["position"],
                              annotation_position="bottom right")

    fig.update_layout(
        title=dict(text=f"C-P差分（コール残-プット残） {fmt_contract_label(product, contract)}",
                    font=dict(size=14, color=COLORS["text"])),
        xaxis_title="C-P（枚）　※青=コール優位／オレンジ=プット優位",
        yaxis_title="権利行使価格（円）",
        height=560,
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["panel"],
        font=dict(color=COLORS["text"]),
        showlegend=False,
        xaxis=dict(gridcolor=COLORS["grid"]),
        yaxis=dict(gridcolor=COLORS["grid"], tickformat=",", nticks=20),
        margin=dict(l=70, r=20, t=70, b=40),
    )
    return fig


def multi_day_trend_chart(history_df, product, contract, strikes):
    if history_df.empty or not strikes:
        fig = go.Figure()
        fig.add_annotation(text="データ蓄積待ち（複数日分たまると表示されます）",
                            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig
    d = history_df[(history_df["product"] == product) & (history_df["contract"] == contract)]
    d = d[d["strike"].isin(strikes)]
    if d.empty:
        fig = go.Figure()
        fig.add_annotation(text="対象ストライクのデータなし", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig

    fig = go.Figure()
    for (strike, pc), grp in d.groupby(["strike", "put_call"]):
        grp = grp.sort_values("report_date")
        color = COLORS["call"] if pc == "Call" else COLORS["put"]
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(grp["report_date"], format="%Y%m%d"), y=grp["oi"],
            mode="lines+markers", name=f"{pc[0]}{int(strike)}",
            line=dict(color=color, width=1.8),
        ))
    fig.update_layout(
        title=dict(text="選択ストライクの建玉残高推移（日次）", font=dict(size=13, color=COLORS["text"])),
        yaxis_title="建玉残高（枚）",
        height=360, paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["panel"],
        font=dict(color=COLORS["text"]),
        xaxis=dict(gridcolor=COLORS["grid"]), yaxis=dict(gridcolor=COLORS["grid"]),
        margin=dict(l=50, r=20, t=50, b=40),
    )
    return fig


def put_call_ratio_series(history_df, product, contract):
    """日ごとのプット建玉合計/コール建玉合計を計算する。"""
    if history_df.empty:
        return pd.DataFrame(columns=["report_date", "put_oi", "call_oi", "ratio"])
    d = history_df[(history_df["product"] == product) & (history_df["contract"] == contract)]
    if d.empty:
        return pd.DataFrame(columns=["report_date", "put_oi", "call_oi", "ratio"])
    g = d.groupby(["report_date", "put_call"])["oi"].sum().unstack(fill_value=0)
    for col in ("Put", "Call"):
        if col not in g.columns:
            g[col] = 0
    g = g.rename(columns={"Put": "put_oi", "Call": "call_oi"}).reset_index()
    g["ratio"] = g["put_oi"] / g["call_oi"].replace(0, pd.NA)
    return g.sort_values("report_date")


def put_call_ratio_trend_chart(history_df, product, contract):
    g = put_call_ratio_series(history_df, product, contract)
    if g.empty or len(g) < 2:
        fig = go.Figure()
        fig.add_annotation(text="データ蓄積待ち（複数日分たまると表示されます）",
                            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=pd.to_datetime(g["report_date"], format="%Y%m%d"), y=g["ratio"],
        mode="lines+markers", name="Put/Call比",
        line=dict(color=COLORS["position"], width=2),
    ))
    fig.add_hline(y=1.0, line_color=COLORS["grid"], line_dash="dash")
    fig.update_layout(
        title=dict(text="Put/Call比（建玉残高ベース）の推移", font=dict(size=13, color=COLORS["text"])),
        yaxis_title="Put OI ÷ Call OI",
        height=360, paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["panel"],
        font=dict(color=COLORS["text"]), showlegend=False,
        xaxis=dict(gridcolor=COLORS["grid"]), yaxis=dict(gridcolor=COLORS["grid"]),
        margin=dict(l=50, r=20, t=50, b=40),
    )
    return fig


def compute_max_pain(df, product, contract):
    """
    マックスペイン価格: 満期時にその権利行使価格で決済されたと仮定した場合に、
    オプション買い手側が受け取る本質的価値の合計（＝売り手側の支払い総額）が
    最小になる権利行使価格。候補は当日実際に建玉のある権利行使価格のみとする。
    戻り値: (max_pain_strike, DataFrame[strike, total_payout])
    """
    d = df[(df["product"] == product) & (df["contract"] == contract)]
    if d.empty:
        return None, pd.DataFrame(columns=["strike", "total_payout"])
    puts = d[d["put_call"] == "Put"][["strike", "oi"]].groupby("strike")["oi"].sum()
    calls = d[d["put_call"] == "Call"][["strike", "oi"]].groupby("strike")["oi"].sum()
    strikes = sorted(set(puts.index) | set(calls.index))
    if not strikes:
        return None, pd.DataFrame(columns=["strike", "total_payout"])

    payouts = []
    for k in strikes:
        call_payout = sum((k - s) * oi for s, oi in calls.items() if s < k)
        put_payout = sum((s - k) * oi for s, oi in puts.items() if s > k)
        payouts.append(call_payout + put_payout)
    loss_df = pd.DataFrame({"strike": strikes, "total_payout": payouts})
    max_pain_strike = int(loss_df.loc[loss_df["total_payout"].idxmin(), "strike"])
    return max_pain_strike, loss_df


def max_pain_chart(loss_df, max_pain_strike, position_strikes=None):
    if loss_df.empty:
        fig = go.Figure()
        fig.add_annotation(text="データなし", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=loss_df["strike"], y=loss_df["total_payout"], mode="lines",
        line=dict(color=COLORS["position"], width=2), name="オプション買い手への支払総額(枚×円)",
    ))
    fig.add_vline(x=max_pain_strike, line_color=COLORS["down"], line_width=2,
                  annotation_text=f"マックスペイン {max_pain_strike:,}円",
                  annotation_font_color=COLORS["down"], annotation_position="top")
    if position_strikes:
        for label, strike in position_strikes:
            if strike:
                fig.add_vline(x=strike, line_color=COLORS["position"], line_width=1, line_dash="dash",
                              annotation_text=label, annotation_font_color=COLORS["position"],
                              annotation_position="bottom")
    fig.update_layout(
        title=dict(text="満期決済価格ごとの買い手側支払総額（最小点＝マックスペイン）",
                    font=dict(size=13, color=COLORS["text"])),
        xaxis_title="満期決済価格（円）", yaxis_title="支払総額（建玉枚数×本質的価値）",
        height=360, paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["panel"],
        font=dict(color=COLORS["text"]), showlegend=False,
        xaxis=dict(gridcolor=COLORS["grid"]), yaxis=dict(gridcolor=COLORS["grid"]),
        margin=dict(l=50, r=20, t=50, b=40),
    )
    return fig


@st.cache_data(ttl=1800)
def max_pain_trend_series(history_df, product, contract):
    """日ごとのマックスペイン価格を計算する（複数日分たまるほど推移が見える）。"""
    if history_df.empty:
        return pd.DataFrame(columns=["report_date", "max_pain"])
    rows = []
    for rd, grp in history_df[(history_df["product"] == product) & (history_df["contract"] == contract)].groupby("report_date"):
        mp, _ = compute_max_pain(grp, product, contract)
        if mp is not None:
            rows.append({"report_date": rd, "max_pain": mp})
    return pd.DataFrame(rows).sort_values("report_date")


def max_pain_trend_chart(history_df, product, contract):
    g = max_pain_trend_series(history_df, product, contract)
    if g.empty or len(g) < 2:
        fig = go.Figure()
        fig.add_annotation(text="データ蓄積待ち（複数日分たまると表示されます）",
                            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=pd.to_datetime(g["report_date"], format="%Y%m%d"), y=g["max_pain"],
        mode="lines+markers", name="マックスペイン価格",
        line=dict(color=COLORS["down"], width=2),
    ))
    fig.update_layout(
        title=dict(text="マックスペイン価格の推移", font=dict(size=13, color=COLORS["text"])),
        yaxis_title="権利行使価格（円）",
        height=300, paper_bgcolor=COLORS["bg"], plot_bgcolor=COLORS["panel"],
        font=dict(color=COLORS["text"]), showlegend=False,
        xaxis=dict(gridcolor=COLORS["grid"]), yaxis=dict(gridcolor=COLORS["grid"]),
        margin=dict(l=50, r=20, t=50, b=40),
    )
    return fig


# ============================================================
# メイン UI
# ============================================================
# ============================================================
# 2026-10-04追加: 建玉の増減 / ガンママップ / 手口（ラージオプション）
# ============================================================
VIEW_WIDTH_OPTIONS = [2000, 3000, 5000, 10000]


def _view_width(key):
    return st.selectbox("表示幅（現在値±）", options=VIEW_WIDTH_OPTIONS, index=2, key=key,
                        format_func=lambda w: f"±{w:,}円")


def render_oi_change_tab(df_snap, dates, selected_date, spot):
    """Phase 1: 期近・次限月のストライク別建玉、前日比、直近5営業日の推移、上位5ストライク。"""
    contracts = views.near_contracts(df_snap, selected_date)
    if not contracts or spot <= 0:
        st.warning("期近・次限月の建玉データ、または現在値が取得できません。")
        return
    width = _view_width("w_oi")
    xr = (spot - width, spot + width)
    recent = [d for d in dates if d <= selected_date][-5:]
    snaps = {d: load_snapshot(d) for d in recent}
    st.caption(f"ラージオプション（通常）。現在値 {spot:,.0f} 円、基準日 {selected_date}。"
               f"ヒートマップは直近{len(recent)}営業日（{recent[0]}〜{recent[-1]}）。")
    for contract in contracts:
        st.subheader(views.label(contract, selected_date))
        st.plotly_chart(views.oi_bars(df_snap, contract, spot, xr), use_container_width=True, key=f"p1_bar_{contract}")
        st.plotly_chart(views.oi_change_bars(df_snap, contract, spot, xr), use_container_width=True,
                        key=f"p1_chg_{contract}")
        h1, h2 = st.columns(2)
        h1.plotly_chart(views.oi_heatmap(snaps, contract, "Call", spot, xr), use_container_width=True,
                        key=f"p1_hc_{contract}")
        h2.plotly_chart(views.oi_heatmap(snaps, contract, "Put", spot, xr), use_container_width=True,
                        key=f"p1_hp_{contract}")
        t1, t2 = st.columns(2)
        t1.markdown("**コール建玉 上位5ストライク**")
        t1.dataframe(views.top5_table(df_snap, contract, "Call"), hide_index=True, use_container_width=True)
        t2.markdown("**プット建玉 上位5ストライク**")
        t2.dataframe(views.top5_table(df_snap, contract, "Put"), hide_index=True, use_container_width=True)
        st.markdown("---")


def render_gamma_tab(df_snap, selected_date, spot):
    """Phase 3 モデルA: 符号なしのガンママップと加速ポイント候補。モデルBは作らない。"""
    st.warning(
        "**ヘッジの向き（買いになるか売りになるか）は分かりません。** このマップは建玉の大きさだけを使った"
        "「どこにヘッジが集中しやすいか」の地図（モデルA・符号なし）です。誰がどちら側のポジションを持っているかは、"
        "公開データから現在値±2,000円の範囲では特定できないため、符号付きのモデルBは作っていません。"
    )
    contracts = views.near_contracts(df_snap, selected_date)
    iv = views.load_iv(selected_date)
    if not contracts or spot <= 0:
        st.warning("期近・次限月の建玉データ、または現在値が取得できません。")
        return
    if iv.empty:
        st.warning(f"{selected_date} のIVデータがありません（data/iv_history/）。")
        return
    table = views.gm.build_gamma_table(df_snap, iv, contracts, selected_date, spot)
    strike_table = views.gm.by_strike(table)
    cands = views.gm.acceleration_candidates(strike_table, spot)
    width = _view_width("w_gamma")
    xr = (spot - width, spot + width)

    st.plotly_chart(views.gamma_map_chart(strike_table, spot, cands, xr), use_container_width=True, key="gamma_map")
    st.subheader(f"加速ポイント候補（現在値 {spot:,.0f} 円の±{views.gm.CANDIDATE_WINDOW_YEN:,}円、上位{views.gm.CANDIDATE_TOP_N}）")
    st.dataframe(views.candidates_table(cands), hide_index=True, use_container_width=True)
    st.caption(
        f"対象限月: {' / '.join(views.label(c, selected_date) for c in contracts)}（合算）。"
        "ヘッジ量の目安 ＝ ガンマ × 建玉 × 取引単位（ラージ1,000倍）× 100円。"
        "ガンマはブラック・ショールズ（配当なし、金利1.08%）、IVはJPX理論価格フィードのボラティリティ"
        "（コール・プットそれぞれのIV）。SQ日は各月の第2金曜として計算（祝日による前倒しは未考慮）。"
        "ミニオプションはIVフィードに無いため対象外。"
    )
    with st.expander("限月別の内訳"):
        t = table[["contract", "strike", "call_oi", "put_oi", "call_iv", "put_iv", "hedge", "futures_large"]].copy()
        t = t[(t["strike"] >= xr[0]) & (t["strike"] <= xr[1])].sort_values(["contract", "strike"])
        st.dataframe(t, hide_index=True, use_container_width=True)


def render_participant_tab(df_snap, selected_date, spot):
    """Phase 2（限定版）: 日次の手口（取引高のみ）と、週次の売超/買超（ATM近傍5ストライクのみ）。"""
    st.warning(
        "**日次の手口は取引高だけで、売り買いの向きは公開されていません（向きは不明）。** "
        "「業者側」に分類した参加者の取引高が多いストライクを示すだけで、業者が売り越しかどうかは分かりません。"
        "売超/買超が分かるのは週次の参加者別建玉残高だけですが、期近限月のATM近傍5ストライクしか載りません。"
    )
    contracts = views.near_contracts(df_snap, selected_date)
    vol = views.pt.load_volume(selected_date)
    width = _view_width("w_part")
    xr = (spot - width, spot + width) if spot > 0 else (0, 200000)

    st.subheader("日次: 取引高上位の参加者（取引高のみ・向き不明）")
    if vol.empty:
        st.info(f"{selected_date} の手口データがありません。")
    else:
        session = st.radio("セッション", ["day", "night"], horizontal=True,
                           format_func=lambda s: "日中立会" if s == "day" else "ナイト")
        st.plotly_chart(views.volume_by_group_chart(vol, contracts, spot, xr, session), use_container_width=True,
                        key="p2_vol")
        rank = views.volume_ranking_table(vol, contracts, session)
        if rank.empty:
            st.info("この範囲・セッションに掲載銘柄がありません。")
        else:
            st.dataframe(rank, hide_index=True, use_container_width=True)
        st.caption("手口に載るのはその日の取引高が大きい銘柄（8〜18銘柄程度）で、遠いストライクはほぼ載りません。"
                   "取引高はランキング掲載分（上位参加者）の合計で、全体の取引高ではありません。")

    st.subheader("週次: 売超/買超の参加者（期近限月・ATM近傍5ストライク）")
    weekly = views.pt.load_weekly()
    if weekly.empty:
        st.info("週次の参加者別建玉残高がありません。")
    else:
        avail = sorted(weekly["asof_date"].unique())
        avail = [a for a in avail if a.strftime("%Y-%m-%d") <= selected_date] or avail
        asof = st.selectbox("基準週（金曜時点）", options=list(reversed(avail)),
                            format_func=lambda a: a.strftime("%Y-%m-%d"))
        wt = views.weekly_net_table(weekly, asof)
        st.dataframe(wt, hide_index=True, use_container_width=True)
        dealers = wt[(wt["区分"] == "業者側") & (wt["売超/買超"] == "売超")]
        if not dealers.empty:
            s = dealers.groupby(["限月", "P/C", "権利行使価格"])["枚数"].sum().reset_index()
            st.markdown("**業者側の売超（このATM近傍5ストライクのみ）**")
            st.dataframe(s, hide_index=True, use_container_width=True)
        st.caption("公開されるのは売超/買超の上位参加者のみ（最大15位）。業者側以外の参加者、掲載外のストライクは見えません。")

    with st.expander("「業者側」とみなす参加者の一覧（261004_participants.py で変更できます）"):
        d = views.pt.DEALER_SIDE
        c = views.pt.CLEARING_BROKERS
        st.dataframe(pd.DataFrame([{"コード": k, "名称": v, "区分": "業者側"} for k, v in d.items()]
                                  + [{"コード": k, "名称": v, "区分": "清算業者（別枠）"} for k, v in c.items()]),
                     hide_index=True, use_container_width=True)


def main():
    dates = list_available_dates()
    if not dates:
        st.title("日経225オプション 建玉残高ダッシュボード")
        st.warning("データがまだありません。`python fetch_open_interest.py` を実行してdata/にCSVを作成してください。")
        return

    latest_date = dates[-1]

    with st.sidebar:
        st.title("⚙️ 設定")
        selected_date = st.selectbox("基準日", options=list(reversed(dates)), index=0,
                                      format_func=lambda d: d)
        st.markdown("---")

        df_snap = load_snapshot(selected_date)
        products = sorted(df_snap["product"].unique()) if not df_snap.empty else ["standard", "mini"]
        product_label = {"standard": "通常オプション", "mini": "ミニオプション"}
        product = st.radio("商品", options=products, format_func=lambda p: product_label.get(p, p))

        contracts = sorted(df_snap[df_snap["product"] == product]["contract"].unique()) if not df_snap.empty else []
        contract = st.selectbox("限月", options=contracts,
                                 format_func=lambda c: fmt_contract_label(product, c) if c else c)

        st.markdown("---")
        st.markdown("**表示レンジ**")
        _underlying = views.underlying_close(selected_date)
        _default_center, _ = compute_max_pain(df_snap, product, contract) if not df_snap.empty else (None, None)
        _default_price = _underlying if _underlying else (float(_default_center) if _default_center else 0.0)
        current_price = st.number_input(
            "現在値（日経225、目安）", value=float(_default_price), step=5.0, format="%.2f",
            key=f"current_price_{selected_date}",
            help="C-P差分・建玉の増減・ガンママップの中心と表示レンジに使う現在値。"
                 "初期値は基準日の日経平均終値（JPX理論価格フィードの原資産終値）。"
                 "終値データが無い日はマックスペイン価格を仮置きするので、実際の値に書き換えてください。",
        )
        range_width = st.selectbox("表示レンジ幅（現在値±）", options=RANGE_WIDTH_OPTIONS, index=2,
                                    format_func=lambda w: f"±{w:,}円")

        st.markdown("---")
        st.markdown("**自分のポジション（権利行使価格）**")
        show_position = st.checkbox("チャートに重ねて表示", value=True)
        put_long = st.number_input("プット買い", value=0, step=250)
        put_short = st.number_input("プット売り", value=0, step=250)
        call_short = st.number_input("コール売り", value=0, step=250)
        call_long = st.number_input("コール買い", value=0, step=250)

        st.markdown("---")
        if len(dates) > 1:
            lookback = st.slider("推移表示の対象日数", min_value=1, max_value=len(dates), value=min(10, len(dates)))
        else:
            lookback = 1
            st.caption("推移表示は2日分以上データが蓄積すると使えます")
        st.markdown("---")
        if st.button("🔄 キャッシュクリア"):
            st.cache_data.clear()
            st.rerun()

    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    st.markdown(f"""
    <h1 style='text-align:center;'>日経225オプション 建玉残高ダッシュボード</h1>
    <h4 style='text-align:center; color:#8b949e;'>
        基準日: {selected_date}　｜　表示: {now}
    </h4>
    """, unsafe_allow_html=True)

    position_strikes = []
    if show_position:
        position_strikes = [
            ("プット買", put_long), ("プット売", put_short),
            ("コール売", call_short), ("コール買", call_long),
        ]
        position_strikes = [(l, s) for l, s in position_strikes if s]

    recent_dates = dates[-lookback:]
    history_df = load_history(recent_dates)

    tabs = st.tabs(["📊 建玉・C-P（既存）", "① 建玉の増減", "② ガンママップ", "③ 手口（限定版）"])
    with tabs[0]:
        # サマリーカード
        d = df_snap[(df_snap["product"] == product) & (df_snap["contract"] == contract)]
        max_pain_strike, max_pain_loss_df = compute_max_pain(df_snap, product, contract)
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("プット建玉合計", f"{int(d[d['put_call']=='Put']['oi'].sum()):,}枚")
        col2.metric("コール建玉合計", f"{int(d[d['put_call']=='Call']['oi'].sum()):,}枚")
        put_call_ratio = (d[d['put_call']=='Put']['oi'].sum() / d[d['put_call']=='Call']['oi'].sum()
                           if d[d['put_call']=='Call']['oi'].sum() else 0)
        col3.metric("プット/コール比", f"{put_call_ratio:.2f}")
        max_call_strike = d[d['put_call']=='Call'].sort_values('oi', ascending=False)['strike'].head(1)
        col4.metric("コール最大建玉ストライク", f"{int(max_call_strike.iloc[0]):,}円" if len(max_call_strike) else "N/A")
        col5.metric("マックスペイン価格", f"{max_pain_strike:,}円" if max_pain_strike is not None else "N/A")

        st.markdown("---")

        price_range = (current_price - range_width, current_price + range_width) if current_price > 0 else None
        center_price = current_price if current_price > 0 else None

        st.plotly_chart(oi_bar_chart(df_snap, product, contract, position_strikes, price_range=price_range),
                         use_container_width=True, key="oi_bar")

        st.plotly_chart(
            cp_diff_bar_chart(df_snap, product, contract, current_price=center_price, range_width=range_width,
                               position_strikes=position_strikes),
            use_container_width=True, key="cp_diff",
        )
        st.caption(
            "C-P差分＝コール建玉残高－プット建玉残高。青（正）＝コール優位、オレンジ（負）＝プット優位。"
            "サイドバーの「現在値」「表示レンジ幅」でこのチャートと上の権利行使価格別建玉残高チャートの表示範囲を調整できます。"
        )

        col_a, col_b = st.columns(2)
        with col_a:
            st.plotly_chart(oi_change_bar_chart(df_snap, product, contract), use_container_width=True, key="oi_change")
        with col_b:
            trend_strikes = [s for _, s in position_strikes] if position_strikes else []
            st.plotly_chart(multi_day_trend_chart(history_df, product, contract, trend_strikes), use_container_width=True, key="multi_day_trend")

        st.markdown("---")
        st.subheader("📈 追加分析: Put/Call比推移・マックスペイン")
        col_c, col_d = st.columns(2)
        with col_c:
            st.plotly_chart(put_call_ratio_trend_chart(history_df, product, contract), use_container_width=True, key="pc_ratio_trend")
        with col_d:
            st.plotly_chart(max_pain_chart(max_pain_loss_df, max_pain_strike, position_strikes), use_container_width=True, key="max_pain")
        st.plotly_chart(max_pain_trend_chart(history_df, product, contract), use_container_width=True, key="max_pain_trend")
        st.caption(
            "マックスペイン理論: 満期の決済価格がその権利行使価格になった場合に、オプション買い手が受け取る"
            "本質的価値の合計（＝オプション売り手の支払い総額）が最小になる権利行使価格。売り手優位の目安として"
            "参考程度に見るもので、将来の価格を予測するものではない。"
        )

        with st.expander("生データを見る"):
            st.dataframe(d.sort_values(["put_call", "strike"]), use_container_width=True)

    with tabs[1]:
        render_oi_change_tab(df_snap, dates, selected_date, current_price)
    with tabs[2]:
        render_gamma_tab(df_snap, selected_date, current_price)
    with tabs[3]:
        render_participant_tab(df_snap, selected_date, current_price)

    st.markdown("---")
    st.caption(f"データ: JPX「デリバティブ建玉残高表」｜ 蓄積データ日数: {len(dates)}日分（{dates[0]} 〜 {dates[-1]}）")


if __name__ == "__main__":
    main()
