#include "HttpClient.h"

#include <curl/curl.h>

#include <stdexcept>

// ---------------------------------------------------------------------------
// Write callback — appends received data to a std::string body
// ---------------------------------------------------------------------------
static std::size_t writeCallback(char* ptr, std::size_t size,
                                 std::size_t nmemb, std::string* body) {
    body->append(ptr, size * nmemb);
    return size * nmemb;
}

// ---------------------------------------------------------------------------
// HttpClient
// ---------------------------------------------------------------------------
HttpClient::HttpClient() {
    curl_ = curl_easy_init();
    if (!curl_) throw std::runtime_error("curl_easy_init failed");
}

HttpClient::~HttpClient() {
    if (curl_) curl_easy_cleanup(static_cast<CURL*>(curl_));
}

HttpResponse HttpClient::get(const std::string& url) {
    auto* curl = static_cast<CURL*>(curl_);
    HttpResponse resp;

    curl_easy_reset(curl);
    curl_easy_setopt(curl, CURLOPT_URL,               url.c_str());
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION,     writeCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA,         &resp.body);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS,        5000L);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, 2000L);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL,          1L);   // required for multithreaded

    CURLcode rc = curl_easy_perform(curl);
    if (rc == CURLE_OK) {
        long code = 0;
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &code);
        resp.statusCode = static_cast<int>(code);
    } else {
        resp.statusCode = -1;
        resp.body       = curl_easy_strerror(rc);
    }

    return resp;
}

HttpResponse HttpClient::post(const std::string& url, const std::string& jsonBody) {
    auto* curl = static_cast<CURL*>(curl_);
    HttpResponse resp;

    curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    curl_easy_reset(curl);
    curl_easy_setopt(curl, CURLOPT_URL,               url.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER,        headers);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS,        jsonBody.c_str());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE,     static_cast<long>(jsonBody.size()));
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION,     writeCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA,         &resp.body);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS,        10000L);  // first-connection may be slow
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, 2000L);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL,          1L);

    CURLcode rc = curl_easy_perform(curl);
    if (rc == CURLE_OK) {
        long code = 0;
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &code);
        resp.statusCode = static_cast<int>(code);
    } else {
        resp.statusCode = -1;
        resp.body       = curl_easy_strerror(rc);
    }

    curl_slist_free_all(headers);
    return resp;
}
