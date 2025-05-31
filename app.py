import streamlit as st
import pandas as pd
import numpy as np
import requests
import itertools
import json
import xmltodict
from datetime import datetime

st.set_page_config(layout="wide")
st.title("🏗️ 1365 사정율 분석 도구")
st.markdown("공고번호를 입력하면 복수예가 조합, 낙찰하한율, 개찰결과를 분석해 드립니다.")

# ▶ 표 폭 조절 옵션 추가 (기존 유지)
display_width = st.selectbox("📏 표 표시 너비 설정", ["자동(전체 너비)", "고정(좁게)"])
use_wide = display_width == "자동(전체 너비)"

# 사용자 입력: 여러 공고번호 입력 (줄바꿈으로 구분)
st.subheader("🔍 분석할 공고번호를 1개에서 10개까지 입력하세요 (줄바꿈으로 구분)") # 숫자 변경
gongo_nums_input = st.text_area("예시: \n20230123456\n20230123457\n...", height=200) # 높이 약간 증가

# 분석 함수 정의
@st.cache_data(ttl=3600) # 1시간 동안 API 응답 캐싱
def analyze_gongo(gongo_nm):
    """
    단일 공고번호에 대한 사정율 분석을 수행하고 결과를 반환합니다.
    반환 값: (DataFrame, 오류 메시지, 1순위 업체명, 1순위 업체 사정율)
    """
    top_bidder_info = {"name": "정보 없음", "rate": "N/A"} # 1순위 업체 정보 초기화
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        service_key = 'NXIL0ccBuaYTU1TvOY7wEfHJzR%2FqBRUCwoIIWHdw%2Bcfy3qy8tVEHktbZ5o95y8XqdW4GrQaj%2FSawwFq7gmkhfA%3D%3D' # 서비스 키는 실제 배포 시 보안에 유의하세요. 환경 변수 사용 권장.

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
        
        # 개찰 결과가 없을 경우를 대비한 처리
        if 'response' not in data4 or 'body' not in data4['response'] or 'items' not in data4['response']['body'] or 'item' not in data4['response']['body']['items']:
            df4 = pd.DataFrame()
        else:
            items = data4['response']['body']['items']['item']
            if not isinstance(items, list): # 단일 항목인 경우 리스트로 감싸기
                items = [items]
            df4 = pd.DataFrame(items)
            df4['bidprcAmt'] = pd.to_numeric(df4['bidprcAmt'], errors='coerce')
            df4 = df4.dropna(subset=['bidprcAmt'])

        if not df4.empty:
            # 1순위 업체 정보 추출 (개찰 결과가 있을 경우에만)
            top_bidder_name = df4.iloc[0]['prcbdrNm']
            
            if sucsfbidLwltRate != 0 and base_price != 0:
                df4['rate'] = (((df4['bidprcAmt'] - A_value) * 100 / sucsfbidLwltRate) + A_value) * 100 / base_price
            else:
                df4['rate'] = np.nan

            df4 = df4.drop_duplicates(subset=['rate']).copy()
            df4 = df4[(df4['rate'] >= 90) & (df4['rate'] <= 110)].copy()
            df4 = df4[['prcbdrNm', 'rate']].rename(columns={'prcbdrNm': '업체명'})

            # 1순위 업체 사정율 찾기 (개찰 결과 df4에서)
            top_bidder_rate_row = df4[df4['업체명'] == top_bidder_name]
            if not top_bidder_rate_row.empty:
                top_bidder_info = {
                    "name": top_bidder_name,
                    "rate": round(top_bidder_rate_row.iloc[0]['rate'], 5)
                }
            else: # 개찰 결과에는 있지만 사정율 범위 필터링 후 사라진 경우
                 top_bidder_info = {"name": top_bidder_name, "rate": "범위 외"}
        else:
            top_bidder_info = {"name": "개찰 결과 없음", "rate": "N/A"}


        # ▶ 사정율 + 업체명 결합
        df_combined_gongo = pd.concat([
            df_rates[['rate']].assign(업체명=df_rates['조합순번'].astype(str) + '조합'),
            df4.rename(columns={'업체명': '업체명'})
        ], ignore_index=True).sort_values('rate').reset_index(drop=True)
        df_combined_gongo['rate'] = round(df_combined_gongo['rate'], 5)

        # ▶ 강조 컬럼 추가: 1순위 업체명과 일치하면 강조 (더 눈에 띄게)
        df_combined_gongo['강조_업체명'] = df_combined_gongo['업체명'].apply(
            lambda x: f"✨ **{x}**" if x == top_bidder_info['name'] else x
        )
        
        # 공고번호 컬럼 추가
        df_combined_gongo['공고번호'] = gongo_nm
        return df_combined_gongo, None, top_bidder_info # 성공 시 데이터프레임, None, 1순위 정보 반환

    except ValueError as ve:
        return pd.DataFrame(), f"⚠️ 경고: 공고번호 {gongo_nm} - {ve}", top_bidder_info
    except Exception as e:
        return pd.DataFrame(), f"❌ 오류 발생: 공고번호 {gongo_nm} - {e}", top_bidder_info

