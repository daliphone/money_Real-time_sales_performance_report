import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import plotly.express as px
import numpy as np
from datetime import datetime

# --- 1. 頁面基礎設定 (v7.0 正式版) ---
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

# --- 🛠️ 數據清洗與工具函式 ---
def clean_df_for_streamlit(df):
    if df.empty: return df
    df = df.reset_index(drop=True)
    try:
        data_dict = df.to_dict(orient='records')
        df_clean = pd.DataFrame(data_dict)
        return df_clean
    except:
        return df

def clean_google_sheet_url(url):
    if not isinstance(url, str): return url
    url = url.strip()
    if "#" in url: url = url.split("#")[0]
    if "/edit" in url: url = url.split("/edit")[0] + "/edit"
    return url

# --- 3. 讀取中央系統配置表 (核心邏輯：填補合併儲存格 + 強力去空白) ---
@st.cache_data(ttl=600)
def load_system_config():
    if "leaderboard" not in st.secrets:
        return pd.DataFrame(), pd.DataFrame() 
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        config_url = clean_google_sheet_url(st.secrets["leaderboard"]["url"])
        
        # 1. 讀取系統配置 (選單來源)
        df_config = conn.read(spreadsheet=config_url, worksheet="系統配置")
        
        # 強力清洗「系統配置表」的文字欄位
        if not df_config.empty:
            for col in df_config.columns:
                if df_config[col].dtype == object:
                    df_config[col] = df_config[col].astype(str).str.strip()

        # 2. 讀取排名結果 (資料來源)
        df_leaderboard_raw = conn.read(spreadsheet=config_url, worksheet="排名結果")
        
        # 複製一份做清洗
        df_clean = df_leaderboard_raw.copy()
        
        if not df_clean.empty:
             # 確保欄位名稱為字串
             cols = [str(c) for c in df_clean.columns]
             
             # --- 關鍵修復 1: 處理月份 (合併儲存格填補 + 格式統一) ---
             if '月份' in df_clean.columns:
                 df_clean['月份'] = df_clean['月份'].astype(str).str.strip()
                 df_clean['月份'] = df_clean['月份'].replace(['', 'nan', 'None'], np.nan)
                 df_clean['月份'] = df_clean['月份'].fillna(method='ffill') # 向下填補
                 
                 df_clean['月份_dt'] = pd.to_datetime(df_clean['月份'], errors='coerce')
                 df_clean['月份_std'] = df_clean['月份_dt'].dt.strftime('%Y-%m')

             # --- 關鍵修復 2: 處理分店 (合併儲存格填補 + 去空白) ---
             if '分店' in df_clean.columns:
                 df_clean['分店'] = df_clean['分店'].astype(str).str.strip()
                 df_clean['分店'] = df_clean['分店'].replace(['', 'nan', 'None'], np.nan)
                 df_clean['分店'] = df_clean['分店'].fillna(method='ffill') # 向下填補
                 df_clean['分店'] = df_clean['分店'].astype(str).str.strip() # 再次確保去空白

             # --- 關鍵修復 3: 處理人員 (去空白) ---
             if '人員' in df_clean.columns:
                 df_clean['人員'] = df_clean['人員'].astype(str).str.strip()
             
             # 排除關鍵字 (包含小西門等總表行)
             exclude_keywords = ["總表", "ALL", "Total", "小計", "合計", "小西門"] 
             mask_keyword = ~df_clean['人員'].isin(exclude_keywords)
             
             # 智慧排除 (人員名 == 分店名)
             def is_not_store_summary(row):
                 branch = str(row['分店']).replace('店', '') 
                 person = str(row['人員'])
                 if person == branch: return False
                 if person == row['分店']: return False
                 return True

             mask_smart = df_clean.apply(is_not_store_summary, axis=1)
             
             # 應用過濾
             df_clean = df_clean[mask_keyword & mask_smart]

        return df_config, df_clean
    except Exception as e:
        st.error(f"無法讀取系統配置表: {e}")
        return pd.DataFrame(), pd.DataFrame()

df_sys_config, df_lb_clean = load_system_config()

