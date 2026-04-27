#pragma once

// ---------------------------------------------------------------------------
// HashUtils — IMSI obfuscation for structured log lines.
//
// Raw IMSIs MUST NEVER appear in logs (PII / GDPR).
// We log the first 8 hex characters of SHA-256(imsi) — sufficient for
// incident correlation without exposing the subscriber identifier.
// ---------------------------------------------------------------------------

#include <array>
#include <iomanip>
#include <openssl/sha.h>
#include <sstream>
#include <string>

namespace HashUtils {

/// Returns first 8 hex chars of SHA-256(input).
/// Example: imsiPartialHash("278773000002002") → "3a9f12c0"
inline std::string imsiPartialHash(const std::string& imsi) {
    std::array<unsigned char, SHA256_DIGEST_LENGTH> digest{};
    SHA256(reinterpret_cast<const unsigned char*>(imsi.data()),
           imsi.size(),
           digest.data());

    std::ostringstream oss;
    oss << std::hex << std::setfill('0');
    for (int i = 0; i < 4; ++i)          // 4 bytes = 8 hex chars
        oss << std::setw(2) << static_cast<int>(digest[i]);
    return oss.str();
}

} // namespace HashUtils
