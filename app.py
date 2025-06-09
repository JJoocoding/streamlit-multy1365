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
    st.session_state.results_by_gongo_data = [] # 분석 결과 데이터
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
        # --- 디버깅용: API 응답 출력 ---
        st.write(f"--- {gongo_nm} 복수예가 API 응답 (url1) ---")
        st.code(res1.text)
        # ---------------------------------
        if res1.status_code != 200:
            raise Exception(f"API 호출 실패 (복수예가): HTTP {res1.status_code}")
        data1 = json.loads(res1.text)
        if 'response' not in data1 or 'body' not in data1['response'] or 'items' not in data1['response']['body'] or not data1['response']['body']['items']:
            raise ValueError(f"복수예가 데이터 없음")
        
        # 복수예가 데이터를 DataFrame으로 변환. 'item'이 리스트가 아닐 경우 처리
        items_df1 = data1['response']['body']['items']['item']
        if not isinstance(items_df1, list):
            items_df1 = [items_df1]
        df1 = pd.json_normalize(items_df1)
        
        # 'plnprcSeCd' (예정가격구분코드)를 사용하여 기초금액 찾기
        # '1'이 예정가격(기초금액)을 나타낸다고 가정
        base_price_rows = df1[df1['plnprcSeCd'] == '1']
        if not base_price_rows.empty:
            base_price = float(base_price_rows.iloc[0]['bssamt'])
        else:
            # 'plnprcSeCd'가 '1'인 데이터가 없으면, 기존 로직처럼 첫 번째 bssamt를 예정가격으로 간주 (최후의 보루)
            # 또는 오류를 발생시켜 사용자에게 알림
            if 'bssamt' in df1.columns and not df1.empty:
                base_price = float(df1.iloc[0]['bssamt'])
                st.warning(f"공고번호 {gongo_nm}: 'plnprcSeCd' 1인 기초금액을 찾을 수 없습니다. 첫 번째 예정가격을 기초금액으로 사용합니다.")
            else:
                raise ValueError("복수예가 데이터에서 유효한 기초금액을 찾을 수 없습니다.")

        df1['bssamt'] = pd.to_numeric(df1['bssamt'], errors='coerce')
        df1['bsisPlnprc'] = pd.to_numeric(df1['bsisPlnprc'], errors='coerce')
        df1['SA_rate'] = df1['bsisPlnprc'] / df1['bssamt'] * 100
        
        st.write(f"--- {gongo_nm} - 추출된 base_price: {base_price} ---") # 디버깅용
        
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
        # --- 디버깅용: API 응답 출력 ---
        st.write(f"--- {gongo_nm} 낙찰하한율 API 응답 (url2) ---")
        st.code(res2.text)
        # ---------------------------------
        if res2.status_code != 200:
            raise Exception(f"API 호출 실패 (낙찰하한율): HTTP {res2.status_code}")
        data2 = json.loads(res2.text)
        if 'response' not in data2 or 'body' not in data2['response'] or 'items' not in data2['response']['body'] or not data2['response']['body']['items']:
            raise ValueError(f"낙찰하한율 데이터 없음")
        df2 = pd.json_normalize(data2['response']['body']['items'])
        sucsfbidLwltRate = float(df2.loc[0, 'sucsfbidLwltRate'])
        st.write(f"--- {gongo_nm} - 추출된 sucsfbidLwltRate: {sucsfbidLwltRate} ---") # 디버깅용

        # ▶ A값 계산 (A값이 없으면 0으로 처리되며, 경고 메시지는 없음)
        url3 = f'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwkBsisAmount?inqryDiv=2&bidNtceNo={gongo_nm}&pageNo=1&numOfRows=10&type=json&ServiceKey={service_key}'
        res3 = requests.get(url3, headers=headers)
        # --- 디버깅용: API 응답 출력 ---
        st.write(f"--- {gongo_nm} A값 API 응답 (url3) ---")
        st.code(res3.text)
        # ---------------------------------
        A_value = 0 # A값 기본값 0으로 설정

        if res3.status_code == 200:
            data3 = json.loads(res3.text)
            
            # API 응답 구조를 확인하고, 'item'이 있는지 확인
            if 'response' in data3 and 'body' in data3['response'] and 'items' in data3['response']['body'] and 'item' in data3['response']['body']['items']:
                items_a_value = data3['response']['body']['items']['item']
                
                # 'item'이 단일 딕셔너리일 경우 리스트로 변환하여 DataFrame 생성을 용이하게 함
                if not isinstance(items_a_value, list):
                    items_a_value = [items_a_value]
                
                df3 = pd.DataFrame(items_a_value)
                
                # A값에 포함되는 비용 컬럼들 정의
                cost_cols = ['sftyMngcst','sftyChckMngcst','rtrfundNon','mrfnHealthInsrprm','npnInsrprm','odsnLngtrmrcprInsrprm','qltyMngcst']
                
                # df3에 실제로 존재하는 A값 관련 컬럼만 필터링
                valid_cost_cols = [col for col in cost_cols if col in df3.columns]
                
                if valid_cost_cols:
                    # 유효한 컬럼들의 값을 숫자로 변환하고(오류 시 NaN), NaN을 0으로 채운 후 합산
                    # .iloc[0]을 통해 첫 번째 행의 합계만 가져옴 (첫 번째 'item'의 합계를 A값으로 사용)
                    A_value = df3[valid_cost_cols].apply(pd.to_numeric, errors='coerce').fillna(0).sum(axis=1).iloc[0]
                # else: valid_cost_cols가 비어있으면 A_value는 초기값인 0으로 유지됨 (정상 처리)
            # else: API 응답에 'item'이 없거나 구조가 다르면 A_value는 초기값인 0으로 유지됨 (정상 처리)
        # else: API 호출 실패 시 A_value는 초기값인 0으로 유지됨 (정상 처리)
        st.write(f"--- {gongo_nm} - 추출된 A_value: {A_value} ---") # 디버깅용

        # ▶ 개찰결과 (여기서 맨 첫 번째 업체가 1순위)
        url4 = f'http://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpengResultListInfoOpengCompt?serviceKey={service_key}&pageNo=1&numOfRows=999&bidNtceNo={gongo_nm}'
        res4 = requests.get(url4, headers=headers)
        # --- 디버깅용: API 응답 출력 ---
        st.write(f"--- {gongo_nm} 개찰결과 API 응답 (url4) ---")
        st.code(res4.text)
        # ---------------------------------
        if res4.status_code != 200:
            raise Exception(f"API 호출 실패 (개찰결과): HTTP {res4.status_code}")
        
        # XML 응답을 JSON으로 변환
        data4 = json.loads(json.dumps(xmltodict.parse(res4.text)))
        
        if 'response' not in data4 or 'body' not in data4['response'] or 'items' not in data4['response']['body'] or 'item' not in data4['response']['body']['items']:
            df4 = pd.DataFrame() # 개찰 결과 데이터가 없으면 빈 DataFrame
        else:
            items = data4['response']['body']['items']['item']
            if not isinstance(items, list): # item이 단일 딕셔너리인 경우 리스트로 변환
                items = [items]
            df4 = pd.DataFrame(items)
            df4['bidprcAmt'] = pd.to_numeric(df4['bidprcAmt'], errors='coerce') # 입찰 금액을 숫자로 변환
            df4 = df4.dropna(subset=['bidprcAmt']) # 유효한 입찰 금액이 있는 행만 남김

        if not df4.empty:
            top_bidder_name = df4.iloc[0]['prcbdrNm'] # 1순위 업체명
            st.write(f"--- {gongo_nm} - 1순위 업체명: {top_bidder_name}, 입찰금액: {df4.iloc[0]['bidprcAmt']} ---") # 디버깅용

            # 사정율 계산식: ((입찰금액 - A값) * 100 / 낙찰하한율) + A값) * 100 / 기초금액
            # A_value는 이미 0 또는 실제 값으로 계산되어 들어옴
            if sucsfbidLwltRate != 0 and base_price != 0:
                # ### 디버깅용: 단계별 사정율 계산 값 출력
                df4['temp_bidprcAmt_minus_A'] = df4['bidprcAmt'] - A_value
                df4['temp_divide_by_sucsfbidLwltRate'] = df4['temp_bidprcAmt_minus_A'] * 100 / sucsfbidLwltRate
                df4['temp_add_A'] = df4['temp_divide_by_sucsfbidLwltRate'] + A_value
                df4['rate'] = df4['temp_add_A'] * 100 / base_price

                st.write(f"--- {gongo_nm} - 1순위 업체 사정율 계산 단계 ---")
                st.write(f"  bidprcAmt: {df4.iloc[0]['bidprcAmt']}")
                st.write(f"  A_value: {A_value}")
                st.write(f"  sucsfbidLwltRate: {sucsfbidLwltRate}")
                st.write(f"  base_price: {base_price}")
                st.write(f"  (bidprcAmt - A_value): {df4.iloc[0]['temp_bidprcAmt_minus_A']}")
                st.write(f"  (bidprcAmt - A_value) * 100 / sucsfbidLwltRate: {df4.iloc[0]['temp_divide_by_sucsfbidLwltRate']}")
                st.write(f"  ((...) + A_value): {df4.iloc[0]['temp_add_A']}")
                st.write(f"  Final Rate before rounding: {df4.iloc[0]['rate']}")
                # ----------------------------------------------------

            else:
                df4['rate'] = np.nan # 낙찰하한율이나 기초금액이 0이면 사정율 계산 불가

            df4 = df4.drop_duplicates(subset=['rate']).copy() # 중복된 사정율 제거
            df4 = df4[(df4['rate'] >= 90) & (df4['rate'] <= 110)].copy() # 90%~110% 범위 내의 사정율만 추출
            df4 = df4[['prcbdrNm', 'rate']].rename(columns={'prcbdrNm': '업체명'})

            top_bidder_rate_row = df4[df4['업체명'] == top_bidder_name]
            if not top_bidder_rate_row.empty:
                top_bidder_info = {
                    "name": top_bidder_name,
                    "rate": round(top_bidder_rate_row.iloc[0]['rate'], 5) # 5자리까지 반올림
                }
            else:
                 top_bidder_info = {"name": top_bidder_name, "rate": "범위 외"} # 1순위 업체 사정율이 범위 외
        else:
            top_bidder_info = {"name": "개찰 결과 없음", "rate": "N/A"} # 개찰 결과 자체가 없음

        # 조합 사정율과 개찰 결과 사정율을 병합
        df_combined_gongo = pd.concat([
            df_rates[['rate']].assign(업체명=df_rates['조합순번'].astype(str)), 
            df4.rename(columns={'업체명': '업체명'})
        ], ignore_index=True).sort_values('rate').reset_index(drop=True)
        df_combined_gongo['rate'] = round(df_combined_gongo['rate'], 5)
        
        df_combined_gongo['공고번호'] = gongo_nm 
        df_combined_gongo['강조_업체명'] = df_combined_gongo['업체명'] # 강조 처리를 위한 컬럼
        df_combined_gongo = df_combined_gongo.fillna('') # NaN 값을 빈 문자열로 채움

        return df_combined_gongo, None, top_bidder_info # 오류 메시지 필드는 None으로 반환 (A값 경고 제거)

    except ValueError as ve:
        # 특정 데이터 부족 등으로 인한 오류
        return pd.DataFrame(), f"⚠️ 경고: 공고번호 {gongo_nm} - {ve}", top_bidder_info
    except Exception as e:
        # 기타 예상치 못한 오류
        return pd.DataFrame(), f"❌ 오류 발생: 공고번호 {gongo_nm} - {e}", top_bidder_info


