# 🗺️ Feature Engineering (FE) — Sequence

순서형은 행 단위로 독립이 아니라 **시간 순서가 곧 정보**다. 과거 값을 끌어와 변수로 굳히는 방식이 핵심이다.

## Univariate Time Series (UTS)

한 변수 한 계열 기준의 기본 시계열 FE.

```text
Time Series FE
│
├─ Lag Features                       # 과거 값을 당겨오기
│   └─ y(t-1), y(t-7), y(t-30) …      # 어제·지난주·지난달
│
├─ Window / Rolling Statistics        # 구간 통계로 추세 훑기
│   ├─ Rolling mean / std / min / max
│   ├─ Expanding window               # 시작부터 누적
│   └─ EWMA                           # 최근에 가중
│
├─ Datetime Decomposition             # 달력 성분 펼치기
│   ├─ year / month / day / hour
│   ├─ dayofweek / weekofyear
│   ├─ is_weekend / is_holiday
│   └─ Cyclical encoding (sin/cos)    # 주기성 인코딩 (23시→0시 연결)
│
├─ Differencing / Trend               # 추세·계절성 분리
│   ├─ Diff: y(t) − y(t-1)            # 차분으로 정상화
│   └─ STL decomposition              # trend + seasonal + residual
│
├─ Frequency Domain                   # 주파수 성분
│   └─ FFT / Fourier terms            # 주기 패턴 추출
│
└─ Event-based                        # 사건 기준 거리
    ├─ Time since last event
    └─ Time until next event
```

## 주요 기법

- **Lag Features (시차 변수)**: 과거 시점 값을 변수로 (`y(t-1)`, `y(t-7)`). 자기상관이 강한 데이터의 출발점
- **Rolling / Window Statistics (이동 통계)**: 최근 N 구간의 평균·표준편차·최댓값 등으로 단기 추세와 변동성을 담음. 누적은 Expanding, 최근 가중은 EWMA
- **Datetime Decomposition (시간 성분 분해)**: 연·월·일·시·요일·주말·공휴일 추출. 시각·각도처럼 순환하는 값은 sin/cos 로 인코딩해 23시와 0시가 이어지게 함
- **Differencing (차분)**: `y(t) − y(t-1)` 로 추세를 걷어내 정상성 (stationarity) 확보. STL 로 trend·seasonal·residual 분리
- **Frequency Domain (주파수 변환)**: FFT·Fourier 항으로 숨은 주기 패턴을 변수화 (센서·신호 데이터에 유효)
- **Event-based (사건 기준)**: 마지막 사건 이후 경과 시간, 다음 사건까지 남은 시간

> ⚠️ **주의**: 시계열 FE 는 **미래 정보 누수 (data leakage)** 를 막는 게 관건이다. Lag·Rolling 은 반드시 과거 방향으로만 계산하고, train/test 분할은 시간 순서를 지켜 (시점 이후를 test 로) 둔다.

---

## Multivariate Time Series (MTS) — 반도체 웨이퍼 예 (W × J × K)

위 기법은 한 변수 (univariate) 기준이다. 실제 현장 데이터는 흔히 **3겹 계층 시계열**이다. 반도체 FDC (Fault Detection & Classification) 를 예로 들면:

```text
데이터 구조  x[w, j, t]
├─ W  wafers      # 시간 순서로 흐름 (run-to-run)  ← slow time axis
├─ J  sensors     # 웨이퍼마다 센서 J개            ← multi-variate
└─ K  trace steps # 센서마다 길이 K 시계열 trace   ← fast time axis
```

- **Multi-variate** = 웨이퍼 안에 센서가 J 개 (온도·압력·RF power·gas flow …)
- **Multi-scale** = 시간축이 두 겹 — 웨이퍼 *안*의 빠른 trace (K) 와 웨이퍼 *간*의 느린 흐름 (W)

FE 는 **안쪽부터 바깥쪽으로** 세 레벨을 쌓는다. trace 를 접고 (L1), 센서를 엮고 (L2), 웨이퍼 순서를 본다 (L3).