# --- 4. 側邊欄 ---
with st.sidebar:
    st.title("📅 業績月份")
    
    if st.button("🔄 更新資料/清除快取", type="primary"):
        st.cache_data.clear()
        st.rerun()
    
    if df_sys_config.empty:
        st.error("❌ 無法讀取配置表")
        st.stop()
    
    try:
        if '月份' in df_sys_config.columns:
            df_sys_config['月份_dt'] = pd.to_datetime(df_sys_config['月份'], errors='coerce')
            df_sys_config['月份_std'] = df_sys_config['月份_dt'].dt.strftime('%Y-%m')
            
            available_months = sorted(df_sys_config['月份_std'].dropna().unique(), reverse=True)
            current_month_str = datetime.now().strftime("%Y-%m")
            try:
                default_index = list(available_months).index(current_month_str)
            except:
                default_index = 0
        else:
            st.error("配置表缺少「月份」欄位")
            st.stop()
    except Exception as e:
        st.warning(f"月份解析錯誤: {e}")
        available_months = df_sys_config['月份'].astype(str).unique()
        default_index = 0

    selected_month = st.selectbox("請選擇月份", available_months, index=default_index)
    
    st.markdown("---")
    st.header("🏢 請選擇分店")
    
    # 使用標準化後的月份進行過濾
    mask_month = df_sys_config['月份_std'] == selected_month
    current_month_config = df_sys_config[mask_month]
    
    if current_month_config.empty:
        st.warning(f"找不到 {selected_month} 的設定資料")
        st.stop()

    branch_list = current_month_config['分店代號'].unique().tolist()
    if 'ALL' in branch_list:
        branch_list.remove('ALL')
        branch_list.insert(0, 'ALL')
    
    selected_branch = st.selectbox("切換戰情看板", branch_list)

    # 3. 取得網址
    try:
        target_row = current_month_config[current_month_config['分店代號'] == selected_branch]
        if not target_row.empty:
            raw_url = target_row.iloc[0]['試算表網址']
            target_url = clean_google_sheet_url(raw_url)
            # 顯示連線資訊
            if selected_branch != "ALL":
                st.caption(f"🔗 連線中: {selected_branch}")
        else:
            st.error("找不到該分店的網址")
            st.stop()
    except Exception as e:
        st.error(f"網址讀取失敗: {e}")
        st.stop()

    # 4. 人員選擇
    target_person = "全店總表"
    worksheet_to_load = selected_branch 

    if selected_branch != "ALL":
        st.markdown("---")
        st.header("👤 選擇檢視對象")
        staff_list = []
        if "branch_staff" in st.secrets:
             staff_list = st.secrets["branch_staff"].get(selected_branch, [])
             if not staff_list:
                 short_name = selected_branch.replace("店", "")
                 staff_list = st.secrets["branch_staff"].get(short_name, [])
             if not staff_list:
                 long_name = selected_branch + "店"
                 staff_list = st.secrets["branch_staff"].get(long_name, [])
        
        if staff_list:
            options = ["全店總表"] + staff_list
            target_person = st.selectbox("請選擇人員", options)
            if target_person == "全店總表":
                worksheet_to_load = selected_branch
            else:
                worksheet_to_load = target_person
        else:
            st.caption("⚠️ 未偵測到人員名單")

    st.info(f"檢視模式：{selected_month} > {selected_branch}")

# --- 讀取資料函式 (標準版) ---
@st.cache_data(ttl=600)
def load_data(url, worksheet, selected_branch_name):
    conn = st.connection("gsheets", type=GSheetsConnection)
    clean_url = clean_google_sheet_url(url)
    
    forced_name = None
    if "sheet_names" in st.secrets:
        forced_name = st.secrets["sheet_names"].get(selected_branch_name)
    
    try_list = []
    
    # 如果是全店總表模式，才需要猜分頁名
    if worksheet == selected_branch_name or worksheet in ["ALL", "總表", "全店總表"]:
        if forced_name: try_list.append(forced_name)
        try_list.extend([worksheet, worksheet.replace("店", ""), "總表", "ALL"])
    else:
        # 如果是選特定人，就只找那個人
        try_list = [worksheet] 
        
    df_raw = pd.DataFrame()
    last_error = None
    
    for sheet_name in try_list:
        try:
            df_raw = conn.read(spreadsheet=clean_url, worksheet=sheet_name, header=None)
            break 
        except Exception as e:
            last_error = e
            continue 
            
    # 嘗試讀取預設第一頁 (作為最後手段)
    if df_raw.empty and (worksheet == selected_branch_name or worksheet in ["ALL", "總表", "全店總表"]):
        try:
            df_raw = conn.read(spreadsheet=clean_url, header=None)
        except Exception as e:
            last_error = e

    if df_raw.empty:
        error_msg = f"❌ 無法讀取任何分頁。已嘗試名稱: {try_list}。請確認分頁名稱或 secrets 設定。"
        raise ValueError(error_msg)

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
    df_view = load_data(target_url, worksheet_to_load, selected_branch)
