# ── Stage 1: Build ───────────────────────────────────────────────────────────
# Uses pre-built base with vcpkg packages already compiled.
# Build the base once: make build-radius-base
ARG BUILD_BASE=aaa/aaa-radius-build-base:latest
FROM ${BUILD_BASE} AS builder

# Build the service (vcpkg packages already in /workspace/vcpkg_installed)
COPY . /workspace/
RUN cmake -S . -B build \
    -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE=${VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake \
    -DVCPKG_TARGET_TRIPLET=x64-linux && \
    cmake --build build --config Release -j$(nproc)

# ── Stage 2: Runtime (minimal) ───────────────────────────────────────────────
FROM ubuntu:24.04 AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 libcurl4 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -r aaa && useradd -r -g aaa aaa

COPY --from=builder /workspace/build/aaa_radius_server /usr/local/bin/aaa_radius_server

RUN mkdir -p /app && chown -R aaa:aaa /app
WORKDIR /app

USER aaa

# RADIUS authentication port (UDP)
EXPOSE 1812/udp

ENTRYPOINT ["/usr/local/bin/aaa_radius_server"]
