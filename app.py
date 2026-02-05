import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import plotly.express as px
import numpy as np
import json 

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
                if "passwords" not in st.secrets:
                    st.error("❌ 找不到 secrets.toml 設定檔！")
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

# --- 🛠️ 數據清洗工具 ---
def clean_df_for_streamlit(df):
    if df.empty: return df
    df = df.reset_index(drop=True)
    try:
        data_dict = df.to_dict(orient='records')
        df_clean = pd.DataFrame(data_dict)
        return df_clean
    except:
        return df

# --- 3. (v3.2 更新) 提早讀取並過濾英雄榜資料 ---
@st.cache_data(ttl=600)
def load_leaderboard_data():
    if "leaderboard" not in st.secrets:
        return pd.DataFrame()
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(spreadsheet=st.secrets["leaderboard"]["url"])
        
        # 🛡️ [v3.2 關鍵修正] 過濾掉被誤判為人員的「門市總表」
        if not df.empty and '人員' in df.columns and '分店' in df.columns:
            # 邏輯：如果「人員名稱」等於「分店名稱」扣掉"店"字 (例如: 小西門店 vs 小西門)
            # 就要把它刪掉，因為它是總表
            
            # 1. 建立一個過濾遮罩
            # df['分店'].str.replace('店', '') 會把 "小西門店" 變成 "小西門"
            mask = df['人員'] != df['分店'].str.replace('店', '')
            
            # 2. 額外過濾：如果有任何人員名稱完全包含"店"字且跟分店名一樣，也過濾
            mask2 = df['人員'] != df['分店']
            
            # 應用過濾
            df = df[mask & mask2]
            
        return df
    except Exception:
        return pd.DataFrame()

# 載入並自動過濾資料
df_lb = load_leaderboard_data()

# --- 4. 側邊欄與主要資料讀取 ---
with st.sidebar:
    st.header("🏢 請選擇分店")
    branch_options = ["ALL", "東門店", "小西門店", "文賢店", "歸仁店", "永康店", "安中店", "鹽行店", "五甲店"]
    selected_branch = st.selectbox("切換戰情看板", branch_options)

    try:
        if "branch_urls" not in st.secrets:
            st.error("❌ 找不到 [branch_urls] 設定")
            st.stop()
        target_url = st.secrets["branch_urls"][selected_branch]
    except KeyError:
        st.error(f"❌ 尚未設定「{selected_branch}」")
        st.stop()

    target_person = "全店總表"
    worksheet_to_load = selected_branch 

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

    st.info(f"檢視模式：{selected_branch} > {target_person}")
    
    if st.button("🔄 強制重新讀取"):
        st.cache_data.clear()
        st.rerun()

# --- 讀取單店/單人詳細資料 ---
@st.cache_data(ttl=600)
def load_data(url, worksheet):
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_raw = conn.read(spreadsheet=url, worksheet=worksheet, header=None)
    
    try:
        year_val = pd.to_numeric(df_raw.iloc[1, 0], errors='coerce')
        month_val = pd.to_numeric(df_raw.iloc[1, 1], errors='coerce')
        year_val = int(year_val) if not pd.isna(year_val) else 2026
        month_val = int(month_val) if not pd.isna(month_val) else 1
    except:
        year_val = 2026; month_val = 1

    headers = df_raw.iloc[2].astype(str).str.strip()
    df = df_raw.iloc[14:].copy()
    df.columns = headers
    
    valid_columns = [col for col in df.columns if col.lower() != 'nan' and not col.startswith('Unnamed') and col.strip() != ""]
    df = df[valid_columns]
    df = df.loc[:, ~df.columns.duplicated()]
    
    if not df.empty:
        first_col = df.columns[0]
        df = df[pd.to_numeric(df[first_col], errors='coerce').notna()]
        df['year'] = year_val
        df['month'] = month_val
        df['day'] = df[first_col].astype(int)
        df['日期'] = pd.to_datetime(df[['year', 'month', 'day']], errors='coerce')
        df = df.drop(columns=['year', 'month', 'day'])

    for col in df.columns:
        if col != '日期':
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(float)
            
    return df

try:
    df_view = load_data(target_url, worksheet_to_load)
except Exception as e:
    st.error("❌ 資料讀取失敗")
    st.stop()

# --- 5. 儀表板顯示 ---
display_title = f"{selected_branch} - {target_person}"
st.title(f"📊 {display_title} 戰情室")

if df_view.empty:
    st.warning("⚠️ 無資料")
    st.stop()

# [第一層] 營運戰情看板
def get_sum(col_name): return df_view.get(col_name, pd.Series([0])).sum()

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
        daily_data = df_view.groupby('日期')['毛利'].sum().reset_index()
        daily_data = daily_data.sort_values('日期')
        daily_data = clean_df_for_streamlit(daily_data)
        fig_line = px.line(daily_data, x='日期', y='毛利', markers=True)
        fig_line.update_xaxes(tickformat="%m/%d") 
        fig_line.update_layout(height=350)
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.warning("無法畫圖")

