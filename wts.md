# 🗺️ Wide Time Series (WTS) — Capability Map

A consolidated map of techniques for handling **wide (p≫n) time-series data**, grounded in semiconductor FDC / DOE / metrology practice.

## 1. Overview

### 1.1 Positioning
- Specialization in time-series data engineering and modeling.

### 1.2 Flagship Experience
- 400 wafers × 200 sensors × 10k time steps — a 3-way tensor (wafer × sensor × time).

### 1.3 Core Challenge
- Strategy for **wide (p≫n) data handling**: far more features than samples.

## 2. Data Handling

```text
Data Handling
├─ FDC Sensor Time-Series         # in-line process sensor traces
├─ DOE Data                       # designed experiments
│   ├─ Narrow (centering)         # dense sampling around optimum
│   └─ Wide (cliff)               # sparse across steep response boundary
├─ Marathon Test                  # long-run, long-term drift
├─ Metrology                      # physical measurement (ground truth)
└─ Data Augmentation              # domain knowledge
    └─ Process / Device physics · Circuit
```

### 2.1 FDC Sensor Time-Series Data
- Fault Detection & Classification traces from in-line process sensors.

### 2.2 DOE Data — Narrow (Centering) vs Wide (Cliff)
- **Narrow / centering**: dense sampling around an optimum.
- **Wide / cliff**: sparse sampling across steep response boundaries.

### 2.3 Marathon Test Data
- Long-run acquisition for long-term drift observation.

### 2.4 Metrology Data
- Physical measurement (dimension, thickness, electrical) as ground truth.

### 2.5 Data Augmentation — Domain Knowledge
- Augmentation driven by process / device physics and circuit knowledge.

## 3. Feature Engineering

```text
Feature Engineering
├─ Feature Construction
│   ├─ TSV / non-TSV              # vectorize trace, or keep sequence
│   ├─ DTW Alignment             # align differing length / phase
│   ├─ Domain-knowledge          # recipe · topology/zone · PVT
│   └─ Wafer Spatial Decomp.     # wafer-to-wafer · within-wafer
│
└─ Feature Reduction
    ├─ Supervised
    │   ├─ Linear        → LDA, PLS
    │   ├─ Tree-based
    │   └─ Deep          → 1D-CNN, deep embedding
    └─ Unsupervised
        ├─ Linear        → PCA
        ├─ Tree-based
        ├─ Deep          → autoencoder, deep embedding
        └─ Representation learning
```

### 3.1 Feature Construction
- **3.1.1 Time Series Vectorization (TSV) / non-TSV** — collapse traces to fixed-length vectors, or keep raw sequence form.
- **3.1.2 DTW-based Alignment** — align traces of differing length / phase via Dynamic Time Warping.
- **3.1.3 Domain-Knowledge Features** — recipe · topology / zone · PVT (process, voltage, temperature).
- **3.1.4 Wafer Spatial Decomposition** — wafer-to-wafer · within-wafer variation.

### 3.2 Feature Reduction

**3.2.1 Supervised Feature Reduction**
- Linear: LDA, PLS
- Tree-based
- Deep learning: supervised 1D-CNN, deep embedding

**3.2.2 Unsupervised Feature Reduction**
- Linear: PCA
- Tree-based
- Deep learning: autoencoder, deep embedding
- Representation learning

## 4. Modeling

```text
Modeling
├─ Tree              # wide DOE / cliff
├─ Regression        # narrow DOE / centering
├─ Hybrid            # tree + regression
├─ Ensemble          # bagging · boosting · stacking
├─ Deep Learning     # end-to-end: 1D-CNN · CNN · UNET · GAN
└─ Transfer / LLM    # pretrained transfer, small-n
```

### 4.1 Tree Models
- For wide DOE / cliff responses.

### 4.2 Regression Models
- For narrow DOE / centering responses.

### 4.3 Hybrid Models
- Tree + regression combined.

### 4.4 Ensemble
- Bagging · boosting · stacking.

### 4.5 Deep Learning
- End-to-end prediction: 1D-CNN · CNN · UNET · GAN.

### 4.6 Transfer Learning — LLM
- Pretrained-model transfer for prediction; addresses small-n regimes.
