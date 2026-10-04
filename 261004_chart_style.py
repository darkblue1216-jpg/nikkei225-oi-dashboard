"""
Plotlyグラフ共通のスタイル。凡例の文字色を白・背景を透明にする。

ダッシュボードのグラフは暗い背景で描いているが、Streamlit側のテーマが凡例の文字色を
暗い色にしてしまい読めなくなることがあるため、全グラフに共通で明示指定する。

install() を呼ぶと st.plotly_chart（列・タブ内の .plotly_chart も含む）に差し込まれ、
今後追加するグラフにも個別の指定なしで自動的に効く。
"""
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

LEGEND_STYLE = dict(font=dict(color="#FFFFFF"), bgcolor="rgba(0,0,0,0)")


def apply_common_layout(fig):
    """凡例のスタイルを共通指定する（既存のlegend設定のorientationなどは保たれる）。"""
    fig.update_layout(legend=LEGEND_STYLE)
    return fig


def install():
    """st.plotly_chart に共通レイアウトを自動適用する。何度呼んでも二重に包まない。"""
    # Streamlit外（HTML書き出しなど）で作るFigureにも効くよう、Plotlyの既定テンプレートにも入れる
    pio.templates["nk225_dark"] = go.layout.Template(layout=dict(legend=LEGEND_STYLE))
    pio.templates.default = "plotly+nk225_dark"

    if getattr(DeltaGenerator.plotly_chart, "_nk225_styled", False):
        return
    original = DeltaGenerator.plotly_chart

    def styled(self, figure_or_data, *args, **kwargs):
        if isinstance(figure_or_data, go.Figure):
            apply_common_layout(figure_or_data)
        return original(self, figure_or_data, *args, **kwargs)

    styled._nk225_styled = True
    DeltaGenerator.plotly_chart = styled
    # st.plotly_chart は import 時点の関数に束縛されているので、こちらも差し替える
    st.plotly_chart = st._main.plotly_chart
