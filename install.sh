#!/usr/bin/env bash
# 豆瓣读书 Skill 一键安装脚本
# 自动判断国内/国外网络，国内走清华 PyPI 镜像 + npmmirror Chromium 镜像

set -e

echo "→ 检测网络环境..."

# 简单 ping 一下 pypi.org，超时则判定为国内网络
if curl -sI --max-time 3 https://pypi.org/ > /dev/null 2>&1; then
    PIP_INDEX=""
    PW_HOST=""
    echo "  ✓ 网络可直连 PyPI，使用官方源"
else
    PIP_INDEX="-i https://pypi.tuna.tsinghua.edu.cn/simple"
    PW_HOST="PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors"
    echo "  → 检测到访问受限，启用清华镜像 + npmmirror"
fi

echo ""
echo "→ 安装 Python 依赖 (playwright, beautifulsoup4)..."
eval "pip3 install $PIP_INDEX playwright beautifulsoup4"

echo ""
echo "→ 安装 Chromium 浏览器（首次较慢，约 130MB）..."
eval "$PW_HOST python3 -m playwright install chromium"

echo ""
echo "✓ 安装完成！"
echo ""
echo "试一下示例报告："
echo "  python3 $(dirname "$0")/scripts/generate_douban_report.py --sample --output /tmp/douban-sample/"
echo "  open /tmp/douban-sample/douban-report.html"
