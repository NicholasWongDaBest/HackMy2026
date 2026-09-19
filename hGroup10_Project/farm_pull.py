"""Compatibility entry point for the maintained Central validator.

python3 farm_pull.py       # one read/validate cycle; no upload
python3 farm_pull.py loop  # continuous pull; do not also run farm.sync
Use python3 -m farm.sync for the normal combined upload/download worker.
"""
import sys

from farm.sync import main


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["loop"]:
        args = ["--pull-only"]
    elif not args:
        args = ["--pull-only", "--once"]
    else:
        args = ["--pull-only"] + args
    raise SystemExit(main(args))
