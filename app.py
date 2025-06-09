import streamlit as st
import pandas as pd
import numpy as np
import requests
import itertools
import json
import xmltodict
from datetime import datetime
import re
import io 

st.set_page_config(layout="wide")
st.title("🏗️ 1365 사정율 분석 도구")
st.markdown("공고번호를 입력하면 복수예가 조합, 낙찰하한율, 개찰결과를 분석해 드립니다.")

# 커스텀 CSS 삽입
st.markdown("""
<style>
/* 통합 사정율 테이블 헤더 셀 스타일 */
div[data-testid="stDataFrame"] .st-emotion-cache-16ffz97 {
    white-space: normal !important;
    word-wrap: break-word !important;
    text-align: center;
    vertical-align: middle;
    font-size: 11px;
    line-height: 1.3;
    padding: 4px 8px;
}

/* Rate 컬럼 헤더는 좌측 정렬 유지 및 글자 크기 조정 */
div[data-testid="stDataFrame"] .st-emotion-cache-16ffz97:first-child {
    text-align: left !important;
    font-size: 12px !important;
}

/* 각 공고별 사정율 테이블의 헤더 셀 (개별 테이블에만 적용) */
.stDataFrame > div > div > div > div > div > div:nth-child(2) > div > div > div > div {
    white-space: normal !important;
    word-wrap: break-word !important;
    text-align: center;
    vertical-align: middle;
    font-size: 11px;
    line-height: 1.3;
    padding: 4px 8px;
}
</style>
""", unsafe_allow_html=True)


display_width = st.selectbox("📏 표 표시 너비 설정", ["자동(전체 너비)", "고정(좁게)"])
use_wide = display_width == "자동(전체 너비)" 

# --- Session State 초기화 및 관리 ---
# 앱의 시작 상태를 정의
if 'gongo_nums_input_value' not in st.session_state:
    st.session_state.gongo_nums_input_value = ""
if 'analysis_completed' not in st.session_state:
    st.session_state.analysis_completed = False # 분석 완료 여부
if 'results_by_gongo_data' not in st.session_state:
    st.session_state.results_by_gongo_data = [] # 분석 결과 데이터 (이름 변경)
if 'errors_data' not in st.session_state:
    st.session_state.errors_data = [] # 오류 메시지
if 'processed_gongo_nums' not in st.session_state:
    st.session_state.processed_gongo_nums = [] # 처리된 공고번호 목록

