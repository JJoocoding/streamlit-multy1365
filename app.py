import streamlit as st
import pandas as pd
import numpy as np
import requests
import itertools
import json
import xmltodict
from datetime import datetime
import re

st.set_page_config(layout="wide")
st.title("🏗️ 1365 사정율 분석 도구")
st.markdown("공고번호를 입력하면 복수예가 조합, 낙찰하한율, 개찰결과를 분석해 드립니다.")

# 커스텀 CSS 삽입 - 줄바꿈을 강제하고 폰트 크기 조절 시도
st.markdown("""
<style>
/* 통합 사정율 테이블 헤더 셀 스타일 */
/* .stDataFrame은 st.dataframe의 가장 바깥쪽 컨테이너 */
/* 이 셀렉터는 Streamlit 버전에 따라 변경될 수 있습니다. F12 개발자 도구로 정확한 클래스명을 확인해야 합니다. */
/* 현재 가장 일반적으로 사용되는 헤더 셀렉터 중 하나입니다. */
div[data-testid="stDataFrame"] .st-emotion-cache-16ffz97 { /* 통합 테이블 헤더 셀 */
    white-space: pre-wrap !important; /* '\n' 문자를 줄바꿈으로 인식하고 텍스트를 줄바꿈 */
    word-wrap: break-word !important; /* 긴 단어도 강제 줄바꿈 */
    text-align: center; /* 텍스트 가운데 정렬 */
    vertical-align: middle; /* 세로 가운데 정렬 */
    font-size: 11px; /* 글자 크기 조정 */
    line-height: 1.3; /* 줄 간격 조정 */
    padding: 4px 8px; /* 패딩 조정 */
}

/* Rate 컬럼 헤더는 좌측 정렬 유지 및 글자 크기 조정 */
div[data-testid="stDataFrame"] .st-emotion-cache-16ffz97:first-child {
    text-align: left !important;
    font-size: 12px !important; /* Rate 컬럼 헤더의 글자 크기는 조금 더 크게 */
}

/* 각 공고별 사정율 테이블의 헤더 셀 (개별 테이블에만 적용) */
/* 이 셀렉터도 정확한 클래스명을 확인해야 합니다. */
/* 일단 일반적인 셀렉터를 사용하고, 안 되면 개발자 도구로 확인 */
.stDataFrame > div > div > div > div > div > div:nth-child(2) > div > div > div > div {
    white-space: pre-wrap !important;
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

st.subheader("🔍 분석할 공고번호를 1개에서 10개까지 입력하세요 (줄바꿈으로 구분)")
gongo_nums_input = st.text_area("예시: \n20230123456\n20230123457\n...", height=200)

@st.cache_data(ttl=3600)
def analyze_gongo(gongo_nm):
    top_bidder_info = {"name": "정보 없음", "rate": "N/A"}
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        service_key = st.secrets["SERVICE_KEY"] 


        # ▶ 복수예가 상세
        url1 = f'http://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpengResultListInfoCnstwkPreparPcDetail?inqryDiv=2&bidNtceNo={gongo_nm}&bidNtceOrd=00&pageNo=1&numOfRows=15&type=json&ServiceKey={service_key}'
        res1 = requests.get(url1, headers=headers)
        if res1.status_code != 200:
            raise Exception(f"API 호출 실패 (복수예가): HTTP {res1.status_code}")
        data1 = json.loads(res1.text)
        if 'response' not in data1 or 'body' not in data1['response'] or 'items' not in data1['response']['body'] or not data1['response']['body']['items']:
            raise ValueError(f"복수예가 데이터 없음")
        df1 = pd.json_normalize(data1['response']['body']['items'])
        df1 = df1[['bssamt', 'bsisPlnprc']].astype('float')
        df1['SA_rate'] = df1['bsisPlnprc'] / df1['bssamt'] * 100
        base_price = df1.iloc[1]['bssamt']

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
        df2 = pd.json_normalize(data2['response']['body']['items'])
        sucsfbidLwltRate = float(df2.loc[0, 'sucsfbidLwltRate'])

        # ▶ A값 계산
        url3 = f'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwkBsisAmount?inqryDiv=2&bidNtceNo={gongo_nm}&pageNo=1&numOfRows=10&type=json&ServiceKey={service_key}'
        res3 = requests.get(url3, headers=headers)
        if res3.status_code != 200:
            raise Exception(f"API 호출 실패 (A값): HTTP {res3.status_code}")
        data3 = json.loads(res3.text)
        if 'response' not in data3 or 'body' not in data3['response'] or 'items' not in data3['response']['body'] or not data3['response']['body']['items']:
            raise ValueError(f"A값 데이터 없음")
        df3 = pd.json_normalize(data3['response']['body']['items'])
        cost_cols = ['sftyMngcst','sftyChckMngcst','rtrfundNon','mrfnHealthInsrprm','npnInsrprm','odsnLngtrmrcprInsrprm','qltyMngcst']
        valid_cost_cols = [col for col in cost_cols if col in df3.columns]
        if not valid_cost_cols:
            A_value = 0
        else:
            A_value = df3[valid_cost_cols].apply(pd.to_numeric, errors='coerce').fillna(0).sum(axis=1).iloc[0]

        # ▶ 개찰결과 (여기서 맨 첫 번째 업체가 1순위)
        url4 = f'http://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpengResultListInfoOpengCompt?serviceKey={service_key}&pageNo=1&numOfRows=999&bidNtceNo={gongo_nm}'
        res4 = requests.get(url4, headers=headers)
        if res4.status_code != 200:
            raise Exception(f"API 호출 실패 (개찰결과): HTTP {res4.status_code}")
        data4 = json.loads(json.dumps(xmltodict.parse(res4.text)))
        
        if 'response' not in data4 or 'body' not in data4['response'] or 'items' not in data4['response']['body'] or 'item' not in data4['response']['body']['items']:
            df4 = pd.DataFrame()
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
                df4['rate'] = (((df4['bidprcAmt'] - A_value) * 100 / sucsfbidLwltRate) + A_value) * 100 / base_price
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

        df_combined_gongo = pd.concat([
            df_rates[['rate']].assign(업체명=df_rates['조합순번'].astype(str)), 
            df4.rename(columns={'업체명': '업체명'})
        ], ignore_index=True).sort_values('rate').reset_index(drop=True)
        df_combined_gongo['rate'] = round(df_combined_gongo['rate'], 5)
        
        df_combined_gongo['공고번호'] = gongo_nm 

        # 강조 컬럼: 이제 텍스트 강조 기호는 사용하지 않습니다. 순수한 업체명만 저장합니다.
        df_combined_gongo['강조_업체명'] = df_combined_gongo['업체명'] # Styler로만 색상 강조

        return df_combined_gongo, None, top_bidder_info 

    except ValueError as ve:
        return pd.DataFrame(), f"⚠️ 경고: 공고번호 {gongo_nm} - {ve}", top_bidder_info
    except Exception as e:
        return pd.DataFrame(), f"❌ 오류 발생: 공고번호 {gongo_nm} - {e}", top_bidder_info

if st.button("분석 시작") and gongo_nums_input:
    gongo_nums = [gn.strip() for gn in gongo_nums_input.split('\n') if gn.strip()]

    if not (1 <= len(gongo_nums) <= 10):
        st.error("⚠️ 공고번호는 1개에서 10개까지만 입력 가능합니다.")
    else:
        results_by_gongo = []
        errors = []

        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, gongo_nm in enumerate(gongo_nums):
            status_text.text(f"📊 공고번호 {gongo_nm} 분석 중... ({i+1}/{len(gongo_nums)})")
            df_result, error_msg, top_bidder_info = analyze_gongo(gongo_nm)
            
            if error_msg:
                errors.append(error_msg)
            if not df_result.empty:
                results_by_gongo.append({
                    "gongo_num": gongo_nm,
                    "df": df_result,
                    "top_bidder": top_bidder_info
                })
            progress_bar.progress((i + 1) / len(gongo_nums))

        status_text.empty()
        progress_bar.empty()

        st.markdown("---") 

        # --- 각 공고별 결과 분리 및 가로 배열 (기존 유지) ---
        if results_by_gongo:
            st.subheader("📈 각 공고별 사정율 분석 결과")
            
            num_cols_per_row = 2 
            
            for i in range(0, len(results_by_gongo), num_cols_per_row):
                cols = st.columns(num_cols_per_row) 
                
                for j, result_data in enumerate(results_by_gongo[i : i + num_cols_per_row]):
                    with cols[j]: 
                        gongo_num = result_data["gongo_num"]
                        df = result_data["df"]
                        top_bidder = result_data["top_bidder"]

                        if top_bidder["name"] != "개찰 결과 없음":
                            st.markdown(f"**공고번호 {gongo_num}**: **{top_bidder['name']}** (사정율: **{top_bidder['rate']}%**)")
                        else:
                            st.markdown(f"**공고번호 {gongo_num}**: 개찰 결과 정보 없음")
                        
                        # 각 공고별 테이블 강조 함수 (텍스트 강조 기호 제거 반영)
                        def highlight_top_bidder_individual(row, top_bidder_name):
                            color = 'background-color: yellow'
                            if pd.notna(row['강조_업체명']) and row['강조_업체명'] == top_bidder_name:
                                return [color] * len(row)
                            return [''] * len(row)

                        # '강조_업체명'에는 이제 순수 업체명이 들어가므로 top_bidder['name']과 직접 비교
                        display_df_styled = df[['rate', '강조_업체명']].style.apply(
                            lambda row: highlight_top_bidder_individual(row, top_bidder['name']), axis=1
                        )

                        st.dataframe(
                            display_df_styled,
                            use_container_width=True,
                            hide_index=True,
                            height=min(35 * len(df) + 38, 400) 
                        )
                        st.markdown("---") 

            # --- 통합 사정율 분석 결과 (새로운 형식) 섹션 ---
            st.markdown("---") 
            st.subheader("📊 통합 사정율 분석 결과") 

            merged_df = pd.DataFrame()
            top_bidder_info_for_header = {} 

            if results_by_gongo:
                all_rates = pd.concat([res['df']['rate'] for res in results_by_gongo], ignore_index=True).unique()
                base_rates_df = pd.DataFrame({'rate': all_rates}).sort_values('rate').reset_index(drop=True)
                merged_df = base_rates_df
            
            for i, result_data in enumerate(results_by_gongo):
                gongo_num = result_data["gongo_num"]
                df_current_gongo = result_data["df"].copy()
                top_bidder = result_data["top_bidder"]
                
                df_for_merge = df_current_gongo[['rate', '강조_업체명']].copy()
                # 컬럼명을 공고번호로 설정 (실제 DataFrame 컬럼명)
                df_for_merge.rename(columns={'강조_업체명': f'{gongo_num}'}, inplace=True) 
                
                merged_df = pd.merge(merged_df, df_for_merge, on='rate', how='outer')
                
                # top_bidder_info_for_header 딕셔너리에 공고번호를 키로 1순위 정보 저장
                top_bidder_info_for_header[gongo_num] = top_bidder 

            if not merged_df.empty:
                final_merged_df = merged_df.sort_values(by='rate').reset_index(drop=True)
                
                # --- st.dataframe의 column_config를 사용하여 헤더에 1순위 정보 표시 ---
                column_config_dict = {"rate": "Rate"} # 'rate' 컬럼은 그대로

                for gongo_num_col in gongo_nums:
                    top_info = top_bidder_info_for_header.get(gongo_num_col, {"name": "정보 없음", "rate": "N/A"})
                    
                    # label은 마크다운 형식으로 변경. <br> 태그 대신 \n을 사용합니다.
                    # CSS의 white-space: pre-wrap; 이 \n을 인식하여 줄바꿈합니다.
                    header_text = f"**{gongo_num_col}**\n" # 공고번호는 항상 표시
                    if top_info["name"] != "개찰 결과 없음":
                        header_text += f"*{top_info['name']}*\n(사정율: {top_info['rate']:.5f}%)"
                    else:
                        header_text += "개찰 결과 없음"
                    
                    column_config_dict[gongo_num_col] = st.column_config.TextColumn(
                        label=header_text, 
                        width="small" 
                    )
                
                # Styler 함수 (통합 테이블용) - 현재 처리 중인 컬럼의 1순위 업체명만 강조
                def highlight_top_bidder_in_merged_table(s, top_bidder_info_map):
                    current_gongo_num_raw = s.name 

                    top_info = top_bidder_info_map.get(current_gongo_num_raw) 

                    if top_info and top_info['name'] != "정보 없음" and top_info['name'] != "개찰 결과 없음":
                        top_bidder_name_raw = top_info['name']
                        return ['background-color: yellow' if pd.notna(val) and val == top_bidder_name_raw else '' for val in s]
                    return [''] * len(s) 

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


            # --- 전체 결과 다운로드 (기존 유지) ---
            st.subheader("📥 전체 결과 다운로드")
            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"통합_사정율분석_{now}.xlsx"
            
            all_results_df_for_download = pd.concat([res["df"] for res in results_by_gongo], ignore_index=True)
            download_df = all_results_df_for_download.copy()
            download_df['업체명'] = download_df['강조_업체명'] 
            download_df = download_df[['공고번호', 'rate', '업체명']] 
            download_df.to_excel(filename, index=False)
            with open(filename, "rb") as f:
                st.download_button("엑셀 다운로드", f, file_name=filename)

        else:
            st.warning("분석할 유효한 공고번호가 없거나 모든 공고번호에서 오류가 발생했습니다.")

        if errors:
            st.subheader("⚠️ 분석 중 발생한 경고 및 오류:")
            for err in errors:
                st.write(err)
        elif not results_by_gongo and not errors and gongo_nums_input.strip():
             st.info("입력된 공고번호에 대한 분석 결과가 없습니다. 공고번호를 다시 확인해주세요.")