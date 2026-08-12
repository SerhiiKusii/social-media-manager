#!/usr/bin/env bash
# Downloads a portable Node+npm and a static ffmpeg build into .tools/,
# entirely user-space (no sudo, no system package manager). Re-run is
# idempotent — it skips anything already present.
set -euo pipefail
cd "$(dirname "$0")/.."

NODE_VERSION="v20.17.0"
mkdir -p .tools

if [ ! -x .tools/node/bin/node ]; then
    echo "installing node ${NODE_VERSION}..."
    curl -sSL -o .tools/node.tar.xz \
        "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-x64.tar.xz"
    tar -xf .tools/node.tar.xz -C .tools
    rm .tools/node.tar.xz
    mv ".tools/node-${NODE_VERSION}-linux-x64" .tools/node
fi
.tools/node/bin/node --version
.tools/node/bin/npm --version

if [ ! -x .tools/ffmpeg/ffmpeg ]; then
    echo "installing ffmpeg (static build)..."
    curl -sSL -o .tools/ffmpeg.tar.xz \
        "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
    tar -xf .tools/ffmpeg.tar.xz -C .tools
    rm .tools/ffmpeg.tar.xz
    mv .tools/ffmpeg-*-amd64-static .tools/ffmpeg
fi
.tools/ffmpeg/ffmpeg -version | head -1
