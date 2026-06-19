"""Read input.txt and create output.txt containing the original text and a reply."""
from pathlib import Path

BASE = Path(__file__).parent          # /app/example inside the container

source = (BASE / "input.txt").read_text(encoding="utf-8").strip()
reply = "Couldn't be better !!"

(BASE / "output.txt").write_text(f"{source}\n{reply}\n", encoding="utf-8")
print(f"Done: created output.txt.\n{source}\n{reply}")
