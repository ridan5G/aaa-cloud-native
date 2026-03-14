#include "Radius.h"

#include <arpa/inet.h>
#include <openssl/evp.h>

#include <cstring>
#include <stdexcept>

// ---------------------------------------------------------------------------
// Attribute / VSA constants
// ---------------------------------------------------------------------------
static constexpr uint8_t  ATTR_USER_NAME          = 1;
static constexpr uint8_t  ATTR_FRAMED_IP_ADDRESS  = 8;
static constexpr uint8_t  ATTR_VENDOR_SPECIFIC    = 26;
static constexpr uint8_t  ATTR_CALLED_STATION_ID  = 30;
static constexpr uint8_t  ATTR_CALLING_STATION_ID = 31;

static constexpr uint32_t VENDOR_3GPP    = 10415;   // 0x000028AF
static constexpr uint8_t  VSA_3GPP_IMSI  = 1;       // 3GPP-IMSI
static constexpr uint8_t  VSA_3GPP_IMEISV = 20;     // 3GPP-IMEISV

// ---------------------------------------------------------------------------
// parseAccessRequest
// ---------------------------------------------------------------------------
std::optional<RadiusRequest> parseAccessRequest(const uint8_t* data, std::size_t len) {
    if (len < 20) return std::nullopt;
    if (data[0] != static_cast<uint8_t>(RadiusCode::AccessRequest)) return std::nullopt;

    uint16_t pktLen;
    std::memcpy(&pktLen, data + 2, 2);
    pktLen = ntohs(pktLen);
    if (pktLen < 20 || static_cast<std::size_t>(pktLen) > len) return std::nullopt;

    RadiusRequest req;
    req.id = data[1];
    std::memcpy(req.authenticator, data + 4, 16);

    // Walk attribute list
    std::size_t pos = 20;
    while (pos + 2 <= static_cast<std::size_t>(pktLen)) {
        uint8_t aType = data[pos];
        uint8_t aLen  = data[pos + 1];
        if (aLen < 2 || pos + aLen > static_cast<std::size_t>(pktLen)) break;

        const uint8_t* aVal = data + pos + 2;
        std::size_t    vLen = aLen - 2;

        switch (aType) {

        case ATTR_USER_NAME:
            req.userName.assign(reinterpret_cast<const char*>(aVal), vLen);
            break;

        case ATTR_CALLED_STATION_ID:
            req.calledStationId.assign(reinterpret_cast<const char*>(aVal), vLen);
            break;

        case ATTR_CALLING_STATION_ID:
            req.callingStationId.assign(reinterpret_cast<const char*>(aVal), vLen);
            break;

        case ATTR_VENDOR_SPECIFIC: {
            // Vendor-Specific layout: vendor-id(4) + sub-type(1) + sub-len(1) + value
            if (vLen < 6) break;
            uint32_t vendorId;
            std::memcpy(&vendorId, aVal, 4);
            vendorId = ntohl(vendorId);
            if (vendorId != VENDOR_3GPP) break;

            uint8_t vsaType = aVal[4];
            uint8_t vsaLen  = aVal[5];      // includes the 2-byte type+len prefix
            if (vsaLen < 2) break;
            std::size_t vsaVLen = static_cast<std::size_t>(vsaLen) - 2;
            if (vsaVLen > vLen - 6) break;  // bounds check
            const uint8_t* vsaVal = aVal + 6;

            if (vsaType == VSA_3GPP_IMSI)
                req.imsi3gpp.assign(reinterpret_cast<const char*>(vsaVal), vsaVLen);
            else if (vsaType == VSA_3GPP_IMEISV)
                req.imeiSv.assign(reinterpret_cast<const char*>(vsaVal), vsaVLen);
            break;
        }

        default:
            break;
        }

        pos += aLen;
    }

    return req;
}

// ---------------------------------------------------------------------------
// Response authenticator: MD5(code | id | length | reqAuth | attrs | secret)
// ---------------------------------------------------------------------------
static std::array<uint8_t, 16> computeResponseAuth(
    uint8_t                     code,
    uint8_t                     id,
    uint16_t                    totalLen,       // host byte order
    const uint8_t               requestAuth[16],
    const std::vector<uint8_t>& attributes,
    const std::string&          secret)
{
    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    if (!ctx) throw std::runtime_error("EVP_MD_CTX_new failed");

    EVP_DigestInit_ex(ctx, EVP_md5(), nullptr);
    EVP_DigestUpdate(ctx, &code, 1);
    EVP_DigestUpdate(ctx, &id,   1);
    uint16_t lenBE = htons(totalLen);
    EVP_DigestUpdate(ctx, &lenBE, 2);
    EVP_DigestUpdate(ctx, requestAuth, 16);
    if (!attributes.empty())
        EVP_DigestUpdate(ctx, attributes.data(), attributes.size());
    EVP_DigestUpdate(ctx, secret.data(), secret.size());

    std::array<uint8_t, 16> digest{};
    unsigned int dLen = 16;
    EVP_DigestFinal_ex(ctx, digest.data(), &dLen);
    EVP_MD_CTX_free(ctx);
    return digest;
}

// ---------------------------------------------------------------------------
// Build a RADIUS response packet (Accept or Reject)
// ---------------------------------------------------------------------------
static std::vector<uint8_t> buildPacket(
    RadiusCode                  code,
    uint8_t                     id,
    const uint8_t               requestAuth[16],
    const std::vector<uint8_t>& attrs,
    const std::string&          secret)
{
    auto total = static_cast<uint16_t>(20 + attrs.size());
    auto auth  = computeResponseAuth(
        static_cast<uint8_t>(code), id, total, requestAuth, attrs, secret);

    std::vector<uint8_t> pkt;
    pkt.reserve(total);
    pkt.push_back(static_cast<uint8_t>(code));
    pkt.push_back(id);
    pkt.push_back(static_cast<uint8_t>(total >> 8));
    pkt.push_back(static_cast<uint8_t>(total & 0xFF));
    pkt.insert(pkt.end(), auth.begin(), auth.end());
    pkt.insert(pkt.end(), attrs.begin(), attrs.end());
    return pkt;
}

// ---------------------------------------------------------------------------
// buildAccessAccept — Framed-IP-Address (attr 8, 6 bytes)
// ---------------------------------------------------------------------------
std::vector<uint8_t> buildAccessAccept(
    uint8_t            id,
    const uint8_t      requestAuth[16],
    const std::string& framedIp,
    const std::string& secret)
{
    in_addr addr{};
    if (inet_aton(framedIp.c_str(), &addr) == 0)
        throw std::invalid_argument("Invalid Framed-IP-Address: " + framedIp);

    // s_addr is in network byte order; cast to byte array for RFC-compliant output
    const auto* ipBytes = reinterpret_cast<const uint8_t*>(&addr.s_addr);
    std::vector<uint8_t> attrs = {
        ATTR_FRAMED_IP_ADDRESS, 6,
        ipBytes[0], ipBytes[1], ipBytes[2], ipBytes[3]
    };

    return buildPacket(RadiusCode::AccessAccept, id, requestAuth, attrs, secret);
}

// ---------------------------------------------------------------------------
// buildAccessReject — no attributes (total length = 20)
// ---------------------------------------------------------------------------
std::vector<uint8_t> buildAccessReject(
    uint8_t            id,
    const uint8_t      requestAuth[16],
    const std::string& secret)
{
    return buildPacket(RadiusCode::AccessReject, id, requestAuth, {}, secret);
}
