#pragma once

#include <string>

struct HttpResponse {
    int         statusCode{0};
    std::string body;
};

// ---------------------------------------------------------------------------
// HttpClient — thin libcurl wrapper
//
// NOT thread-safe: each worker thread must own its own instance.
// ---------------------------------------------------------------------------
class HttpClient {
public:
    HttpClient();
    ~HttpClient();

    HttpClient(const HttpClient&)            = delete;
    HttpClient& operator=(const HttpClient&) = delete;

    HttpResponse get(const std::string& url);
    HttpResponse post(const std::string& url, const std::string& jsonBody);

private:
    void* curl_;   // CURL* (void* to avoid exposing curl.h in this header)
};
