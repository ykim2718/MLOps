"""download_data.py - fetch the PHM 2016 CMP data set into ./data (no account needed).

The official 2016 PHM Data Challenge sources are all gone now (the CFP Dropbox link
serves a JS page, and phmsociety.org migrated so its file links 404). The data set is
not on Kaggle either. The one reliable, token-free source left is the Internet
Archive's Wayback Machine, which captured the full zip - that is the default here.

Usage:
    python download_data.py                  # download + unzip the CMP data set into ./data
    python download_data.py --url <zip-url>   # use a different zip URL (e.g. your own mirror)
    python download_data.py --keep-zip        # keep the downloaded archive

Expected files after a successful run (in ./data):
    CMP-training-001.csv ... CMP-training-184.csv   # 25 columns, WITH header row
    CMP-training-removalrate.csv                     # WAFER_ID, STAGE, AVG_REMOVAL_RATE (target)
    CMP-test-000.csv ...                             # 25 columns, target withheld
    CMP-test-removalrate.csv                         # submission template (AVG_REMOVAL_RATE = '?')
"""
import argparse
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

# Full snapshot of the official "2016 PHM DATA CHALLENGE CMP DATA SET.zip" (~9.4 MB).
# The 'id_' marker returns the original bytes (not the Wayback HTML wrapper).
DEFAULT_URL = (
    "https://web.archive.org/web/20200727094500id_/"
    "https://www.phmsociety.org/sites/phmsociety.org/files/"
    "2016%20PHM%20DATA%20CHALLENGE%20CMP%20DATA%20SET.zip")
# Official held-out test answers (released after the competition) - used to score the
# test set. The zip holds orig_CMP-test-removalrate.csv; we save it as CMP-test-answers.csv.
ANSWERS_URL = (
    "https://web.archive.org/web/20200727104606id_/"
    "https://www.phmsociety.org/sites/phmsociety.org/files/PHM16TestValidationAnswers.zip")


def _download(url, dest, min_size=1_000_000):
    print(f"downloading {url}\n  -> {dest}")
    req = urllib.request.Request(url, headers={"User-Agent": "phm-cmp-fetch/1.0"})
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:   # noqa: S310 (fixed, vetted URL)
        f.write(r.read())
    size = dest.stat().st_size
    print(f"  downloaded {size:,} bytes")
    if size < min_size:
        sys.exit(f"download looks truncated (<{min_size:,} bytes). "
                 "Try again or pass --url for another mirror.")


def _unzip(zip_path):
    print(f"unzipping {zip_path.name}")
    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
        if bad is not None:
            sys.exit(f"archive is corrupt at {bad}. Re-run to download again.")
        z.extractall(DATA)


def _flatten():
    """The archive nests CSVs under .../CMP-data/{training,test}/ - lift them into ./data."""
    moved = 0
    for src in DATA.rglob("CMP-*.csv"):
        dst = DATA / src.name
        if src.resolve() != dst.resolve():
            src.replace(dst)
            moved += 1
    # drop now-empty extracted directories
    for d in sorted(DATA.rglob("*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return moved


def _download_answers():
    """Fetch the official test answers and save as data/CMP-test-answers.csv (best-effort)."""
    tmp = DATA / "_answers.zip"
    try:
        _download(ANSWERS_URL, tmp, min_size=2_000)              # answers zip is ~9 KB
        with zipfile.ZipFile(tmp) as z:
            z.extractall(DATA)
    except Exception as e:                                       # answers are optional - flow still runs
        print(f"  (answers download skipped: {e})")
        return False
    finally:
        tmp.unlink(missing_ok=True)
    src = next((p for p in DATA.rglob("orig_CMP-test-removalrate.csv")
                if "__MACOSX" not in str(p)), None)
    if src:
        src.replace(DATA / "CMP-test-answers.csv")
    shutil.rmtree(DATA / "PHM16TestValidationAnswers", ignore_errors=True)   # leftover validation csv
    shutil.rmtree(DATA / "__MACOSX", ignore_errors=True)                     # mac zip cruft
    return (DATA / "CMP-test-answers.csv").exists()


def _report():
    train = sorted(DATA.glob("CMP-training-[0-9]*.csv"))
    test = sorted(DATA.glob("CMP-test-[0-9]*.csv"))
    rate = DATA / "CMP-training-removalrate.csv"
    print(f"\ndata ready in {DATA}")
    print(f"  training trajectory files: {len(train)}")
    print(f"  test trajectory files:     {len(test)}")
    print(f"  removal-rate (target):     {'present' if rate.exists() else 'MISSING'}")
    if not train or not rate.exists():
        print("\nwarning: expected CMP-training-*.csv and CMP-training-removalrate.csv not found - "
              "inspect ./data.")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", type=str, default=DEFAULT_URL, metavar="ZIP_URL",
                   help="zip URL to download (default: Wayback Machine copy)")
    p.add_argument("--keep-zip", action="store_true", help="keep the downloaded archive")
    a = p.parse_args(argv)

    DATA.mkdir(parents=True, exist_ok=True)
    zip_path = DATA / "_cmp_data.zip"
    _download(a.url, zip_path)
    _unzip(zip_path)
    moved = _flatten()
    if not a.keep_zip:
        zip_path.unlink(missing_ok=True)
    print(f"flattened {moved} csv files into ./data")
    got_answers = _download_answers()
    print(f"test answers: {'present' if got_answers else 'unavailable'}")
    _report()


if __name__ == "__main__":
    main()