if st.button("분석 시작") and gongo_nums_input:
    gongo_nums = [gn.strip() for gn in gongo_nums_input.split('\n') if gn.strip()]

    # 공고번호 개수 제한을 10개로 변경
    if not (1 <= len(gongo_nums) <= 10):
        st.error("⚠️ 공고번호는 1개에서 10개까지만 입력 가능합니다.")
    else:
        results = []
        errors = []
        top_bidders_summary = [] # 1순위 업체 요약 정보를 저장할 리스트

        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, gongo_nm in enumerate(gongo_nums):
            status_text.text(f"📊 공고번호 {gongo_nm} 분석 중... ({i+1}/{len(gongo_nums)})")
            df_result, error_msg, top_bidder_info = analyze_gongo(gongo_nm)
            
            if error_msg:
                errors.append(error_msg)
            if not df_result.empty:
                results.append(df_result)
            
            # 1순위 업체 정보 저장
            top_bidders_summary.append({
                "gongo_num": gongo_nm,
                "name": top_bidder_info["name"],
                "rate": top_bidder_info["rate"]
            })
            progress_bar.progress((i + 1) / len(gongo_nums))

        status_text.empty()
        progress_bar.empty()

        # --- 각 공고별 1순위 업체 정보 표시 ---
        if top_bidders_summary:
            st.subheader("🏆 공고별 1순위 업체 정보")
            for summary in top_bidders_summary:
                if summary["name"] != "개찰 결과 없음":
                    st.success(f"**공고번호 {summary['gongo_num']}**: **{summary['name']}** (사정율: **{summary['rate']}%**)")
                else:
                    st.info(f"**공고번호 {summary['gongo_num']}**: 개찰 결과 정보가 없거나 1순위 업체 정보를 가져올 수 없습니다.")
            st.markdown("---") # 구분선 추가

        # --- 통합 분석 결과 표시 ---
        if results:
            st.subheader("📈 통합 사정율 분석 결과")
            final_df = pd.concat(results, ignore_index=True)
            final_df = final_df[['공고번호', 'rate', '강조_업체명']]

            st.data_editor(
                final_df,
                use_container_width=True,
                disabled=True,
                height=600 # 여러 결과를 표시하기 위해 높이 유지
            )

            # ▶ 엑셀 다운로드 기능
            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"통합_사정율분석_{now}.xlsx"
            download_df = final_df.copy()
            download_df['업체명'] = download_df['강조_업체명'].str.replace('✨ ', '').str.replace('**', '') # 강조 표시 및 볼드체 마크다운 제거
            download_df = download_df[['공고번호', 'rate', '업체명']]
            download_df.to_excel(filename, index=False)
            with open(filename, "rb") as f:
                st.download_button("📥 결과 엑셀 다운로드", f, file_name=filename)
        else:
            st.warning("분석할 유효한 공고번호가 없거나 모든 공고번호에서 오류가 발생했습니다.")

        if errors:
            st.subheader("⚠️ 분석 중 발생한 경고 및 오류:")
            for err in errors:
                st.write(err)
        elif not results and not errors and gongo_nums_input.strip(): # 입력은 했으나 결과/오류 모두 없는 경우
             st.info("입력된 공고번호에 대한 분석 결과가 없습니다. 공고번호를 다시 확인해주세요.")