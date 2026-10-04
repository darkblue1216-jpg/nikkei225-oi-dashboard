"""
手口（取引参加者別）データの読み込みと「業者側」判定（Phase 2・限定版）。

**日次の手口は取引高のみで売買区分がない**。したがって「どの参加者が売り越しか」は日次データからは
分からない。売買の向き（売超/買超）が分かるのは週次の参加者別建玉残高だけで、そちらは期近限月の
ATM近傍5ストライクしか載らない（docs/261004_phase0_data_survey.md参照）。
"""
import glob
import os

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
PV_DIR = os.path.join(BASE, "data", "participant_volume")
WK_DIR = os.path.join(BASE, "data", "participant_oi_weekly")

# ------------------------------------------------------------------
# 「業者側」とみなす参加者の一覧（変更しやすいようここに集約）。
# マーケットメイク・ヘッジを担うと見られる外資系証券。コードはJPXの参加者コード。
# 実際に誰がヘッジ主体かは公開データから断定できないので、あくまで目安。
# ------------------------------------------------------------------
DEALER_SIDE = {
    "12428": "BNPパリバ証券",
    "12792": "BofA証券",
    "11788": "ソシエテ・ジェネラル証券",
    "11714": "JPモルガン証券",
    "12800": "モルガン・スタンレーMUFG証券",
    "11746": "UBS証券",
    "11792": "シティグループ証券",
    "11560": "ゴールドマン・サックス証券",
    "12410": "バークレイズ証券",
    "12176": "ドイツ証券",
    "12724": "HSBC証券",
    "13004": "サスケハナ・ホンコン",
}
# 清算業者。顧客（内外の機関・個人）の注文を集約するため取引高は常に最大になるが、
# ヘッジ主体かどうかは区別できないので、業者側とは別枠で表示する。
CLEARING_BROKERS = {
    "12479": "ABNクリアリング証券",
}


def classify(code):
    if code in DEALER_SIDE:
        return "業者側"
    if code in CLEARING_BROKERS:
        return "清算業者"
    return "その他"


def load_volume(date_iso):
    path = os.path.join(PV_DIR, f"{date_iso}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, dtype={"contract": str, "participant_code": str})
    df["group"] = df["participant_code"].map(classify)
    return df


def load_weekly():
    frames = []
    for f in sorted(glob.glob(os.path.join(WK_DIR, "*.csv"))):
        frames.append(pd.read_csv(f, dtype={"contract": str, "participant_code": str}))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["asof_date"] = pd.to_datetime(df["asof_date"].astype(str), format="%Y%m%d")
    df["group"] = df["participant_code"].map(classify)
    return df
