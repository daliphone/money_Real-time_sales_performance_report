import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import plotly.express as px
import numpy as np
import json # 引入 json 用於除錯

# --- 1. 頁面基礎設定 ---
st.set_page_config(page_title="馬尼通訊戰情室", page_icon="📱", layout="wide", initial_sidebar_state="expanded")

# --- 2. 安全登入機制 ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False
    if not st.session_state.password_correct:
        st.markdown("### 🔒 請輸入戰情室密碼")
        with st.form("login_form"):
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("登入")
            if submitted:
                # 檢查 secrets 是否存在
                if "passwords" not in st.secrets:
                    st.error("❌ 找不到 secrets.toml 設定檔！如果您在本機執行，請確認 .streamlit 資料夾內有此檔案。")
                    return False
                
                if password == st.secrets["passwords"]["main_password"]:
                    st.session_state.password_correct = True
                    st.rerun()
                else:
                    st.error("密碼錯誤")
        return False
    return True

if not check_password():
    st.stop()

# --- 🛠️ (v3.0 核心修復) 數據清洗工具 ---
# 這個函式專門用來解決 Windows 下 "int64 is not JSON serializable" 的崩潰問題
def clean_df_for_streamlit(df):
    if df.empty:
        return df
    
    # 1. 重設索引，避免 Index 是 int64
    df = df.reset_index(drop=True)
    
    # 2. 核彈級清洗：轉成 Python 原生字典再轉回來
    # 這會強迫所有 Numpy 特殊格式 (int64) 變成標準 Python int/float
    try:
        data_dict = df.to_dict(orient='records')
        df_clean = pd.DataFrame(data_dict)
        return df_clean
    except:
        return df

# --- 3. 側邊欄與資料讀取 ---
with st.sidebar:
    st.header("🏢 請選擇分店")
    branch_options = ["ALL", "東門店", "小西門店", "文賢店", "歸仁店", "永康店", "安中店", "鹽行店", "五甲店"]
    selected_branch = st.selectbox("切換戰情看板", branch_options)

    # 讀取主要資料
    try:
        if "branch_urls" not in st.secrets:
            st.error("❌ 找不到 [branch_urls] 設定，請檢查 secrets.toml")
            st.stop()
        target_url = st.secrets["branch_urls"][selected_branch]
    except KeyError:
        st.error(f"❌ 尚未設定「{selected_branch}」的試算表網址！")
        st.stop()

    # 人員選擇邏輯
    target_person = "全店總表"
    worksheet_to_load = selected_branch # 預設

    if selected_branch != "ALL":
        st.markdown("---")
        st.header("👤 選擇檢視對象")
        staff_list = []
        if "branch_staff" in st.secrets:
             staff_list = st.secrets["branch_staff"].get(selected_branch, [])
        
        if staff_list:
            options = ["全店總表"] + staff_list
            target_person = st.selectbox("請選擇人員", options)
            if target_person == "全店總表":
                worksheet_to_load = selected_branch
            else:
                worksheet_to_load = target_person
        else:
            worksheet_to_load = selected_branch

    else:
        target_person = "ALL"
        worksheet_to_load = "ALL"

    st.info(f"檢視模式：{selected_branch} > {target_person}")
    
    if st.button("🔄 強制重新讀取"):
        st.cache_data.clear()
        st.rerun()

# --- 資料讀取函式 ---
@st.cache_data(ttl=600)
def load_data(url, worksheet):
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_raw = conn.read(spreadsheet=url, worksheet=worksheet, header=None)
    
    # 處理年份月份
    try:
        year_val = pd.to_numeric(df_raw.iloc[1, 0], errors='coerce')
        month_val = pd.to_numeric(df_raw.iloc[1, 1], errors='coerce')
        year_val = int(year_val) if not pd.isna(year_val) else 2026
        month_val = int(month_val) if not pd.isna(month_val) else 1
    except:
        year_val = 2026
        month_val = 1

    headers = df_raw.iloc[2].astype(str).str.strip()
    df = df_raw.iloc[14:].copy()
    df.columns = headers
    
    valid_columns = [col for col in df.columns if col.lower() != 'nan' and not col.startswith('Unnamed') and col.strip() != ""]
    df = df[valid_columns]
    df = df.loc[:, ~df.columns.duplicated()]
    
    if not df.empty:
        first_col = df.columns[0]
        df = df[pd.to_numeric(df[first_col], errors='coerce').notna()]
        
        # 建立日期
        df['year'] = year_val
        df['month'] = month_val
        df['day'] = df[first_col].astype(int)
        df['日期'] = pd.to_datetime(df[['year', 'month', 'day']], errors='coerce')
        df = df.drop(columns=['year', 'month', 'day'])

    # 數值轉換：全部轉為 float
    for col in df.columns:
        if col != '日期':
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)
            
    return df