# --- analyze_gongo 함수 정의 (최상단) ---
@st.cache_data(ttl=3600)
def analyze_gongo(gongo_nm):
    top_bidder_info = {"name": "정보 없음", "rate": "N/A"}
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        service_key = st.secrets.get("SERVICE_KEY", None)
        if service_key is None or not service_key.strip():
            raise Exception("Streamlit Secrets에 'SERVICE_KEY'가 설정되지 않았거나 비어 있습니다.")

        # ▶ 복수예가 상세
        url1 = f'http://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpengResultListInfoCnstwkPreparPcDetail?inqryDiv=2&bidNtceNo={gongo_nm}&bidNtceOrd=00&pageNo=1&numOfRows=15&type=json&ServiceKey={service_key}'
        res1 = requests.get(url1, headers=headers)
        if res1.status_code != 200:
            raise Exception(f"API 호출 실패 (복수예가): HTTP {res1.status_code}")
        data1 = json.loads(res1.text)
        
        if 'response' not in data1 or 'body' not in data1['response'] or 'items' not in data1['response']['body'] or not data1['response']['body']['items']:
            raise ValueError(f"복수예가 데이터 없음")
            
        items_data1_raw = data1['response']['body']['items']
        if isinstance(items_data1_raw, dict) and 'item' in items_data1_raw:
            items_data1 = items_data1_raw['item']
        else:
            items_data1 = items_data1_raw
            
        if not isinstance(items_data1, list):
            items_data1 = [items_data1]

        df1 = pd.json_normalize(items_data1) 
        df1 = df1[['bssamt', 'bsisPlnprc']].astype('float')
        df1['SA_rate'] = df1['bsisPlnprc'] / df1['bssamt'] * 100
        
        if len(df1) > 1:
            base_price = df1.iloc[1]['bssamt'] 
        else:
            if not df1.empty and 'bssamt' in df1.columns:
                base_price = df1.iloc[0]['bssamt']
                st.warning(f"공고번호 {gongo_nm}: 복수예가 항목이 2개 미만입니다. 첫 번째 예정가격을 기초금액으로 사용합니다.")
            else:
                raise ValueError("복수예가 데이터에서 유효한 기초금액을 찾을 수 없습니다.")
        
        # ▶ 조합 평균 계산
        if len(df1['SA_rate']) < 4:
            raise ValueError(f"복수예가 항목이 4개 미만입니다")
        combs = itertools.combinations(df1['SA_rate'], 4)
        rates = [np.mean(c) for c in combs]
        df_rates = pd.DataFrame(rates, columns=['rate']).sort_values('rate').reset_index(drop=True)
        df_rates['조합순번'] = range(1, len(df_rates)+1)

        # ▶ 낙찰하한율 조회
        url2 = f'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwk?inqryDiv=2&bidNtceNo={gongo_nm}&pageNo=1&numOfRows=10&type=json&ServiceKey={service_key}'
        res2 = requests.get(url2, headers=headers)
        if res2.status_code != 200:
            raise Exception(f"API 호출 실패 (낙찰하한율): HTTP {res2.status_code}")
        data2 = json.loads(res2.text)
        
        if 'response' not in data2 or 'body' not in data2['response'] or 'items' not in data2['response']['body'] or not data2['response']['body']['items']:
            raise ValueError(f"낙찰하한율 데이터 없음")
            
        items_data2_raw = data2['response']['body']['items']
        if isinstance(items_data2_raw, dict) and 'item' in items_data2_raw:
            items_data2 = items_data2_raw['item']
        else:
            items_data2 = items_data2_raw

        if not isinstance(items_data2, list):
            items_data2 = [items_data2]

        df2 = pd.json_normalize(items_data2)
        
        if df2.empty or 'sucsfbidLwltRate' not in df2.columns:
            raise ValueError(f"낙찰하한율 데이터에 'sucsfbidLwltRate' 컬럼이 없거나 비어 있습니다.")
        
        sucsfbidLwltRate = float(df2.loc[0, 'sucsfbidLwltRate'])

        # ▶ A값 계산 (경고 메시지 포함)
        url3 = f'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwkBsisAmount?inqryDiv=2&bidNtceNo={gongo_nm}&pageNo=1&numOfRows=10&type=json&ServiceKey={service_key}'
        res3 = requests.get(url3, headers=headers)
        A_value = 0.0 # A값 기본값 0.0으로 설정 (실수형)
        a_value_warning_displayed = False

        if res3.status_code == 200:
            data3 = json.loads(res3.text)
            
            items_a_value_raw = data3.get('response', {}).get('body', {}).get('items', {})
            items_a_value = items_a_value_raw.get('item') if isinstance(items_a_value_raw, dict) else items_a_value_raw

            if items_a_value:
                if not isinstance(items_a_value, list):
                    items_a_value = [items_a_value]
                
                df3 = pd.DataFrame(items_a_value)
                
                cost_cols = ['sftyMngcst','sftyChckMngcst','rtrfundNon','mrfnHealthInsrprm','npnInsrprm','odsnLngtrmrcprInsrprm','qltyMngcst']
                valid_cost_cols = [col for col in cost_cols if col in df3.columns]
                
                if valid_cost_cols:
                    A_value = df3[valid_cost_cols].apply(pd.to_numeric, errors='coerce').fillna(0.0).sum(axis=1).iloc[0]
                else:
                    a_value_warning_displayed = True
            else:
                a_value_warning_displayed = True
        else:
            a_value_warning_displayed = True

        if a_value_warning_displayed:
            st.warning(f"⚠️ 경고: 공고번호 {gongo_nm} - A값 데이터 없음. A값은 0으로 처리됩니다.")

        # ▶ 개찰결과 (여기서 맨 첫 번째 업체가 1순위)
        url4 = f'http://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpengResultListInfoOpengCompt?serviceKey={service_key}&pageNo=1&numOfRows=999&bidNtceNo={gongo_nm}'
        res4 = requests.get(url4, headers=headers)
        if res4.status_code != 200:
            raise Exception(f"API 호출 실패 (개찰결과): HTTP {res4.status_code}")
        
        # XML 응답을 JSON으로 변환
        data4 = json.loads(json.dumps(xmltodict.parse(res4.text)))
        
        if 'response' not in data4 or 'body' not in data4['response'] or 'items' not in data4['response']['body'] or 'item' not in data4['response']['body']['items']:
            df4 = pd.DataFrame() # 개찰 결과 데이터가 없으면 빈 DataFrame
        else:
            items = data4['response']['body']['items']['item']
            if not isinstance(items, list):
                items = [items]
            df4 = pd.DataFrame(items)
            df4['bidprcAmt'] = pd.to_numeric(df4['bidprcAmt'], errors='coerce')
            df4 = df4.dropna(subset=['bidprcAmt'])

        if not df4.empty:
            top_bidder_name = df4.iloc[0]['prcbdrNm']

            if sucsfbidLwltRate != 0 and base_price != 0:
                df4['rate'] = (((df4['bidprcAmt'] - A_value) * 100) / sucsfbidLwltRate + A_value) * 100 / base_price
            else:
                df4['rate'] = np.nan

            df4 = df4.drop_duplicates(subset=['rate']).copy()
            df4 = df4[(df4['rate'] >= 90) & (df4['rate'] <= 110)].copy()
            df4 = df4[['prcbdrNm', 'rate']].rename(columns={'prcbdrNm': '업체명'})

            top_bidder_rate_row = df4[df4['업체명'] == top_bidder_name]
            if not top_bidder_rate_row.empty:
                top_bidder_info = {
                    "name": top_bidder_name,
                    "rate": round(top_bidder_rate_row.iloc[0]['rate'], 5)
                }
            else:
                 top_bidder_info = {"name": top_bidder_name, "rate": "범위 외"}
        else:
            top_bidder_info = {"name": "개찰 결과 없음", "rate": "N/A"}

        # 조합 사정율과 개찰 결과 사정율을 병합
        df_combined_gongo = pd.concat([
            df_rates[['rate']].assign(업체명=df_rates['조합순번'].astype(str)), 
            df4.rename(columns={'업체명': '업체명'})
        ], ignore_index=True).sort_values('