# ── Stage 1: Build ───────────────────────────────────────────────────────────
# Uses pre-built base with vcpkg packages already compiled.
# Build the base once: make build-lookup-base
ARG BUILD_BASE=aaa/aaa-lookup-build-base:latest
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
    libssl3 libpq5 uuid-runtime ca-certificates libjsoncpp25 libbrotli1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -r aaa && useradd -r -g aaa aaa

COPY --from=builder /workspace/build/aaa_lookup_service /usr/local/bin/aaa_lookup_service

# JWT public key mount point (injected at runtime via K8s secret)
RUN mkdir -p /etc/jwt && chown aaa:aaa /etc/jwt

# Writable working directory — Drogon creates ./uploads/tmp/ on startup
RUN mkdir -p /app/uploads && chown -R aaa:aaa /app
WORKDIR /app

USER aaa

# HTTP API port (internal)
EXPOSE 8081
# Prometheus metrics port
EXPOSE 9090

ENTRYPOINT ["/usr/local/bin/aaa_lookup_service"]