try:
    df_view = load_data(target_url, worksheet_to_load)
except Exception as e:
    st.error("❌ 資料讀取失敗")
    st.markdown(f"**詳細錯誤訊息：** `{e}`")
    st.stop()

# --- 4. 主要儀表板顯示 ---
display_title = f"{selected_branch} - {target_person}"
st.title(f"📊 {display_title} 戰情室")

if df_view.empty:
    st.warning("⚠️ 無資料")
    st.stop()

# =========================================================
#  [第一層] 營運戰情看板
# =========================================================
def get_sum(col_name):
    return df_view.get(col_name, pd.Series([0])).sum()

st.markdown("### 💰 營收與獲利")
m1, m2, m3 = st.columns(3)
with m1: st.metric("總毛利", f"${get_sum('毛利'):,.0f}")
with m2: st.metric("配件營收", f"${get_sum('配件營收'):,.0f}")
with m3: st.metric("保險營收", f"${get_sum('保險營收'):,.0f}")

st.markdown("### 📈 關鍵營運指標")
c1, c2, c3, c4 = st.columns(4)
with c1: st.metric("門號申辦數", f"{get_sum('門號'):,.0f}")
with c2: st.metric("總來客數", f"{get_sum('來客數'):,.0f}")
with c3: st.metric("Google 評論", f"{get_sum('GOOGLE 評論'):,.0f}")
with c4: st.metric("生活圈加入", f"{get_sum('生活圈'):,.0f}")

st.markdown("### 📱 手機與硬體銷售/庫存")
i1, i2, i3, i4 = st.columns(4)
with i1: st.metric("庫存手機", f"{get_sum('庫存手機'):,.0f}")
with i2: st.metric("VIVO 手機", f"{get_sum('VIVO手機'):,.0f}")
with i3: st.metric("蘋果手機", f"{get_sum('蘋果手機'):,.0f}")
with i4: st.metric("蘋果平板+手錶", f"{get_sum('蘋果平板+手錶'):,.0f}")

st.markdown("### 🔵 遠傳指標")
f1, f2, f3, f4 = st.columns(4)
with f1: st.metric("續約累積 GAP", f"{get_sum('遠傳續約累積GAP'):,.0f}")
with f2: st.metric("升續率", f"{get_sum('遠傳升續率'):.1f}") 
with f3: st.metric("平續率", f"{get_sum('遠傳平續率'):.1f}")
with f4: st.metric("綜合指標", f"{get_sum('綜合指標'):.1f}")

st.markdown("---")

# [第二層] 圖表區
c1, c2 = st.columns([2, 1])

with c1:
    st.subheader("📈 日毛利趨勢")
    if '日期' in df_view.columns and '毛利' in df_view.columns:
        # 使用 clean_df 確保圖表數據也是乾淨的
        daily_data = df_view.groupby('日期')['毛利'].sum().reset_index()
        daily_data = daily_data.sort_values('日期')
        daily_data = clean_df_for_streamlit(daily_data)
        
        fig_line = px.line(daily_data, x='日期', y='毛利', markers=True)
        fig_line.update_xaxes(tickformat="%m/%d") 
        fig_line.update_layout(height=350)
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.warning("無法畫圖：缺少必要欄位")

with c2:
    st.subheader("📊 營收結構")
    metrics = {'毛利': get_sum('毛利'), '配件營收': get_sum('配件營收'), '保險營收': get_sum('保險營收')}
    metrics = {k: v for k, v in metrics.items() if v > 0}
    if metrics:
        df_pie = pd.DataFrame(list(metrics.items()), columns=['類別', '金額'])
        df_pie = clean_df_for_streamlit(df_pie) # 清洗
        fig_pie = px.pie(df_pie, values='金額', names='類別', hole=0.4)
        fig_pie.update_layout(height=350, showlegend=True)
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("無數據")

