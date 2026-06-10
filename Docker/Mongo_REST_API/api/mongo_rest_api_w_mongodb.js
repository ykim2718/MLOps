import express from 'express';
import { MongoClient } from 'mongodb';

const app = express();

// 환경 변수 설정
const MONGO_URI = process.env.MONGO_URI || 'mongodb://host.docker.internal:27017/yControl';
const API_PORT = process.env.API_PORT || 3000;

// 허용된 컬렉션 목록 설정
const rawCollections = process.env.ALLOWED_COLLECTIONS || 'log';
const ALLOWED_COLLECTIONS = rawCollections.split(',').map(item => item.trim());

app.use(express.json());
app.use(express.urlencoded({ extended: true }));


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
    app.listen(API_PORT, () => {
      console.log(`🚀 API Server running on port ${API_PORT}`);
      console.log(`🔒 Allowed Collections: ${ALLOWED_COLLECTIONS.join(', ')}`);
      console.log(`🛡️ Mode: Read-Only (GET Only)`);
    });

  } catch (err) {
    console.error('❌ Failed to start server:', err);
    process.exit(1); // 연결 실패 시 프로세스 종료
  }
}
startServer();


// --- API 라우트 ---
app.get('/api/:collectionName', async (req, res) => {
  try {
    const { collectionName } = req.params;

    // 1. [보안] 허용된 컬렉션인지 검사
    if (!ALLOWED_COLLECTIONS.includes(collectionName)) {
      console.warn(`[Access Denied] ${collectionName}`);
      return res.status(403).json({   // 403 (Forbidden)
        error: "Forbidden", 
        message: "접근 권한이 없는 컬렉션입니다." 
      });
    }

    let result;
    let applied;

    // 2. 쿼리 파라미터 검증
    const { find, aggregate } = req.query;
    const findStr = find ? find.trim() : null;
    const aggStr = aggregate ? aggregate.trim() : null;

    if (!find && !aggregate) {
      return res.status(400).json({ 
        error: "Bad Request", 
        message: "find 또는 aggregate 파라미터가 누락되었습니다." 
      });
    }

    if (find && aggregate) {  // 둘 다 데이터가 들어온 경우 (동시 사용 불가)
      return res.status(400).json({ 
        error: "Bad Request", 
        message: "find와 aggregate는 동시에 사용할 수 없습니다. 하나만 선택해 주세요." 
      });
    }

    const rawQueryString = find || aggregate;
    const blacklistedOperators = ['$where', '$accumulator', '$function'];
    if (blacklistedOperators.some(op => rawQueryString.includes(op))) {
      console.warn(`[Security Alert] Blocked request containing: ${rawQueryString}`);
      return res.status(400).json({ error: "Forbidden operator used" });
    }

    // 3. Fetch by find or aggregate
    try {
      if (find) {
        // --- Find 모드 ---
        const query = JSON.parse(find);

        // 쿼리 객체가 비어있는지 체크 (예: {})
        if (Object.keys(query).length === 0) {
          return res.status(398).json({ error: "Bad Request", message: "find 쿼리가 비어있습니다. 필터 조건을 입력해주세요." });
        }

        console.log(`🔎 [${collectionName}] Find:`, JSON.stringify(query));
        result = await db.collection(collectionName).find(query).toArray();
        applied = query;

      } else if (aggregate) {
        // --- Aggregate 모드 ---
        const pipeline = JSON.parse(aggregate);
        const finalPipeline = Array.isArray(pipeline) ? pipeline : [pipeline];

        // 파이프라인 배열이 비어있는지 체크
        if (finalPipeline.length === 0) {
          return res.status(400).json({ error: "Bad Request", message: "aggregate 파이프라인이 비어있습니다." });
        }

        console.log(`📊 [${collectionName}] Aggregate:`, JSON.stringify(finalPipeline));
        result = await db.collection(collectionName).aggregate(finalPipeline).toArray();
        applied = finalPipeline;
      }
      console.log(`📊 [${collectionName}] result:`, result.length);

    } catch (parseErr) {
      // JSON 형식이 잘못되었거나 빈 문자열인 경우 처리
      return res.status(400).json({ 
        error: "Bad Request", 
        message: "유효하지 않은 JSON 형식이거나 빈 값입니다.",
        details: parseErr.message 
      });
    }

    // 3. 결과 응답
    res.json({
      collection: collectionName,
      type: aggregate ? 'aggregate' : 'find',
      count: result.length,
      query: applied,
      data: result
    });

  } catch (err) {
    console.error('Server Error:', err);
    res.status(500).json({ error: "Server Error", details: err.message });
  }
});

