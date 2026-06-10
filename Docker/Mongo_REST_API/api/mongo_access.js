/*
 * mongodb_access.js
 cmd>> docker exec -it mongo_api_docker-mongo_api0 node api/mongodb_access.js
 cmd>> docker exec -it mongo_api_docker-mongo_api-1 npm run dev
 bash>> node api/mongo_access.js
 bash>> npm run dev
 */

 // 별도 임포트 없이 실행 가능 (Node.js 18+)

const API_PORT = process.env.API_PORT || '3000';
const COLLECTION_NAME = process.env.COLLECTION_NAME ||'log';

async function getData() {
  // 1. URL과 쿼리 파라미터 수동 조합
  const params = new URLSearchParams({
    // find: JSON.stringify({ "_id": "control" })
    // aggregate: JSON.stringify([{ "$match": { "_id": "arbiter" } }])
    aggregate: JSON.stringify([
      {"$sort": { "time": -1 } },
      {"$limit": 2}
    ])
  });

  const url = `http://localhost:${API_PORT}/api/${COLLECTION_NAME}?${params.toString()}`;

  try {
    console.log(`🔗 API 서버에 접속 중: ${url}`);
    
    const response = await fetch(url);
    const result = await response.json();

    if (response.ok) {
      console.log("✅ 성공:", JSON.stringify(result, null, 2));
    } else {
      console.error(`❌ 오류 (${response.status}):`, result.message || result.error);
    }
  } catch (error) {
    console.error("❌ 연결 실패 또는 네트워크 오류");
  }
}

getData();