```text
MTS FE  (W wafers × J sensors × K steps)
│
├─ L1. Trace-level                    # 한 센서의 K-길이 trace 요약 → K 압축
│   ├─ Summary: mean / std / min / max / range
│   ├─ Shape: slope · AUC · time-to-peak
│   ├─ Transient: overshoot · settling time   # 과도·정착 특성
│   └─ Step-wise: recipe step 구간별 통계
│
├─ L2. Cross-sensor                   # 한 웨이퍼 안 J개 센서 간 (multi-variate)
│   ├─ Sensor-pair corr / cov
│   ├─ Spread / ratio                 # 센서 간 차·비
│   ├─ Lead-lag                       # 어느 센서가 먼저 반응하나
│   └─ Wafer PCA / health index       # J채널 압축, 종합 지표
│
├─ L3. Cross-wafer                    # 웨이퍼 시간순서 W축 (run-to-run)
│   ├─ Lag: 직전 웨이퍼(들) 요약값
│   ├─ Rolling / EWMA over wafers     # tool drift 추적
│   ├─ By chamber / lot aggregation
│   └─ Diff vs golden wafer / baseline
│
└─ Multi-scale (두 겹 시간축)
    ├─ Intra-wafer: step 분할 · wavelet on trace   # fast scale (K)
    └─ Inter-wafer: wafer · lot · long-term drift   # slow scale (W)
```

### L1. Trace-level (센서 trace 요약, K 압축)

각 `(wafer, sensor)` 의 길이 K trace 를 소수 변수로 접는다. MTS FE 의 출발점이자 가장 큰 차원 절감이 일어나는 곳.

- **요약 통계**: mean · std · min · max · range
- **모양 (shape)**: 기울기 (slope), 곡선 아래 면적 (AUC), 피크 도달 시간
- **과도 특성**: overshoot, settling time — 설정값에 얼마나 빨리·매끈하게 안착하나
- **step 구간별**: 한 trace 안에서도 recipe step 마다 따로 요약 (단계별 거동이 다름)

### L2. Cross-sensor (웨이퍼 내 J 센서 간)

같은 웨이퍼에서 센서들이 **어떻게 함께 움직였나**. L1 요약 또는 trace 끼리 직접 비교.

- 센서쌍 상관·공분산, spread (`A − B`)·ratio (`A / B`)
- lead-lag 로 선후 관계 (예: RF power 가 오르면 온도가 뒤따름)
- 웨이퍼 단위 PCA 로 J 채널을 소수 성분으로 압축, 잔차 기반 종합 health index

### L3. Cross-wafer (웨이퍼 시간순서)

**여기서 웨이퍼 순서가 정보가 된다.** 앞의 univariate·시계열 기법을 "웨이퍼 = 한 시점"으로 보고 그대로 적용 — run-to-run 변동과 장비 drift.

- **Lag**: 직전 웨이퍼(들)의 L1/L2 요약값
- **Rolling / EWMA over wafers**: 웨이퍼 축으로 굴려 **tool drift** 추적
- **By chamber / lot**: 챔버·로트별 집계 (장비·배치 차이 반영)
- **Baseline diff**: golden wafer·정상 기준 대비 차이

### Multi-scale (두 겹)

- **Intra-wafer (빠른 결, K 축)**: trace 를 step 으로 분할하거나 wavelet 으로 거친 결–고운 결 분해
- **Inter-wafer (느린 결, W 축)**: wafer → lot → 장기 drift 를 여러 창으로 동시에

> ⚠️ **차원 폭발**: J 센서 × trace-stat 종류 × 창 수 → 변수가 곱으로 불어난다. 생성 뒤 **Feature Selection / Extraction ([fe-cs.md](fe-cs.md) 꼭지 4)** 으로 반드시 추려낸다.
>
> ⚠️ **정렬 (alignment)**: trace 길이 K 가 웨이퍼마다 다를 수 있다. step (recipe) 기준 정렬 또는 DTW·resample 로 길이를 맞춘 뒤 요약·비교한다.
>
> ⚠️ **누수 (leakage)**: L1·L2 는 웨이퍼 완성 후 *전체 trace* 를 써도 된다 (웨이퍼 단위 판정 시점 기준). 그러나 **L3 cross-wafer 는 반드시 과거 웨이퍼만** 쓰고, train/test 도 웨이퍼 시간순서로 분할한다.
