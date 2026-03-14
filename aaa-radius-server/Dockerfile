# ── Stage 1: Build ───────────────────────────────────────────────────────────
FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    build-essential cmake ninja-build git curl zip unzip tar pkg-config \
    bison flex autoconf automake libtool m4 \
    libssl-dev libcurl4-openssl-dev zlib1g-dev \
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