with c2:
    st.subheader("📊 各店毛利佔比")
    
    if df_lb.empty:
        st.info("⚠️ 無法讀取全公司資料，請確認 GAS 腳本。")
    else:
        # [v3.2] 這裡使用的 df_lb 已經在上方過濾過，所以數字會是正確的
        if '毛利' in df_lb.columns and '分店' in df_lb.columns:
            df_lb['毛利'] = pd.to_numeric(df_lb['毛利'], errors='coerce').fillna(0)
            
            df_branch_pie = df_lb.groupby('分店')['毛利'].sum().reset_index()
            df_branch_pie = clean_df_for_streamlit(df_branch_pie)
            
            fig_pie = px.pie(
                df_branch_pie, 
                values='毛利', 
                names='分店', 
                hole=0.4,
                title="全公司總營收結構"
            )
            fig_pie.update_layout(height=350, showlegend=True, margin=dict(t=30, b=0, l=0, r=0))
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.warning("欄位缺失，無法繪製佔比圖")

st.markdown("---")

# =========================================================
#  🏆 全公司業績英雄榜
# =========================================================
st.subheader("🏆 全公司業績英雄榜")
with st.expander("展開查看全公司跨店排名 (由 GAS 自動彙整)", expanded=True):
    
    if df_lb.empty:
        if "leaderboard" not in st.secrets:
             st.error("❌ 讀取失敗：您的 secrets.toml 缺少 `[leaderboard]` 設定。")
        else:
             st.warning("⚠️ 連線成功但無資料。請確認 GAS 腳本已執行。")
    else:
        tab1, tab2 = st.tabs(["👤 個人排名", "🏢 門市排名"])
        
        rank_options = [
            "毛利", "門號", "保險營收", "配件營收", 
            "庫存手機", "蘋果手機", "蘋果平板+手錶", "VIVO手機",
            "生活圈", "GOOGLE 評論", "來客數", 
            "遠傳續約累積GAP", "遠傳升續率", "遠傳平續率"
        ]
        
        # --- 分頁 1: 個人排名 ---
        with tab1:
            lb_col1, lb_col2 = st.columns([1, 3])
            with lb_col1:
                rank_metric_p = st.radio("指標 (個人)", rank_options, index=0, key="rank_p")
            
            with lb_col2:
                if rank_metric_p in df_lb.columns:
                    df_lb[rank_metric_p] = pd.to_numeric(df_lb[rank_metric_p], errors='coerce').fillna(0)
                    df_rank_p = df_lb.sort_values(by=rank_metric_p, ascending=False).head(20)
                    
                    # [v3.2] 這裡顯示的資料已經過濾掉「小西門」總表，所以個人排名不會再出現門市名
                    df_rank_p['Display'] = df_rank_p.apply(lambda x: f"{x['分店']} - {x['人員']}", axis=1)
                    
                    df_rank_p = clean_df_for_streamlit(df_rank_p)
                    
                    fig_rank_p = px.bar(
                        df_rank_p, x=rank_metric_p, y='Display', orientation='h',
                        text=rank_metric_p, title=f"🏆 個人 Top 20 - {rank_metric_p}",
                        color=rank_metric_p, color_continuous_scale='Blues'
                    )
                    fig_rank_p.update_layout(yaxis={'categoryorder':'total ascending'}, height=500)
                    fig_rank_p.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
                    st.plotly_chart(fig_rank_p, use_container_width=True)
        
        # --- 分頁 2: 門市排名 ---
        with tab2:
            lb_col3, lb_col4 = st.columns([1, 3])
            with lb_col3:
                rank_metric_s = st.radio("指標 (門市)", rank_options, index=0, key="rank_s")
            
            with lb_col4:
                if rank_metric_s in df_lb.columns:
                    # [v3.2] 這裡加總時，因為已經過濾掉重複的總表，所以數字會是正確的 (不會翻倍)
                    df_lb[rank_metric_s] = pd.to_numeric(df_lb[rank_metric_s], errors='coerce').fillna(0)
                    df_store = df_lb.groupby('分店')[rank_metric_s].sum().reset_index()
                    df_store = df_store.sort_values(by=rank_metric_s, ascending=False)
                    
                    df_store = clean_df_for_streamlit(df_store)
                    
                    fig_rank_s = px.bar(
                        df_store, x=rank_metric_s, y='分店', orientation='h',
                        text=rank_metric_s, title=f"🏢 門市總排名 - {rank_metric_s}",
                        color=rank_metric_s, color_continuous_scale='Reds'
                    )
                    fig_rank_s.update_layout(yaxis={'categoryorder':'total ascending'}, height=400)
                    fig_rank_s.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
                    st.plotly_chart(fig_rank_s, use_container_width=True)

        if '更新時間' in df_lb.columns:
            st.caption(f"ℹ️ 數據最後同步時間：{df_lb['更新時間'].iloc[0]}")

st.markdown("---")

# [第三層] 詳細資料表
with st.expander(f"查看 {display_title} 詳細資料"):
    df_display = df_view.copy()
    if '日期' in df_display.columns: df_display['日期'] = df_display['日期'].dt.strftime('%Y-%m-%d')
    
    first_col_name = df_display.columns[0]
    if '日期' in df_display.columns:
        cols = ['日期'] + [c for c in df_display.columns if c != '日期' and c != first_col_name]
        df_display = df_display[cols]
    
    df_display = clean_df_for_streamlit(df_display)
    
    for col in df_display.columns:
        if pd.api.types.is_numeric_dtype(df_display[col]):
            df_display[col] = df_display[col].astype(float)

    st.dataframe(df_display, use_container_width=True, hide_index=True)
