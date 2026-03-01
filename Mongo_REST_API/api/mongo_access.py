import os
import requests
import json
# from bson.objectid import ObjectId  # 👈 ObjectId 변환을 위해 임포트

# 1. API 주소 설정 (Node.js 서버 주소)
port_number = os.getenv("api_port", "3000")  # .env에서 port 값을 가져오거나 기본값 3000 사용
collection_name = os.getenv("collection_name", "log")  # .env에서 collection_name 값을 가져오거나 기본값 사용
API_URL = f"http://localhost:{port_number}/api/{collection_name}"

def get_data():
    try:
        # 1. 쿼리 조건 설정
        query_params = {
            # "aggregate": json.dumps([{"$match": {"_id": "arbiter"}},]),
            "find": json.dumps({'_id': 'control'})
        }

        print(f"🔗 API 서버에 접속 중: {API_URL=}")
        print(f"🔍 적용 필터: {query_params=}")
        
        # 2. params 인자에 딕셔너리를 전달 (requests가 자동으로 URL 뒤에 붙여줌)
        response = requests.get(API_URL, params=query_params)
        
        # 3. 응답 결과 확인
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 데이터 가져오기 성공!: {json.dumps(result, indent=2)})")
            if False:
                for item in result['data']:
                    print(item)
        elif response.status_code == 403:
            print("❌ 오류: 허용되지 않은 컬렉션입니다 (ALLOWED_COLLECTIONS 확인 필요)")
        else:
            print(f"❌ 서버 오류: {response.status_code=}")
            print(f"❌ 오류 상세: {response.text=}")
            
    except requests.exceptions.ConnectionError:
        print("❌ 연결 실패: Node.js 서버(Docker)가 실행 중인지 확인하세요.")

if __name__ == "__main__":
    get_data()