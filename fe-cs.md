# 🗺️ Feature Engineering (FE) — Cross-sectional

> 행끼리 독립 (i.i.d.) 인 정형 데이터 기준 — 한 시점의 snapshot 처럼 행 순서가 정보가 아니다.

```text
Feature Engineering (FE)
│
├─ 1. Preprocessing & Cleaning        # tidy up before learning
│   ├─ Imputation                     # 결측치 처리
│   │   ├─ Deletion                   # 행/열 제거
│   │   ├─ Mean / Median / Mode       # 대표값 대체
│   │   └─ Model-based                # 모델 기반 예측 대체
│   ├─ Outlier Handling               # 이상치 처리
│   │   ├─ Trimming                   # 삭제
│   │   ├─ Winsorization              # 상하한 클리핑
│   │   └─ Log transform              # 로그 변환
│   └─ Feature Scaling                # 스케일링
│       ├─ Min-Max
│       ├─ Standardization (Z-Score)
│       └─ Robust
│
├─ 2. Transformation                  # reshape for clearer patterns
│   ├─ Encoding                       # 범주형 → 수치형
│   │   ├─ One-Hot
│   │   ├─ Label
│   │   └─ Target
│   ├─ Discretization / Binning       # 연속형 → 구간 범주화
│   │   ├─ Equal-width                # 등간격
│   │   └─ Equal-frequency            # 등빈도
│   └─ Mathematical Transform         # 비대칭 분포 → 정규분포 근사
│       ├─ Log
│       ├─ Square Root
│       └─ Box-Cox
│
├─ 3. Generation / Construction       # build new, richer variables
│   ├─ Domain-Specific                # 도메인 특성 반영
│   ├─ Interaction                    # 변수 조합 (예: BMI = 체중 ÷ 키²)
│   └─ Aggregation                    # 그룹별 통계량
│
└─ 4. Reduction / Selection           # shrink dimension, fight overfit
    ├─ Feature Selection              # 원본 유지, 중요 변수 선별
    │   ├─ Filter
    │   ├─ Wrapper
    │   └─ Embedded
    └─ Feature Extraction             # 저차원 잠재 공간 투영
        ├─ PCA
        ├─ LDA
        └─ Autoencoder                # Representation Learning 과 잇닿음
```

---

## 1. Feature Preprocessing & Cleaning (전처리·정제)

- **Imputation (결측치 처리)**: 제거 (Deletion), 대표값 대체 (Mean / Median / Mode), 모델 기반 예측 대체
- **Outlier Handling (이상치 처리)**: Trimming (삭제), Winsorization (상하한 클리핑), 로그 변환
- **Feature Scaling (스케일링)**: Min-Max Scaling, Standardization (Z-Score), Robust Scaling

## 2. Feature Transformation (특징 변환)

- **Encoding (인코딩)**: 범주형 → 수치형 변환 (One-Hot, Label, Target)
- **Discretization / Binning (이산화)**: 연속형 변수를 구간으로 나눠 범주화 (등간격, 등빈도)
- **Mathematical Transformation (수학적 변환)**: 왜도 (Skewness) 높은 비대칭 분포를 정규분포에 가깝게 (Log, Square Root, Box-Cox)

## 3. Feature Generation / Construction (특징 생성)

- **Domain-Specific Generation**: 도메인 특성 반영 (시계열 이동 평균, 센서 데이터 주파수 성분 변환)
- **Interaction Features (상호작용 변수)**: 둘 이상의 변수를 조합해 관계성 극대화 (예: BMI = 체중 ÷ 키²)
- **Aggregation Features (집계 변수)**: 그룹별 통계량 (사용자별 월평균 구매액, 최대 접속 횟수)

## 4. Feature Reduction / Selection (특징 축소·선택)

- **Feature Selection (선택)**: 원본 특성을 유지한 채 중요 변수만 선별 (Filter, Wrapper, Embedded)
- **Feature Extraction (추출)**: 고차원을 저차원 잠재 변수 (Latent Variable) 공간으로 투영 (PCA, LDA, Autoencoder)
