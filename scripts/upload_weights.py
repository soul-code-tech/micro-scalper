#!/usr/bin/env python3
import os, shutil, subprocess, time

WEIGHTS_DIR = "weights"
BRANCH = "weights"
REMOTE = f"https://x-access-token:{os.getenv('GITHUB_TOKEN')}@github.com/${{ github.repository }}.git"

def run(cmd):
    print(">>>", cmd)
    subprocess.run(cmd, shell=True, check=True)

def main():
    if not os.path.exists(WEIGHTS_DIR):
        print("No weights to upload")
        return

    # clone weights branch into temp
    tmp = f"weights_clone_{int(time.time())}"
    run(f"git clone --branch {BRANCH} --single-branch {REMOTE} {tmp} || git clone --single-branch {REMOTE} {tmp}")
    os.chdir(tmp)

    # copy fresh weights
    for f in os.listdir(f"../{WEIGHTS_DIR}"):
        if f.endswith(".weights.h5"):
            shutil.copy(f"../{WEIGHTS_DIR}/{f}", f)

    # commit & push
    run("git config user.name 'github-actions[bot]'")
    run("git config user.email '41898282+github-actions[bot]@users.noreply.github.com'")
    run("git add .")
    run("git diff --cached --quiet || git commit -m '🤖 Retrain weights'")
    run("git push origin weights")

    os.chdir("..")
    shutil.rmtree(tmp)

if __name__ == "__main__":
    main()