st.subheader("🔍 분석할 공고번호를 1개에서 10개까지 입력하세요 (줄바꿈으로 구분)")

# --- "처음으로" 버튼 로직 (UI 상단으로 이동하여 항상 보이게) ---
def reset_app():
    # 모든 관련 세션 상태 초기화
    st.session_state.gongo_nums_input_value = "" 
    st.session_state.analysis_completed = False
    st.session_state.results_by_gongo_data = []
    st.session_state.errors_data = []
    st.session_state.processed_gongo_nums = [] 
    st.cache_data.clear() # 캐시 데이터도 초기화
    # st.rerun() # 이 부분은 "Calling st.rerun() within a callback is a no-op." 경고를 발생시켰으므로 제거합니다.
                # 세션 상태가 변경되면 Streamlit이 자동으로 재실행됩니다.

# '처음으로' 버튼: 분석이 완료되었거나 입력 필드에 값이 있을 때만 표시
if st.session_state.analysis_completed or st.session_state.gongo_nums_input_value.strip():
    st.button("🔄 처음으로", on_click=reset_app)

if not st.session_state.analysis_completed:
    gongo_nums_input = st.text_area("예시: \n20230123456\n20230123457\n...", 
                                    height=200, 
                                    value=st.session_state.gongo_nums_input_value, 
                                    key="gongo_input_area") 

    if st.button("🚀 분석 시작", key="start_analysis_button"): 
        st.session_state.gongo_nums_input_value = gongo_nums_input # 현재 입력값 저장
        
        gongo_nums = [gn.strip() for gn in gongo_nums_input.split('\n') if gn.strip()]
        st.session_state.processed_gongo_nums = gongo_nums # 처리할 공고번호 목록 저장

        if not (1 <= len(gongo_nums) <= 10):
            st.error("⚠️ 공고번호는 1개에서 10개까지만 입력 가능합니다.")
            st.session_state.analysis_completed = False # 분석 완료 상태 해제
            st.session_state.processed_gongo_nums = [] # 처리 목록 초기화
        else:
            results_by_gongo = []
            errors = []

            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, gongo_nm in enumerate(gongo_nums): 
                status_text.text(f"📊 공고번호 {gongo_nm} 분석 중... ({i+1}/{len(gongo_nums)})")
                df_result, error_msg, top_bidder_info = analyze_gongo(gongo_nm)
                
                if error_msg: # analyze_gongo에서 반환된 오류 메시지가 있다면 추가
                    errors.append(error_msg)
                if not df_result.empty: # 분석 결과 DataFrame이 비어있지 않다면 저장
                    results_by_gongo.append({
                        "gongo_num": gongo_nm,
                        "df": df_result,
                        "top_bidder": top_bidder_info
                    })
                progress_bar.progress((i + 1) / len(gongo_nums)) # 진행률 업데이트

            status_text.empty() # 상태 텍스트 제거
            progress_bar.empty() # 진행률 바 제거

            st.session_state.results_by_gongo_data = results_by_gongo # 최종 결과 데이터 저장
            st.session_state.errors_data = errors # 최종 오류 메시지 저장
            st.session_state.analysis_completed = True # 분석 완료 상태로 변경
            st.rerun() # 분석 완료 후 UI를 갱신하기 위해 재실행

