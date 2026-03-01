cmake_minimum_required(VERSION 3.22)
project(aaa_lookup_service CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ── Release flags ────────────────────────────────────────────────────────────
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
add_compile_options(-Wall -Wextra -Wpedantic
  $<$<CONFIG:Release>:-O3>
  $<$<CONFIG:Release>:-march=x86-64-v3>
)
# ── Dependencies (found via vcpkg toolchain or system packages) ───────────────
find_package(Drogon CONFIG REQUIRED)          # HTTP server + async PostgreSQL
find_package(prometheus-cpp CONFIG REQUIRED)  # Prometheus metrics
find_package(spdlog CONFIG REQUIRED)          # Structured logging
find_package(jwt-cpp CONFIG REQUIRED)         # JWT RS256 verification
find_package(OpenSSL REQUIRED)                # SHA-256 for IMSI hashing

# ── Sources ───────────────────────────────────────────────────────────────────
set(SOURCES
  src/main.cpp
  src/Metrics.cpp
  src/Resolver.cpp
  src/controllers/LookupController.cpp
  src/controllers/HealthController.cpp
)

add_executable(aaa_lookup_service ${SOURCES})

target_include_directories(aaa_lookup_service PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_link_libraries(aaa_lookup_service PRIVATE
  Drogon::Drogon
  prometheus-cpp::pull
  prometheus-cpp::core
  spdlog::spdlog
  jwt-cpp::jwt-cpp
  OpenSSL::SSL
  OpenSSL::Crypto
)

# ── Install ───────────────────────────────────────────────────────────────────
install(TARGETS aaa_lookup_service DESTINATION bin)
