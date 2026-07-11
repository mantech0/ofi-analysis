#!/bin/bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJTHtGTzo3jyt6trgTxIRHMeNbFV9Hw/dCDOVoPDU7vH GitHubに登録したメールアドレス" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
echo "=== SSH公開鍵を登録しました ==="
cat ~/.ssh/authorized_keys
