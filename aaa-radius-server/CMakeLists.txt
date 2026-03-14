cmake_minimum_required(VERSION 3.22)
project(aaa_radius_server CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ── Release flags ─────────────────────────────────────────────────────────────
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
add_compile_options(-Wall -Wextra -Wpedantic
  $<$<CONFIG:Release>:-O3>
  $<$<CONFIG:Release>:-march=x86-64-v3>
)

# ── Dependencies (via vcpkg) ──────────────────────────────────────────────────
find_package(CURL CONFIG REQUIRED)          # HTTP client for lookup + provisioning
find_package(nlohmann_json CONFIG REQUIRED) # JSON parsing
find_package(spdlog CONFIG REQUIRED)        # Structured logging
find_package(OpenSSL REQUIRED)              # MD5 for RADIUS response authenticator

# ── Sources ───────────────────────────────────────────────────────────────────
set(SOURCES
  src/main.cpp
  src/Radius.cpp
  src/HttpClient.cpp
  src/Handler.cpp
)

add_executable(aaa_radius_server ${SOURCES})

target_include_directories(aaa_radius_server PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_link_libraries(aaa_radius_server PRIVATE
  CURL::libcurl
  nlohmann_json::nlohmann_json
  spdlog::spdlog
  OpenSSL::SSL
  OpenSSL::Crypto
)

# ── Install ───────────────────────────────────────────────────────────────────
install(TARGETS aaa_radius_server DESTINATION bin)
