#!/usr/bin/env python3
"""Refresh stale schedules before a clock-triggered notification pass."""
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    path=ROOT/'docs/fights.json'
    now=datetime.now(timezone.utc)
    try:
        generated=datetime.fromisoformat(json.loads(path.read_text())['generated'].replace('Z','+00:00'))
        fresh=now-generated<timedelta(hours=6)
    except (OSError,ValueError,KeyError):fresh=False
    if fresh:
        print('Schedule refreshed within six hours');return 0
    return subprocess.run([sys.executable,str(ROOT/'scanner/scan.py')],cwd=ROOT).returncode

if __name__=='__main__':sys.exit(main())