else: # st.session_state.analysis_completed가 True일 경우 (즉, 분석이 완료된 경우)
    results_by_gongo = st.session_state.results_by_gongo_data
    errors = st.session_state.errors_data
    gongo_nums = st.session_state.processed_gongo_nums 

    st.markdown("---") 

    if results_by_gongo:
        st.subheader("📈 각 공고별 사정율 분석 결과")
        
        num_cols_per_row = 2 # 한 줄에 표시할 컬럼 수
        
        for i in range(0, len(results_by_gongo), num_cols_per_row):
            cols = st.columns(num_cols_per_row) # 컬럼 생성
            
            for j, result_data in enumerate(results_by_gongo[i : i + num_cols_per_row]):
                with cols[j]: # 각 컬럼 내부에 결과 표시
                    gongo_num = result_data["gongo_num"]
                    df = result_data["df"]
                    top_bidder = result_data["top_bidder"]

                    # 개찰 결과가 있는 경우 업체명과 사정율 표시
                    if top_bidder["name"] != "개찰 결과 없음":
                        st.markdown(f"**공고번호 {gongo_num}**: **{top_bidder['name']}** (사정율: **{top_bidder['rate']}%**)")
                    else:
                        st.markdown(f"**공고번호 {gongo_num}**: 개찰 결과 정보 없음")
                    
                    # 개별 테이블에서 1순위 업체 및 특정 업체 강조
                    def highlight_top_bidder_individual(row, top_bidder_name):
                        styles = [''] * len(row)
                        if pd.notna(row['강조_업체명']) and row['강조_업체명'] == top_bidder_name:
                            styles = ['background-color: #ffcccc'] * len(row) # 1순위 업체 배경색
                        elif pd.notna(row['강조_업체명']) and "대명포장중기" in row['강조_업체명']:
                            styles = ['background-color: #ffffcc'] * len(row) # 대명포장중기 배경색
                        return styles

                    display_df_styled = df[['rate', '강조_업체명']].style.apply(
                        lambda row: highlight_top_bidder_individual(row, top_bidder['name']), axis=1
                    )

                    st.dataframe(
                        display_df_styled,
                        use_container_width=True, # 컨테이너 너비에 맞춤
                        hide_index=True, # 인덱스 숨기기
                        height=min(35 * len(df) + 38, 400) # 높이 동적 조절 (최대 400px)
                    )
                    st.markdown("---") # 각 공고별 결과 구분선

        st.markdown("---") 
        st.subheader("📊 통합 사정율 분석 결과") 

        merged_df = pd.DataFrame()
        top_bidder_info_for_header = {} 

        if results_by_gongo:
            # 모든 공고의 고유한 사정율을 모아서 기본 DataFrame 생성
            all_rates = pd.concat([res['df']['rate'] for res in results_by_gongo], ignore_index=True).unique()
            base_rates_df = pd.DataFrame({'rate': all_rates}).sort_values('rate').reset_index(drop=True)
            merged_df = base_rates_df
        
        # 공고번호를 역순으로 정렬하여 표시 (최신 공고가 먼저 오도록)
        ordered_gongo_nums = gongo_nums[::-1] 
        
        for gongo_num_to_process in ordered_gongo_nums:
            current_result_data = next((res for res in results_by_gongo if res['gongo_num'] == gongo_num_to_process), None)
            
            if current_result_data:
                df_current_gongo = current_result_data["df"].copy()
                top_bidder = current_result_data["top_bidder"]
                
                df_for_merge = df_current_gongo[['rate', '강조_업체명']].copy()
                df_for_merge.rename(columns={'강조_업체명': f'{gongo_num_to_process}'}, inplace=True) # 컬럼명 변경
                
                # 병합 (Outer Join으로 모든 사정율 포함)
                merged_df = pd.merge(merged_df, df_for_merge, on='rate', how='outer')
                
                top_bidder_info_for_header[gongo_num_to_process] = top_bidder # 헤더 정보 저장

        if not merged_df.empty:
            final_merged_df = merged_df.sort_values(by='rate').reset_index(drop=True)
            
            final_merged_df = final_merged_df.fillna('') # NaN 값을 빈 문자열로 채움

            columns_order = ['rate'] + ordered_gongo_nums # 최종 컬럼 순서
            final_merged_df = final_merged_df[columns_order]

            column_config_dict = {"rate": "Rate"} # Rate 컬럼 설정

            # 통합 테이블 헤더 설정 (HTML 태그 제거 및 정보 명확화)
            for gongo_num_col in ordered_gongo_nums: 
                top_info = top_bidder_info_for_header.get(gongo_num_col, {"name": "정보 없음", "rate": "N/A"})
                
                header_text = f"{gongo_num_col}" 
                if top_info["name"] != "개찰 결과 없음" and top_info["rate"] != "N/A":
                    header_text += f"\n({top_info['rate']:.5f}%)" # 사정율만 표시
                else:
                    header_text += "\n(정보 없음)" 
                
                column_config_dict[gongo_num_col] = st.column_config.TextColumn(
                    label=header_text, 
                    width="small" 
                )
            
            # 통합 테이블에서 1순위 업체 및 특정 업체 강조
            def highlight_top_bidder_in_merged_table(s, top_bidder_info_map):
                current_gongo_num_raw = s.name 
                top_info = top_bidder_info_map.get(current_gongo_num_raw) 
                
                styles = []
                for val in s:
                    style = ''
                    if top_info and top_info['name'] != "정보 없음" and top_info['name'] != "개찰 결과 없음" and \
                       pd.notna(val) and val == top_info['name']:
                        style = 'background-color: #ffcccc' # 1순위 업체 배경색
                    elif pd.notna(val) and "대명포장중기" in val and \
                         not (top_info and top_info['name'] != "정보 없음" and top_info['name'] != "개찰 결과 없음" and val == top_info['name']):
                        style = 'background-color: #ffffcc' # 대명포장중기 배경색 (1순위가 아닐 때만)
                    styles.append(style)
                return styles 

            columns_to_style = [col for col in final_merged_df.columns if col != 'rate']

            styled_final_merged_df = final_merged_df.style.apply(
                lambda s: highlight_top_bidder_in_merged_table(s, top_bidder_info_for_header), 
                subset=columns_to_style
            )
            
            st.dataframe(
                styled_final_merged_df,
                use_container_width=True,
                hide_index=True,
                height=min(35 * len(final_merged_df) + 38, 600),
                column_config=column_config_dict 
            )
        else:
            st.info("분석할 유효한 공고번호가 없거나 데이터 병합에 실패했습니다.")


        st.subheader("📥 전체 결과 다운로드")
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"통합_사정율분석_{now}.xlsx"
        
        if not final_merged_df.empty: 
            excel_buffer = io.BytesIO()
            # Styler 객체를 직접 엑셀로 저장. 이전에 사용된 to_excel(index=False) 방식과 동일하게 작동
            styled_final_merged_df.to_excel(excel_buffer, index=False, engine='openpyxl') 
            excel_buffer.seek(0)
            
            st.download_button(
                label="통합 결과 엑셀 다운로드",
                data=excel_buffer,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_button_key" 
            )
        else:
            st.info("다운로드할 통합 결과 데이터가 없습니다.")
        

    else:
        st.warning("분석할 유효한 공고번호가 없거나 모든 공고번호에서 오류가 발생했습니다.")

    if errors:
        st.subheader("⚠️ 분석 중 발생한 경고 및 오류:")
        for err in errors:
            st.write(err)
    elif not results_by_gongo and not errors and st.session_state.gongo_nums_input_value.strip():
         st.info("입력된 공고번호에 대한 분석 결과가 없습니다. 공고번호를 다시 확인해주세요.")