except Exception as e:
    st.error(f"❌ 資料讀取失敗")
    st.caption("請檢查 secrets.toml 中的網址是否正確，以及 Google 試算表權限。")
    st.stop()

# --- 5. 儀表板顯示 ---
display_title = f"{selected_month} {selected_branch} - {target_person}"
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

i5, i6, i7, i8 = st.columns(4)
with i5: st.metric("華為穿戴", f"{get_sum('華為穿戴'):,.0f}")
with i6: st.metric("GPLUS 吸塵器", f"{get_sum('GPLUS GP-S10吸塵器'):,.0f}")
with i7: st.metric("VIVO 目標", f"{get_sum('VIVO銷售目標'):,.0f}")
with i8: st.metric("橙艾玻璃貼", f"{get_sum('橙艾玻璃貼(13,14,15系列)'):,.0f}")

st.markdown("### 🔵 遠傳指標")
f1, f2, f3, f4 = st.columns(4)
with f1: st.metric("續約累積 GAP", f"{get_sum('遠傳續約累積GAP'):,.0f}")
with f2: st.metric("升續率", f"{get_sum('遠傳升續率'):.1f}") 
with f3: st.metric("平續率", f"{get_sum('遠傳平續率'):.1f}")
with f4: st.metric("綜合指標", f"{get_sum('綜合指標'):.1f}")

st.markdown("---")

# [第二層] 圖表區
c1, c2 = st.columns([2, 1])

# 使用標準化後的月份進行過濾
if df_lb_clean.empty:
    df_lb_month = pd.DataFrame()
else:
    mask_lb_month = df_lb_clean['月份_std'] == selected_month
    df_lb_month = df_lb_clean[mask_lb_month].copy()

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
    if selected_branch == "ALL":
        pie_title = "📊 各店毛利佔比"
        group_key = '分店' 
        pie_data_source = df_lb_month
    else:
        pie_title = "📊 該店人員毛利佔比"
        group_key = '人員' 
        if not df_lb_month.empty:
            pie_data_source = df_lb_month[df_lb_month['分店'] == selected_branch].copy()
        else:
            pie_data_source = pd.DataFrame()

    st.subheader(pie_title)
    
    if df_lb_month.empty:
        st.info(f"⚠️ 尚無 {selected_month} 彙整資料")
    elif pie_data_source.empty:
        st.info(f"⚠️ 尚無 {selected_branch} 的詳細資料")
    else:
        if '毛利' in pie_data_source.columns and group_key in pie_data_source.columns:
            pie_data_source['毛利'] = pd.to_numeric(pie_data_source['毛利'], errors='coerce').fillna(0)
            df_pie = pie_data_source.groupby(group_key)['毛利'].sum().reset_index()
            df_pie = clean_df_for_streamlit(df_pie)
            
            if not df_pie.empty and df_pie['毛利'].sum() > 0:
                fig_pie = px.pie(
                    df_pie, 
                    values='毛利', 
                    names=group_key, 
                    hole=0.4,
                    title=f"{selected_month} {selected_branch} 營收結構",
                    color_discrete_sequence=px.colors.sequential.Teal
                )
                fig_pie.update_layout(height=350, showlegend=True, margin=dict(t=30, b=0, l=0, r=0))
                fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info(f"⚠️ 毛利總和為 0")
        else:
            st.warning("欄位缺失")

st.markdown("---")

# =========================================================
#  🏆 業績英雄榜 (正式版)
# =========================================================
if selected_branch == "ALL":
    lb_title = f"🏆 全公司業績英雄榜 ({selected_month})"
else:
    lb_title = f"🏆 {selected_branch} 業績英雄榜 ({selected_month})"

st.subheader(lb_title)

