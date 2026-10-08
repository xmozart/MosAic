# syntax=docker/dockerfile:1.7
# MosAic server image (ARCHITECTURE.md §15; ADR 0055): multi-arch (amd64, arm64), LGPL
# FFmpeg run as a subprocess, the web UI served by the backend. Build:
#   docker buildx build --platform linux/amd64,linux/arm64 -t mosaic:latest .

# ----------------------------------------------------------------- web UI (any arch)
FROM --platform=$BUILDPLATFORM node:24-bookworm-slim AS ui
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund --ignore-scripts
COPY docs/ui/tokens.json /src/docs/ui/tokens.json
COPY frontend/ ./
RUN npm run build

# ----------------------------------------------------------------- LGPL FFmpeg
# BtbN's static LGPL builds (no GPL parts: no libx264/x265; hardware encoding through
# NVENC/VAAPI), pinned to one dated release and checked by SHA-256 per architecture. BtbN
# prunes old autobuilds: to update, set the three ARGs from the release's asset digests
# (docs/deploy/DOCKER.md). The build is refused if it reports --enable-gpl.
FROM debian:bookworm-slim AS ffmpeg
ARG TARGETARCH
ARG FFMPEG_TAG=autobuild-2026-10-07-13-07
ARG FFMPEG_NAME=ffmpeg-n8.1.3-14-g330caae0c1
ARG FFMPEG_SHA256_AMD64=8e51013f0977f0d59f2ecfb7a5c8baec7f4c6896ebd47a3877b9ca7431f2ce47
ARG FFMPEG_SHA256_ARM64=0f4c1b60fec2076db6ebb639a2106f704007a5415ce97916c07efc59300737e2
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl xz-utils \
 && rm -rf /var/lib/apt/lists/*
RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) arch=linux64; sum="$FFMPEG_SHA256_AMD64" ;; \
      arm64) arch=linuxarm64; sum="$FFMPEG_SHA256_ARM64" ;; \
      *) echo "unsupported arch $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    name="${FFMPEG_NAME}-${arch}-lgpl-8.1"; \
    curl -fL --retry 3 -o /tmp/ffmpeg.tar.xz "https://github.com/BtbN/FFmpeg-Builds/releases/download/${FFMPEG_TAG}/${name}.tar.xz"; \
    echo "${sum}  /tmp/ffmpeg.tar.xz" | sha256sum -c -; \
    tar -xf /tmp/ffmpeg.tar.xz -C /tmp; \
    install -m 0755 "/tmp/${name}/bin/ffmpeg" "/tmp/${name}/bin/ffprobe" /usr/local/bin/; \
    if /usr/local/bin/ffmpeg -hide_banner -buildconf | grep -q -- "--enable-gpl"; then echo "GPL FFmpeg refused" >&2; exit 1; fi; \
    /usr/local/bin/ffmpeg -hide_banner -version | head -1; \
    rm -rf /tmp/ffmpeg.tar.xz "/tmp/${name}"

# ----------------------------------------------------------------- runtime
FROM python:3.12-slim-bookworm AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.10.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY backend/ backend/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
COPY --from=ffmpeg /usr/local/bin/ffmpeg /usr/local/bin/ffprobe /usr/local/bin/
COPY --from=ui /src/frontend/dist /app/ui
COPY LICENSES.md /app/LICENSES.md

# /data: MosAic's app data: the control DB, settings, models, logs and every trip's live
# database (MOSAIC_FOLDER_DB=never: a bind mount can't be trusted to reveal whether a NAS or
# a cloud-synced folder backs it; invariant 2, ADR 0055). /media: the footage, mounted by
# compose (the media root people can open).
ENV PATH=/opt/venv/bin:$PATH \
    MOSAIC_MODE=server \
    MOSAIC_HOME=/data \
    MOSAIC_UI_DIR=/app/ui \
    MOSAIC_MEDIA_ROOTS=/media \
    MOSAIC_BIND=0.0.0.0 \
    MOSAIC_FOLDER_DB=never \
    PYTHONUNBUFFERED=1
RUN useradd --uid 1000 --user-group --create-home mosaic \
 && mkdir -p /data /media \
 && chown mosaic:mosaic /data
USER mosaic
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4).status == 200 else 1)"]
CMD ["mosaic", "serve", "--port", "8765"]
