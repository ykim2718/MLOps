"""train_dp.py — data preparation (train)

input : train raw parquet
output: train transformed parquet

실제로는 pandas.read_parquet(in_path) -> 정제/결측치 처리 -> to_parquet(out_path).
여기서는 예시용으로 입력을 읽어 placeholder 산출물을 생성한다.
"""
import os


def run(in_path="data/raw/train.parquet",
        out_path="data/interim/train_transformed.parquet"):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    # TODO: 실제 정제 로직 (결측치/이상치 처리, 타입 변환 등)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"transformed-from:{in_path}\n")
    print(f"[train_dp] {in_path} -> {out_path}")
    return out_path


if __name__ == "__main__":
    run()