with st.expander("展開查看詳細排名", expanded=True):
    
    if selected_branch == "ALL":
        df_rank_source = df_lb_month 
    else:
        if not df_lb_month.empty:
            df_rank_source = df_lb_month[df_lb_month['分店'] == selected_branch].copy()
        else:
            df_rank_source = pd.DataFrame()

    if df_rank_source.empty:
        st.info(f"⚠️ 尚無排名資料。")
    else:
        fixed_cols = ['月份', '分店', '人員', '更新時間', 'Display', '月份_dt', '月份_str', '月份_std']
        available_metrics = [c for c in df_rank_source.columns if c not in fixed_cols]
        priority = ["毛利", "門號", "保險營收", "配件營收"]
        sorted_metrics = sorted(available_metrics, key=lambda x: (priority.index(x) if x in priority else 999))
        
        if not sorted_metrics:
            st.warning("找不到任何指標欄位")
        else:
            if selected_branch == "ALL":
                tab1, tab2 = st.tabs(["👤 個人排名", "🏢 門市排名"])
                
                with tab1: 
                    lb_col1, lb_col2 = st.columns([1, 3])
                    with lb_col1:
                        rank_metric_p = st.radio("指標 (個人)", sorted_metrics, index=0, key="rank_p")
                    with lb_col2:
                        df_rank_source[rank_metric_p] = pd.to_numeric(df_rank_source[rank_metric_p], errors='coerce').fillna(0)
                        df_rank_p = df_rank_source.sort_values(by=rank_metric_p, ascending=False).head(20)
                        df_rank_p['Display'] = df_rank_p.apply(lambda x: f"{x['分店']} - {x['人員']}", axis=1)
                        df_rank_p['Display'] = df_rank_p['Display'].astype(str)
                        df_rank_p = clean_df_for_streamlit(df_rank_p)
                        
                        fig_rank_p = px.bar(
                            df_rank_p, x=rank_metric_p, y='Display', orientation='h',
                            text=rank_metric_p, title=f"🏆 全公司 Top 20 - {rank_metric_p}",
                            color=rank_metric_p, 
                            color_continuous_scale='Teal'
                        )
                        fig_rank_p.update_layout(yaxis={'type': 'category', 'categoryorder':'total ascending', 'title': '人員'}, height=500)
                        fig_rank_p.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
                        st.plotly_chart(fig_rank_p, use_container_width=True)

                with tab2: 
                    lb_col3, lb_col4 = st.columns([1, 3])
                    with lb_col3:
                        rank_metric_s = st.radio("指標 (門市)", sorted_metrics, index=0, key="rank_s")
                    with lb_col4:
                        df_rank_source[rank_metric_s] = pd.to_numeric(df_rank_source[rank_metric_s], errors='coerce').fillna(0)
                        df_store = df_rank_source.groupby('分店')[rank_metric_s].sum().reset_index()
                        df_store = df_store.sort_values(by=rank_metric_s, ascending=False)
                        df_store['分店'] = df_store['分店'].astype(str)
                        df_store = clean_df_for_streamlit(df_store)
                        
                        fig_rank_s = px.bar(
                            df_store, x=rank_metric_s, y='分店', orientation='h',
                            text=rank_metric_s, title=f"🏢 門市總排名 - {rank_metric_s}",
                            color=rank_metric_s, 
                            color_continuous_scale='Reds'
                        )
                        fig_rank_s.update_layout(yaxis={'type': 'category', 'categoryorder':'total ascending', 'title': '分店'}, height=400)
                        fig_rank_s.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
                        st.plotly_chart(fig_rank_s, use_container_width=True)

            else:
                lb_col1, lb_col2 = st.columns([1, 3])
                with lb_col1:
                    rank_metric_p = st.radio("選擇排名指標", sorted_metrics, index=0, key="rank_single")
                with lb_col2:
                    df_rank_source[rank_metric_p] = pd.to_numeric(df_rank_source[rank_metric_p], errors='coerce').fillna(0)
                    df_rank_p = df_rank_source.sort_values(by=rank_metric_p, ascending=False)
                    
                    df_rank_p['人員'] = df_rank_p['人員'].astype(str)
                    df_rank_p = clean_df_for_streamlit(df_rank_p)
                    
                    fig_rank_p = px.bar(
                        df_rank_p, x=rank_metric_p, y='人員', orientation='h',
                        text=rank_metric_p, title=f"🏆 {selected_branch} 人員排名 - {rank_metric_p}",
                        color=rank_metric_p, 
                        color_continuous_scale='Teal'
                    )
                    fig_rank_p.update_layout(yaxis={'type': 'category', 'categoryorder':'total ascending', 'title': '人員'}, height=500)
                    fig_rank_p.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
                    st.plotly_chart(fig_rank_p, use_container_width=True)

        if '更新時間' in df_rank_source.columns:
            st.caption(f"ℹ️ 數據最後同步時間：{df_rank_source['更新時間'].iloc[0]}")

st.markdown("---")

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
