"""
日経225オプション 建玉残高ダッシュボード
データ: JPX「デリバティブ建玉残高表」(https://www.jpx.co.jp/markets/derivatives/trading-volume/)
"""
import glob
import os
import re
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

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
}

BASE = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE, "data")


# ============================================================
# データ読み込み
# ============================================================
@st.cache_data(ttl=1800)
def list_available_dates():
    files = glob.glob(os.path.join(DATA_DIR, "oi_*.csv"))
    dates = sorted(re.search(r"oi_(\d{8})\.csv", f).group(1) for f in files)
    return dates


@st.cache_data(ttl=1800)
def load_snapshot(date_str):
    path = os.path.join(DATA_DIR, f"oi_{date_str}.csv")
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
def oi_bar_chart(df, product, contract, position_strikes=None):
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
                              annotation_position="top")

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
        legend=dict(orientation="h", y=1.08),
        xaxis=dict(gridcolor=COLORS["grid"]),
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


# ============================================================
# メイン UI
# ============================================================
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
                                      format_func=lambda d: f"{d[:4]}-{d[4:6]}-{d[6:]}")
        st.markdown("---")

        df_snap = load_snapshot(selected_date)
        products = sorted(df_snap["product"].unique()) if not df_snap.empty else ["standard", "mini"]
        product_label = {"standard": "通常オプション", "mini": "ミニオプション"}
        product = st.radio("商品", options=products, format_func=lambda p: product_label.get(p, p))

        contracts = sorted(df_snap[df_snap["product"] == product]["contract"].unique()) if not df_snap.empty else []
        contract = st.selectbox("限月", options=contracts,
                                 format_func=lambda c: fmt_contract_label(product, c) if c else c)

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
        基準日: {selected_date[:4]}-{selected_date[4:6]}-{selected_date[6:]}　｜　表示: {now}
    </h4>
    """, unsafe_allow_html=True)

    position_strikes = []
    if show_position:
        position_strikes = [
            ("プット買", put_long), ("プット売", put_short),
            ("コール売", call_short), ("コール買", call_long),
        ]
        position_strikes = [(l, s) for l, s in position_strikes if s]

    # サマリーカード
    d = df_snap[(df_snap["product"] == product) & (df_snap["contract"] == contract)]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("プット建玉合計", f"{int(d[d['put_call']=='Put']['oi'].sum()):,}枚")
    col2.metric("コール建玉合計", f"{int(d[d['put_call']=='Call']['oi'].sum()):,}枚")
    put_call_ratio = (d[d['put_call']=='Put']['oi'].sum() / d[d['put_call']=='Call']['oi'].sum()
                       if d[d['put_call']=='Call']['oi'].sum() else 0)
    col3.metric("プット/コール比", f"{put_call_ratio:.2f}")
    max_call_strike = d[d['put_call']=='Call'].sort_values('oi', ascending=False)['strike'].head(1)
    col4.metric("コール最大建玉ストライク", f"{int(max_call_strike.iloc[0]):,}円" if len(max_call_strike) else "N/A")

    st.markdown("---")

    st.plotly_chart(oi_bar_chart(df_snap, product, contract, position_strikes), use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(oi_change_bar_chart(df_snap, product, contract), use_container_width=True)
    with col_b:
        recent_dates = dates[-lookback:]
        history_df = load_history(recent_dates)
        trend_strikes = [s for _, s in position_strikes] if position_strikes else []
        st.plotly_chart(multi_day_trend_chart(history_df, product, contract, trend_strikes), use_container_width=True)

    with st.expander("生データを見る"):
        st.dataframe(d.sort_values(["put_call", "strike"]), use_container_width=True)

    st.markdown("---")
    st.caption(f"データ: JPX「デリバティブ建玉残高表」｜ 蓄積データ日数: {len(dates)}日分（{dates[0][:4]}-{dates[0][4:6]}-{dates[0][6:]} 〜 {dates[-1][:4]}-{dates[-1][4:6]}-{dates[-1][6:]}）")


if __name__ == "__main__":
    main()
