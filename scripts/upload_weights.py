#!/usr/bin/env python3
import os, shutil, subprocess, time

WEIGHTS_DIR = "weights"
BRANCH = "weights"
# Берем токен и репозиторий из env-переменных GitHub Actions
token = os.getenv('GITHUB_TOKEN')
repo  = os.getenv('GITHUB_REPOSITORY')
if not token or not repo:
    raise RuntimeError("GITHUB_TOKEN и GITHUB_REPOSITORY должны быть заданы")

REMOTE = f"https://x-access-token:{token}@github.com/{repo}.git"

def run(cmd):
    print(">>>", cmd)
    subprocess.run(cmd, shell=True, check=True)

def main():
    if not os.path.exists(WEIGHTS_DIR):
        print("No weights to upload")
        return

    tmp = f"weights_clone_{int(time.time())}"
    # клонируем ветку weights (если есть) либо весь репо
    run(f"git clone --branch {BRANCH} --single-branch {REMOTE} {tmp} 2>/dev/null || git clone --single-branch {REMOTE} {tmp}")

    # копируем свежие веса
    for f in os.listdir(WEIGHTS_DIR):
        if f.endswith((".weights.h5", ".pkl")):
            shutil.copy(os.path.join(WEIGHTS_DIR, f), tmp)

    os.chdir(tmp)
    run("git config user.name 'github-actions[bot]'")
    run("git config user.email '41898282+github-actions[bot]@users.noreply.github.com'")
    run("git add .")
    run("git diff --cached --quiet || git commit -m '🤖 Retrain weights'")
    run("git push origin weights")
    os.chdir("..")
    shutil.rmtree(tmp)

if __name__ == "__main__":
    main()
