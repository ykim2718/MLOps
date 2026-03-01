/*
 * mongodb_access.js
 * Updated to ES Modules & Async/Await (2026 Standard)
 cmd>> docker exec -it mongo_api_docker-mongo_api0 node api/mongodb_access.js
 cmd>> docker exec -it mongo_api_docker-mongo_api-1 npm run dev
 bash>> node api/mongo_rest_api.js
 bash>> npm run dev
 */

import { MongoClient } from 'mongodb';

// Docker 컨테이너에서 로컬 MongoDB에 접속하기 위한 주소
const url = process.env.MONGO_URI || 'mongodb://host.docker.internal:3000';
const dbName = 'yControl'; // mongo_rest_api.js와 데이터베이스 이름을 맞춤
const collectionName = 'project_log'; // mongo_rest_api.js에서 사용하는 컬렉션 이름

async function run() {
    const client = new MongoClient(url);

    try {
        // 데이터베이스 연결
        await client.connect();
        console.log('Successfully connected to MongoDB');

        const db = client.db(dbName);
        const collection = db.collection(collectionName); // 테스트를 위해 project_log 컬렉션 접근

        // 최신 문서 1개 찾아오기 (find는 커서를 반환하므로 toArray()나 next() 필요)
        const doc = await collection.find({})
            .sort({ _id: -1 })
            .limit(1)
            .toArray();

        console.log('Latest Document:', doc);

    } catch (err) {
        console.error('Connection error:', err);
    } finally {
        // 연결 종료
        await client.close();
        process.exit(0);
    }
}

run();