st.markdown("---")

# =========================================================
#  🏆 全公司業績英雄榜 (v3.0 本機除錯版)
# =========================================================
st.subheader("🏆 全公司業績英雄榜")
with st.expander("展開查看全公司跨店排名 (由 GAS 自動彙整)", expanded=True):
    
    # 檢查是否在本機執行且缺少 secrets
    if "leaderboard" not in st.secrets:
        st.error("❌ 讀取失敗：您的 `secrets.toml` 檔案中缺少 `[leaderboard]` 設定。")
        st.info("💡 因為您是在本機執行，雲端的設定不會自動同步下來。請手動打開電腦裡的 `.streamlit/secrets.toml`，把 [leaderboard] 那一段貼進去。")
    else:
        try:
            leaderboard_url = st.secrets["leaderboard"]["url"]
            conn_lb = st.connection("gsheets", type=GSheetsConnection)
            df_lb = conn_lb.read(spreadsheet=leaderboard_url)
            
            if df_lb.empty:
                st.warning("⚠️ 連線成功但無資料。請確認 GAS 腳本已執行。")
            else:
                lb_col1, lb_col2 = st.columns([1, 3])
                with lb_col1:
                    rank_options = [
                        "毛利", "門號", "保險營收", "配件營收", 
                        "庫存手機", "蘋果手機", "蘋果平板+手錶", "VIVO手機",
                        "生活圈", "GOOGLE 評論", "來客數", 
                        "遠傳續約累積GAP", "遠傳升續率", "遠傳平續率"
                    ]
                    rank_metric = st.radio("選擇排名指標", rank_options, index=0)
                
                with lb_col2:
                    if rank_metric in df_lb.columns:
                        df_lb[rank_metric] = pd.to_numeric(df_lb[rank_metric], errors='coerce').fillna(0)
                        df_rank = df_lb.sort_values(by=rank_metric, ascending=False).head(20)
                        df_rank['Display'] = df_rank.apply(lambda x: f"{x['分店']} - {x['人員']}", axis=1)
                        
                        # 清洗數據以防圖表崩潰
                        df_rank = clean_df_for_streamlit(df_rank)
                        
                        fig_rank = px.bar(
                            df_rank, x=rank_metric, y='Display', orientation='h',
                            text=rank_metric, title=f"🏆 全公司 {rank_metric} 排行榜 Top 20",
                            color=rank_metric, color_continuous_scale='Blues'
                        )
                        fig_rank.update_layout(yaxis={'categoryorder':'total ascending'}, height=600, xaxis_title=rank_metric, yaxis_title="人員")
                        fig_rank.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
                        st.plotly_chart(fig_rank, use_container_width=True)
                        
                        if '更新時間' in df_rank.columns:
                            st.caption(f"ℹ️ 數據最後同步時間：{df_rank['更新時間'].iloc[0]}")
                    else:
                        st.warning(f"⚠️ 找不到欄位「{rank_metric}」。")

        except Exception as e:
            st.error("❌ 讀取失敗。")
            # 這裡我們把錯誤轉成字串顯示，確保看得到
            st.warning(f"錯誤類型: {type(e).__name__}")
            st.warning(f"錯誤內容: {str(e)}")

st.markdown("---")

# [第三層] 詳細資料表 (v3.0 核彈級修復版)
with st.expander(f"查看 {display_title} 詳細資料"):
    df_display = df_view.copy()
    
    # 1. 格式化日期
    if '日期' in df_display.columns: 
        df_display['日期'] = df_display['日期'].dt.strftime('%Y-%m-%d')
    
    # 2. 調整欄位
    first_col_name = df_display.columns[0]
    if '日期' in df_display.columns:
        cols = ['日期'] + [c for c in df_display.columns if c != '日期' and c != first_col_name]
        df_display = df_display[cols]
    
    # 3. [關鍵修正] 使用 clean_df_for_streamlit 徹底清洗
    # 這會把所有 int64 轉成標準 Python 數字，解決 JSON Error
    df_display = clean_df_for_streamlit(df_display)

    st.dataframe(df_display, use_container_width=True, hide_index=True)
