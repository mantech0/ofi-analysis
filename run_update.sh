#!/bin/bash
set -e
cd ~/ofi-analysis
[ -f .env ] && source .env
git pull origin main
source venv/bin/activate
python create_dashboard.py
git add logs/
git diff --staged --quiet || git commit -m "OFI snapshot"
git push origin main
if [ ! -d "/tmp/gh-pages" ]; then
    git worktree add /tmp/gh-pages gh-pages
fi
git -C /tmp/gh-pages pull origin gh-pages
cp -r dist/* /tmp/gh-pages/
cd /tmp/gh-pages
git add -A
git diff --staged --quiet || git commit -m "dashboard update"
git push origin gh-pages
