#!/usr/bin/env bash
# Build librealsense from source on the Jetson and make `import pyrealsense2`
# work in the conda env (depth mode, Intel RealSense D455).
#
# Why: `pip install pyrealsense2` has no working aarch64 wheel for the Jetson.
# Approach adapted from JetsonHacks installRealSenseSDK (buildLibrealsense.sh):
# RSUSB backend (no kernel patch, works on any JetPack), Python bindings built
# against the conda Python 3.8. Never touches torch, numpy, or other packages.
#
# Usage: ./robot/install_realsense_jetson.sh      (30-90 min; run inside tmux)
#   OFB_RS_VERSION=v2.55.1   librealsense tag
#   OFB_RS_JOBS=4            parallel compile jobs (lower it if the Jetson runs out of memory)
#   OFB_RS_SRC=~/librealsense
set -uo pipefail
source "$(dirname "$0")/env.sh"
ofb_log_init install_realsense

VER="${OFB_RS_VERSION:-v2.55.1}"
JOBS="${OFB_RS_JOBS:-4}"
SRC="${OFB_RS_SRC:-$HOME/librealsense}"

echo "== 1. conda Python"
if ofb_conda_activate; then ok "conda env $OFB_CONDA_ENV"; else ofb_summary; exit 1; fi
PY="$(command -v python)"
SITE="$(python -c 'import site; print(site.getsitepackages()[0])')"
info "python $PY ($(python --version 2>&1)), site-packages $SITE"
if python -c "import pyrealsense2" 2>/dev/null; then
  ok "pyrealsense2 already importable: $(python -c 'import pyrealsense2 as rs; print(getattr(rs, "__version__", "?"))')"
  ofb_summary; exit 0
fi

echo "== 2. Build dependencies (apt)"
sudo apt-get install -y git cmake build-essential pkg-config libssl-dev libusb-1.0-0-dev libudev-dev \
  && ok "build dependencies" || { fail "apt install failed" "read $OFB_LOG_FILE"; ofb_summary; exit 1; }

echo "== 3. Source $VER"
if [ -d "$SRC/.git" ]; then
  info "using existing $SRC"
else
  git clone --depth 1 -b "$VER" https://github.com/IntelRealSense/librealsense.git "$SRC" \
    && ok "cloned librealsense $VER" || { fail "git clone failed" "check the network"; ofb_summary; exit 1; }
fi

echo "== 4. cmake (RSUSB backend, Python bindings for $PY)"
# Use the system cmake (3.16 on focal), not the conda env's: a pip-installed
# CMake 4.x rejects librealsense's cmake_minimum_required (seen 2026-11-20).
CMAKE=cmake; [ -x /usr/bin/cmake ] && CMAKE=/usr/bin/cmake
info "$($CMAKE --version | head -n 1) ($CMAKE)"
mkdir -p "$SRC/build" && cd "$SRC/build" || exit 1
# A cache written by another cmake (the conda one) cannot be reused; keep a
# matching cache so a rerun does not start the compile over.
if [ -f CMakeCache.txt ] && ! grep -q "^CMAKE_COMMAND:INTERNAL=$CMAKE\$" CMakeCache.txt; then
  rm -f CMakeCache.txt
fi
# Python_EXECUTABLE: librealsense's pybind11 setup uses FindPython, which ignores
# PYTHON_EXECUTABLE and finds the system Python 2.7 without headers (2026-11-20).
if "$CMAKE" .. -DCMAKE_BUILD_TYPE=Release \
     -DFORCE_RSUSB_BACKEND=ON \
     -DBUILD_PYTHON_BINDINGS=ON -DPYTHON_EXECUTABLE="$PY" -DPython_EXECUTABLE="$PY" \
     -DBUILD_EXAMPLES=OFF -DBUILD_GRAPHICAL_EXAMPLES=OFF -DBUILD_WITH_CUDA=OFF \
     -DBUILD_UNIT_TESTS=OFF; then
  ok "cmake configured"
else
  fail "cmake failed" "read $OFB_LOG_FILE (pybind11 and json are downloaded during cmake); after an interrupted run: rm -rf $SRC/build, then rerun"; ofb_summary; exit 1
fi

echo "== 5. make -j$JOBS (30-90 min)"
if make -j"$JOBS"; then ok "built"; else
  fail "make failed" "rerun with OFB_RS_JOBS=2 if the compiler was killed (out of memory)"; ofb_summary; exit 1
fi
sudo make install >/dev/null && sudo ldconfig && ok "librealsense2 installed to /usr/local (rs-enumerate-devices)"

echo "== 6. pyrealsense2 into the conda env"
MOD="$(find "$SRC/build" -name 'pyrealsense2*.so' | head -n 1)"
if [ -z "$MOD" ]; then fail "pyrealsense2*.so not found under $SRC/build"; ofb_summary; exit 1; fi
DST="$SITE/pyrealsense2"
mkdir -p "$DST"
cp "$(dirname "$MOD")"/pyrealsense2*.so "$DST"/
cp "$(dirname "$MOD")"/pybackend2*.so "$DST"/ 2>/dev/null || true
# Same layout as the pip package: pyrealsense2/__init__.py re-exports the extension.
printf 'from .pyrealsense2 import *  # noqa: F401,F403\n' > "$DST/__init__.py"
if python -c "import pyrealsense2 as rs; print('devices:', len(rs.context().devices))"; then
  ok "import pyrealsense2 works in $OFB_CONDA_ENV"
else
  fail "import pyrealsense2 failed" "ldd $DST/pyrealsense2*.so | grep 'not found'"
fi
info "next: plug the D455 into a blue USB 3 port, then ./robot/check_stage4.sh depth"
ofb_summary
