#!/usr/bin/env bash
# Cài ffmpeg + cairo + font cho máy chạy GitHub Actions.
# 1) Thử apt nhanh (tối đa ~4 phút). 2) Nếu kho Ubuntu không vào được (lỗi mạng của GitHub, đã gặp
#    ngày 2026-11-11), lấy ffmpeg bản dựng sẵn từ GitHub và cairo từ conda-forge (Miniconda có sẵn trên máy chạy).
set -u
PKGS="ffmpeg libcairo2-dev pkg-config python3-dev fonts-dejavu-core fonts-noto-core fonts-noto-cjk"
APT="-o Acquire::Retries=2 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 -o DPkg::Lock::Timeout=60"
sudo rm -f /var/lib/man-db/auto-update

have_all() { command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null && pkg-config --exists cairo; }

if ! have_all; then
  sudo timeout 90 apt-get update -qq $APT || echo "::warning::apt update lỗi mạng"
  sudo timeout 150 apt-get install -y -qq --no-install-recommends $APT $PKGS || echo "::warning::apt install lỗi"
fi

if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "Dự phòng: tải ffmpeg dựng sẵn từ GitHub (BtbN/FFmpeg-Builds)"
  url=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz
  for i in 1 2 3; do curl -fsSL --retry 3 --max-time 300 "$url" -o /tmp/ffmpeg.tar.xz && break; sleep 10; done
  mkdir -p "$HOME/ffmpeg" && tar -xf /tmp/ffmpeg.tar.xz -C "$HOME/ffmpeg" --strip-components=1
  echo "$HOME/ffmpeg/bin" >> "$GITHUB_PATH"
  export PATH="$HOME/ffmpeg/bin:$PATH"
fi

if ! pkg-config --exists cairo; then
  echo "Dự phòng: cài cairo + font từ conda-forge"
  CONDA_BIN="${CONDA:-/usr/share/miniconda}/bin/conda"
  "$CONDA_BIN" create -y -q -p "$HOME/cairo-env" -c conda-forge --override-channels \
    cairo pkg-config fonts-conda-forge font-ttf-dejavu-sans-mono || exit 1
  P="$HOME/cairo-env"
  {
    echo "PKG_CONFIG_PATH=$P/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
    echo "LD_LIBRARY_PATH=$P/lib:${LD_LIBRARY_PATH:-}"
    echo "FONTCONFIG_FILE=$P/etc/fonts/fonts.conf"
  } >> "$GITHUB_ENV"
  echo "$P/bin" >> "$GITHUB_PATH"
fi

export PATH="$HOME/ffmpeg/bin:$PATH"
command -v ffmpeg && ffmpeg -version | head -1
