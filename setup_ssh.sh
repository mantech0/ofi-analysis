#!/bin/bash
sudo sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
sudo systemctl restart ssh
echo "=== SSH パスワード認証を有効化しました ==="
grep PasswordAuthentication /etc/ssh/sshd_config
