import express from 'express';
import mongoose from 'mongoose';
import cors from 'cors';
import qs from 'qs';  // QS Parser를 사용하여 쿼리 문자열을 객체로 변환
import dotenv from 'dotenv';

dotenv.config();

const app = express();

const MONGO_URI = process.env.MONGO_URI || 'mongodb://host.docker.internal:27017/yControl';
const PORT = process.env.PORT || 3000;
const rawCollections = process.env.ALLOWED_COLLECTIONS || 'log';
const ALLOWED_COLLECTIONS = rawCollections.split(',').map(item => item.trim());  // 쉼표로 잘라서 배열로 변환 (공백 제거 포함)

app.use(cors());
app.use(express.json());
// extended: true 설정이 있어야 URL의 [ ] 중첩 구조를 객체로 인식합니다.
app.use(express.urlencoded({ extended: true }));

// --- 미들웨어: Read-Only 설정 ---
app.use((req, res, next) => {
  // GET 요청이 아닌 모든 요청(POST, PUT, DELETE 등)을 차단합니다.
  if (req.method !== 'GET') {
    console.log(`[Blocked] ${req.method} request to ${req.url}`);
    return res.status(405).json({ 
      error: 'Method Not Allowed', 
      message: 'This API is in Read-Only mode.' 
    });
  }
  next(); // GET 요청일 경우에만 다음 로직(라우터)으로 넘어갑니다.
});
// ------------------------------------------

mongoose
  .connect(MONGO_URI)
  .then(() => console.log('MongoDB connected'))
  .catch((err) => console.error('MongoDB error:', err));


// 2. Express의 기본 쿼리 파서를 qs로 교체
// 'extended' 옵션을 사용하여 중첩된 객체($gte 등)를 완벽하게 지원합니다.
app.set('query parser', (str) => qs.parse(str, {
  allowDots: true,      // price.gte 같은 점 표기법 허용 여부
  comma: true           // tag=a,b 를 [a, b]로 변환 허용 여부
}));

app.use(express.json());

// ... (DB 연결 및 모델 설정 코드는 동일) ...

// 3. 숫자 형변환 유틸리티 (qs는 기본적으로 모두 문자열로 가져오기 때문)
const autoConvert = (obj) => {
  for (let key in obj) {
    if (typeof obj[key] === 'object' && obj[key] !== null) {
      autoConvert(obj[key]);
    } else if (!isNaN(obj[key]) && obj[key].trim() !== "") {
      obj[key] = Number(obj[key]);
    }
  }
  return obj;
};

app.get('/api/:collectionName', async (req, res) => {
  try {
    const { collectionName } = req.params;

    // ✅ DB에 접근하기 전에 허용한 collection인지 검사합니다.
    if (!ALLOWED_COLLECTIONS.includes(collectionName)) {
      console.warn(`[Access Denied] Attempted to access: ${collectionName}`);
      return res.status(403).json({ 
        error: "Forbidden", 
        message: "접근 권한이 없는 컬렉션입니다." 
      });
    }
    
    // qs에 의해 파싱된 req.query를 숫자 변환만 거쳐서 바로 사용
    const filter = autoConvert(req.query);

    const DynamicModel = mongoose.models[collectionName] || mongoose.model(
      collectionName,
      new mongoose.Schema({}, { strict: false, collection: collectionName })
    );

    const items = await DynamicModel.find(filter).sort({ _id: -1 });

    res.json({
      collection: collectionName,
      applied_filter: filter,
      data: items
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`API running on port ${PORT}`);
});