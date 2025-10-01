#!/usr/bin/env python3
import os
import subprocess
import sys

# прокидываем переменные из окружения
os.environ["GITHUB_TOKEN"] = os.getenv("GITHUB_TOKEN", "")
os.environ["GITHUB_REPOSITORY"] = os.getenv("GITHUB_REPOSITORY", "")

if not (os.environ["GITHUB_TOKEN"] and os.environ["GITHUB_REPOSITORY"]):
    print("⚠️  GITHUB_TOKEN или GITHUB_REPOSITORY не заданы – пропускаем пуш")
    sys.exit(0)

REMOTE = f"https://x-access-token:{os.environ['GITHUB_TOKEN']}@github.com/{os.environ['GITHUB_REPOSITORY']}.git"


def run(cmd):
    print(">>>", cmd)
    subprocess.run(cmd, shell=True, check=True)


def main():
    if not os.path.exists("weights"):
        print("No weights to upload")
        return

    tmp = f"weights_clone_{os.getpid()}"
    run(f"git clone --branch weights --single-branch {REMOTE} {tmp} 2>/dev/null || git clone --single-branch {REMOTE} {tmp}")
    run(f"cp -r weights/* {tmp}/ 2>/dev/null || true")
    os.chdir(tmp)
    run("git config user.name 'github-actions[bot]'")
    run("git config user.email '41898282+github-actions[bot]@users.noreply.github.com'")
    run("git add .")
    run("git diff --cached --quiet || (git commit -m '🤖 Retrain (15m walk-forward)' && git push origin weights)")
    os.chdir("..")
    subprocess.run(["rm", "-rf", tmp])


if __name__ == "__main__":
    main()
