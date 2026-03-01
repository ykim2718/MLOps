import express from 'express';
import { MongoClient } from 'mongodb';
import qs from 'qs';
import dotenv from 'dotenv';
import cors from 'cors';

dotenv.config();

const app = express();

// 환경 변수 설정
const MONGO_URI = process.env.MONGO_URI || 'mongodb://host.docker.internal:27017/yControl';
const PORT = process.env.PORT || 3000;

// 허용된 컬렉션 목록 설정
const rawCollections = process.env.ALLOWED_COLLECTIONS || 'log';
const ALLOWED_COLLECTIONS = rawCollections.split(',').map(item => item.trim());

app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.set('query parser', (str) => qs.parse(str, { allowDots: true }));  // Express의 쿼리 파서를 qs로 교체


// --- 미들웨어: Read-Only 설정 ---
app.use((req, res, next) => {
  // GET 요청이 아닌 모든 요청(POST, PUT, DELETE 등)을 차단합니다.
  if (req.method !== 'GET') {
    console.log(`[Blocked] ${req.method} request to ${req.url}`);
    return res.status(405).json({ 
      error: 'Method Not Allowed', 
      message: 'This API is in Read-Only mode. Only GET requests are allowed.' 
    });
  }
  next(); 
});


// MongoDB 연결
const client = new MongoClient(MONGO_URI);
let db;

async function startServer() {
  try {
    // 1️⃣ DB 먼저 연결
    await client.connect();
    
    // 2️⃣ URI에서 DB명 가져와서 db 변수에 할당
    const connectedDbName = client.options.dbName || 'yControl';
    db = client.db(connectedDbName);
    
    console.log(`✅ MongoDB Connected: ${connectedDbName}`);

    // 3️⃣ DB 연결이 성공한 '후에' 서버 실행
    app.listen(PORT, () => {
      console.log(`🚀 API Server running on port ${PORT}`);
      console.log(`🔒 Allowed Collections: ${ALLOWED_COLLECTIONS.join(', ')}`);
      console.log(`🛡️ Mode: Read-Only (GET Only)`);
    });

  } catch (err) {
    console.error('❌ Failed to start server:', err);
    process.exit(1); // 연결 실패 시 프로세스 종료
  }
}
startServer();


// 숫자 형변환 유틸리티
const autoConvert = (obj) => {
  const newObj = {};
  for (let key in obj) {
    const value = obj[key];
    if (typeof value === 'object' && value !== null) {
      newObj[key] = autoConvert(value);
    } else {
      // 숫자 형태의 문자열이면 숫자로, 아니면 그대로 유지
      newObj[key] = (!isNaN(value) && value.trim() !== "") ? Number(value) : value;
    }
  }
  return newObj;
};


// --- API 라우트 ---
app.get('/api/:collectionName', async (req, res) => {
  try {
    const { collectionName } = req.params;

    // 1. [보안] 허용된 컬렉션인지 검사
    if (!ALLOWED_COLLECTIONS.includes(collectionName)) {
      console.warn(`[Access Denied] ${collectionName}`);
      return res.status(403).json({ 
        error: "Forbidden", 
        message: "접근 권한이 없는 컬렉션입니다." 
      });
    }

    // 2. 쿼리 파싱 및 숫자 변환
    const query = autoConvert(req.query);

    // 3. 데이터 조회 (Native Driver 사용으로 _id string 쿼리 완벽 지원)
    const result = await db.collection(collectionName)
      .find(query)
      .sort({ _id: -1 }) // 가장 최근 데이터 순
      .limit(1)          // 마지막 하나만 리턴
      .toArray();

    res.json({
      collection: collectionName,
      query_applied: query,
      count: result.length,
      data: result
    });

  } catch (err) {
    res.status(500).json({ error: "Server Error", details: err.message });
  }
});

