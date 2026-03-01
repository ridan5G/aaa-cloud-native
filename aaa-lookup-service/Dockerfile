# ── Stage 1: Build ───────────────────────────────────────────────────────────
FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build git curl zip unzip tar pkg-config \
    libssl-dev libpq-dev uuid-dev zlib1g-dev libjsoncpp-dev \
    libbrotli-dev libc-ares-dev libhiredis-dev \
    && rm -rf /var/lib/apt/lists/*
# ca config
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git \
 && update-ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# vcpkg for C++ dependency management
ENV VCPKG_ROOT=/opt/vcpkg
RUN git clone --depth=1 https://github.com/microsoft/vcpkg.git ${VCPKG_ROOT} && \
    ${VCPKG_ROOT}/bootstrap-vcpkg.sh -disableMetrics

# Install all project dependencies via vcpkg
COPY vcpkg.json /workspace/vcpkg.json
WORKDIR /workspace
RUN ${VCPKG_ROOT}/vcpkg install \
    --triplet=x64-linux \
    --feature-flags=manifests \
    --x-manifest-root=/workspace

# Build the service
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

USER aaa

# HTTP API port (internal)
EXPOSE 8081
# Prometheus metrics port
EXPOSE 9090

ENTRYPOINT ["/usr/local/bin/aaa_lookup_service"]
