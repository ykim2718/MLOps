"""test_dp.py — data preparation (test)

input : test raw parquet
output: test transformed parquet
"""
import os


def run(in_path="data/raw/test.parquet",
        out_path="data/interim/test_transformed.parquet"):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    # TODO: train_dp 와 동일한 정제 로직 적용
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"transformed-from:{in_path}\n")
    print(f"[test_dp] {in_path} -> {out_path}")
    return out_path


if __name__ == "__main__":
    run()
