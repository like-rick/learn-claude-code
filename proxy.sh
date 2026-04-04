#!/bin/bash
# proxy.sh

export http_proxy=http://127.0.0.1:10808
export https_proxy=http://127.0.0.1:10808

echo "🚀 当前 Shell 代理已开启"
echo "http_proxy: $http_proxy"
echo "尝试连接 GitHub..."

# 顺便测试一下连接
curl -I -m 5 https://github.com > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✅ 代理连接成功！"
else
    echo "❌ 代理连接失败，请检查 10808 端口是否开启。"
fi