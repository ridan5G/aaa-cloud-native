//
// aaa-radius-server — lightweight RADIUS authentication server
//
// Architecture:
//   • UDP socket on RADIUS_PORT (default 1812)
//   • Single recvfrom loop on the main thread dispatches to a fixed thread pool
//   • Each worker thread owns a Handler (with its own libcurl handle)
//   • Two-stage AAA:
//       Stage 1 → GET  /lookup?imsi=...&apn=...           (aaa-lookup-service)
//       Stage 2 → POST /v1/first-connection {imsi,apn,imei} (subscriber-profile-api)
//   • Returns Access-Accept + Framed-IP-Address or Access-Reject
//

#include <arpa/inet.h>
#include <curl/curl.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <cerrno>
#include <condition_variable>
#include <csignal>
#include <cstring>
#include <mutex>
#include <queue>
#include <thread>
#include <vector>

#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/spdlog.h>

#include "Config.h"
#include "Handler.h"
#include "Radius.h"

// ── Work item: one received UDP datagram ─────────────────────────────────────
struct WorkItem {
    std::vector<uint8_t> data;
    sockaddr_in          src{};
};

// ── Bounded MPMC work queue ───────────────────────────────────────────────────
class WorkQueue {
public:
    void push(WorkItem item) {
        {
            std::scoped_lock lk(mu_);
            q_.push(std::move(item));
        }
        cv_.notify_one();
    }

    // Blocks until an item is available or shutdown() is called.
    // Returns false when shut down and queue is empty.
    bool pop(WorkItem& out) {
        std::unique_lock lk(mu_);
        cv_.wait(lk, [this] { return !q_.empty() || done_; });
        if (q_.empty()) return false;
        out = std::move(q_.front());
        q_.pop();
        return true;
    }

    void shutdown() {
        { std::scoped_lock lk(mu_); done_ = true; }
        cv_.notify_all();
    }

private:
    std::queue<WorkItem>    q_;
    std::mutex              mu_;
    std::condition_variable cv_;
    bool                    done_{false};
};

// ── Globals for signal handler ────────────────────────────────────────────────
static std::atomic<bool> g_running{true};
static int               g_sockFd{-1};

static void handleSignal(int sig) {
    spdlog::info("Signal {} received — initiating graceful shutdown", sig);
    g_running.store(false, std::memory_order_relaxed);
    // Interrupt the blocking recvfrom by closing the socket
    if (g_sockFd >= 0) ::close(g_sockFd);
}

// ── Worker thread ─────────────────────────────────────────────────────────────
static void workerLoop(WorkQueue& queue, int sockFd, const Config& cfg) {
    Handler handler(cfg);   // each thread owns its CURL handle via Handler → HttpClient

    WorkItem item;
    while (queue.pop(item)) {
        auto req = parseAccessRequest(item.data.data(), item.data.size());
        if (!req) {
            spdlog::debug("Dropped malformed/non-AccessRequest packet ({} bytes)",
                          item.data.size());
            continue;
        }

        std::vector<uint8_t> response = handler.handle(*req);

        socklen_t addrLen = sizeof(item.src);
        ssize_t   sent    = sendto(
            sockFd,
            response.data(), response.size(),
            0,
            reinterpret_cast<const sockaddr*>(&item.src), addrLen);

        if (sent < 0)
            spdlog::error("sendto failed: {}", strerror(errno));
    }
}

// ── main ──────────────────────────────────────────────────────────────────────
int main() {
    // ── 1. Load configuration ─────────────────────────────────────────────────
    try {
        Config::instance().load();
    } catch (const std::exception& ex) {
        spdlog::critical("Configuration error: {}", ex.what());
        return 1;
    }
    const auto& cfg = Config::instance();

    // ── 2. Structured logger ──────────────────────────────────────────────────
    auto console = spdlog::stdout_color_mt("aaa-radius");
    spdlog::set_default_logger(console);

    if      (cfg.logLevel == "trace") spdlog::set_level(spdlog::level::trace);
    else if (cfg.logLevel == "debug") spdlog::set_level(spdlog::level::debug);
    else if (cfg.logLevel == "warn")  spdlog::set_level(spdlog::level::warn);
    else if (cfg.logLevel == "error") spdlog::set_level(spdlog::level::err);
    else                              spdlog::set_level(spdlog::level::info);

    spdlog::info("aaa-radius-server starting — port={} workers={} lookup={} provisioning={}",
                 cfg.radiusPort, cfg.workerThreads, cfg.lookupUrl, cfg.provisioningUrl);

    // ── 3. libcurl global init (call once, before any thread uses curl) ───────
    if (curl_global_init(CURL_GLOBAL_DEFAULT) != 0) {
        spdlog::critical("curl_global_init failed");
        return 1;
    }

    // ── 4. UDP socket ─────────────────────────────────────────────────────────
    g_sockFd = socket(AF_INET, SOCK_DGRAM, 0);
    if (g_sockFd < 0) {
        spdlog::critical("socket(): {}", strerror(errno));
        curl_global_cleanup();
        return 1;
    }

    {
        int opt = 1;
        setsockopt(g_sockFd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    }

    sockaddr_in bindAddr{};
    bindAddr.sin_family      = AF_INET;
    bindAddr.sin_addr.s_addr = INADDR_ANY;
    bindAddr.sin_port        = htons(cfg.radiusPort);

    if (bind(g_sockFd,
             reinterpret_cast<const sockaddr*>(&bindAddr),
             sizeof(bindAddr)) < 0) {
        spdlog::critical("bind(port={}): {}", cfg.radiusPort, strerror(errno));
        ::close(g_sockFd);
        curl_global_cleanup();
        return 1;
    }

    spdlog::info("Listening on UDP port {}", cfg.radiusPort);

    // ── 5. Signal handlers ────────────────────────────────────────────────────
    std::signal(SIGTERM, handleSignal);
    std::signal(SIGINT,  handleSignal);

    // ── 6. Thread pool ────────────────────────────────────────────────────────
    WorkQueue            queue;
    std::vector<std::thread> workers;
    workers.reserve(static_cast<std::size_t>(cfg.workerThreads));
    for (int i = 0; i < cfg.workerThreads; ++i)
        workers.emplace_back(workerLoop, std::ref(queue), g_sockFd, std::ref(cfg));

    spdlog::info("Ready — {} worker threads started", cfg.workerThreads);

    // ── 7. Receive loop ───────────────────────────────────────────────────────
    static constexpr std::size_t kMaxUdpSize = 4096;  // RFC 2865 §3
    std::vector<uint8_t> buf(kMaxUdpSize);

    while (g_running.load(std::memory_order_relaxed)) {
        sockaddr_in src{};
        socklen_t   srcLen = sizeof(src);

        ssize_t n = recvfrom(
            g_sockFd,
            buf.data(), buf.size(),
            0,
            reinterpret_cast<sockaddr*>(&src), &srcLen);

        if (n <= 0) {
            if (!g_running.load()) break;    // socket closed by signal handler
            if (errno == EINTR)    continue;  // interrupted by signal, retry
            spdlog::error("recvfrom: {}", strerror(errno));
            break;
        }

        WorkItem item;
        item.data.assign(buf.begin(), buf.begin() + n);
        item.src = src;
        queue.push(std::move(item));
    }

    // ── 8. Graceful shutdown ──────────────────────────────────────────────────
    spdlog::info("Draining work queue and joining worker threads...");
    queue.shutdown();
    for (auto& t : workers) t.join();

    curl_global_cleanup();
    spdlog::info("aaa-radius-server stopped cleanly");
    return 0;
}
