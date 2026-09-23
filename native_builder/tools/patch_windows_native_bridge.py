from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('Usage: patch_windows_native_bridge.py <ppsspp_repo>')
repo = Path(sys.argv[1]).resolve()
header = repo / 'SCBD/SCBDNativeLiveBridge.h'
if not header.exists():
    raise SystemExit('SCBDNativeLiveBridge.h missing')

text = r'''#pragma once

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "Ws2_32.lib")
#else
#include <cerrno>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

#include "SCBD/SCBDNativeWinner.h"

namespace SCBDNativeLiveBridge {

inline constexpr int kPort = 8796;
inline constexpr int kMaxPacketsPerFrame = 16;
inline constexpr int kMaxPacketBytes = 2048;

#ifdef _WIN32
using SocketHandle = SOCKET;
inline constexpr SocketHandle kInvalidSocket = INVALID_SOCKET;
#else
using SocketHandle = int;
inline constexpr SocketHandle kInvalidSocket = -1;
#endif

struct RuntimeState {
    SocketHandle fd = kInvalidSocket;
    bool bound = false;
    uint64_t packets = 0;
    uint64_t errors = 0;
    std::string lastCommand = "NONE";
    std::string lastError;
    std::string lastAvatarUrl;
    std::chrono::steady_clock::time_point nextBindAttempt{};
};

struct Snapshot {
    bool bound = false;
    int port = kPort;
    uint64_t packets = 0;
    uint64_t errors = 0;
    std::string lastCommand;
    std::string lastError;
    std::string lastAvatarUrl;
};

inline RuntimeState &State() { static RuntimeState s; return s; }

inline void CloseSocket(SocketHandle fd) {
#ifdef _WIN32
    if (fd != INVALID_SOCKET) ::closesocket(fd);
#else
    if (fd >= 0) ::close(fd);
#endif
}

inline int SocketError() {
#ifdef _WIN32
    return ::WSAGetLastError();
#else
    return errno;
#endif
}

inline bool WouldBlock(int e) {
#ifdef _WIN32
    return e == WSAEWOULDBLOCK;
#else
    return e == EAGAIN || e == EWOULDBLOCK;
#endif
}

inline bool InitSockets(RuntimeState &s) {
#ifdef _WIN32
    static bool attempted = false;
    static bool ok = false;
    if (!attempted) {
        attempted = true;
        WSADATA data{};
        ok = ::WSAStartup(MAKEWORD(2, 2), &data) == 0;
    }
    if (!ok) {
        ++s.errors;
        s.lastError = "WSAStartup failed";
    }
    return ok;
#else
    (void)s;
    return true;
#endif
}

inline int HexNibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

inline std::string UrlDecode(const std::string &src) {
    std::string out; out.reserve(src.size());
    for (size_t i = 0; i < src.size(); ++i) {
        const char c = src[i];
        if (c == '%' && i + 2 < src.size()) {
            const int hi = HexNibble(src[i + 1]);
            const int lo = HexNibble(src[i + 2]);
            if (hi >= 0 && lo >= 0) { out.push_back(static_cast<char>((hi << 4) | lo)); i += 2; continue; }
        }
        out.push_back(c == '+' ? ' ' : c);
    }
    return out;
}

inline std::vector<std::string> SplitTabs(const std::string &line) {
    std::vector<std::string> out;
    size_t start = 0;
    while (start <= line.size()) {
        const size_t tab = line.find('\t', start);
        if (tab == std::string::npos) { out.push_back(line.substr(start)); break; }
        out.push_back(line.substr(start, tab - start));
        start = tab + 1;
    }
    return out;
}

inline int ParseInt(const std::string &text, int fallback) {
    if (text.empty()) return fallback;
    char *end = nullptr;
    const long v = std::strtol(text.c_str(), &end, 10);
    if (end == text.c_str() || *end != '\0') return fallback;
    if (v < -2147483647L) return -2147483647;
    if (v > 2147483647L) return 2147483647;
    return static_cast<int>(v);
}

inline bool EnsureBound(RuntimeState &s) {
    if (s.bound && s.fd != kInvalidSocket) return true;
    const auto now = std::chrono::steady_clock::now();
    if (now < s.nextBindAttempt) return false;
    s.nextBindAttempt = now + std::chrono::seconds(2);
    if (!InitSockets(s)) return false;

    SocketHandle fd = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (fd == kInvalidSocket) {
        ++s.errors; s.lastError = "socket() failed " + std::to_string(SocketError()); return false;
    }

    int reuse = 1;
#ifdef _WIN32
    ::setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char *>(&reuse), sizeof(reuse));
    u_long nonBlocking = 1;
    if (::ioctlsocket(fd, FIONBIO, &nonBlocking) != 0) {
        ++s.errors; s.lastError = "ioctlsocket(FIONBIO) failed " + std::to_string(SocketError()); CloseSocket(fd); return false;
    }
#else
    ::setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
#endif

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(kPort);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (::bind(fd, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) != 0) {
        ++s.errors; s.lastError = "bind 127.0.0.1:8796 failed " + std::to_string(SocketError()); CloseSocket(fd); return false;
    }
    s.fd = fd; s.bound = true; s.lastError.clear(); return true;
}

inline void Reply(RuntimeState &s, const sockaddr_in &peer, int peerLen, const std::string &command, bool ok, const std::string &detail = {}) {
    if (s.fd == kInvalidSocket) return;
    std::string reply = "ACK\t" + command + "\t" + (ok ? "OK" : "ERR");
    if (!detail.empty()) reply += "\t" + detail;
    ::sendto(s.fd, reply.data(), static_cast<int>(reply.size()), 0, reinterpret_cast<const sockaddr *>(&peer), peerLen);
}

inline void HandlePacket(RuntimeState &s, std::string line, const sockaddr_in &peer, int peerLen) {
    while (!line.empty() && (line.back() == '\r' || line.back() == '\n' || line.back() == '\0')) line.pop_back();
    const auto parts = SplitTabs(line);
    if (parts.empty() || parts[0].empty()) { ++s.errors; s.lastError = "empty command"; Reply(s, peer, peerLen, "UNKNOWN", false, "empty-command"); return; }
    const std::string &cmd = parts[0]; s.lastCommand = cmd;
    if (cmd == "PING") { Reply(s, peer, peerLen, "PING", true, "WINDOWS-V0.1"); return; }
    if (cmd == "WINNER") {
        if (parts.size() < 4) { ++s.errors; s.lastError = "WINNER needs username/team/score"; Reply(s, peer, peerLen, "WINNER", false, "bad-fields"); return; }
        const std::string username = UrlDecode(parts[1]);
        const int team = ParseInt(parts[2], 1) == 2 ? 2 : 1;
        const int score = std::max(0, ParseInt(parts[3], 0));
        if (parts.size() >= 5) s.lastAvatarUrl = UrlDecode(parts[4]);
        SCBDNativeWinner::BeginWinnerPick(username.c_str(), team, score);
        Reply(s, peer, peerLen, "WINNER", true); return;
    }
    if (cmd == "PICK") {
        if (parts.size() < 3) { ++s.errors; s.lastError = "PICK needs id/name"; Reply(s, peer, peerLen, "PICK", false, "bad-fields"); return; }
        const int id = ParseInt(parts[1], 0); const std::string character = UrlDecode(parts[2]);
        if (id < 1 || id > 28 || character.empty()) { ++s.errors; s.lastError = "PICK rejected"; Reply(s, peer, peerLen, "PICK", false, "invalid-pick"); return; }
        SCBDNativeWinner::ShowPickSuccess(id, character.c_str()); Reply(s, peer, peerLen, "PICK", true); return;
    }
    if (cmd == "TIMEOUT") { SCBDNativeWinner::ShowTimeout(); Reply(s, peer, peerLen, "TIMEOUT", true); return; }
    if (cmd == "CANCEL") { SCBDNativeWinner::Cancel(); Reply(s, peer, peerLen, "CANCEL", true); return; }
    ++s.errors; s.lastError = "unknown command: " + cmd; Reply(s, peer, peerLen, cmd, false, "unknown-command");
}

inline void Process() {
    RuntimeState &s = State();
    if (!EnsureBound(s)) return;
    for (int i = 0; i < kMaxPacketsPerFrame; ++i) {
        char buf[kMaxPacketBytes + 1]{};
        sockaddr_in peer{};
#ifdef _WIN32
        int peerLen = sizeof(peer);
        const int n = ::recvfrom(s.fd, buf, kMaxPacketBytes, 0, reinterpret_cast<sockaddr *>(&peer), &peerLen);
#else
        socklen_t peerLenNative = sizeof(peer);
        const ssize_t nNative = ::recvfrom(s.fd, buf, kMaxPacketBytes, MSG_DONTWAIT, reinterpret_cast<sockaddr *>(&peer), &peerLenNative);
        const int n = static_cast<int>(nNative);
        const int peerLen = static_cast<int>(peerLenNative);
#endif
        if (n < 0) {
            const int e = SocketError();
            if (WouldBlock(e)) break;
            ++s.errors; s.lastError = "recvfrom failed " + std::to_string(e); break;
        }
        if (n == 0) break;
        buf[n] = '\0'; ++s.packets; HandlePacket(s, std::string(buf, static_cast<size_t>(n)), peer, peerLen);
    }
}

inline Snapshot Read() {
    const RuntimeState &s = State();
    Snapshot out; out.bound=s.bound; out.port=kPort; out.packets=s.packets; out.errors=s.errors;
    out.lastCommand=s.lastCommand; out.lastError=s.lastError; out.lastAvatarUrl=s.lastAvatarUrl; return out;
}

} // namespace SCBDNativeLiveBridge
'''
header.write_text(text, encoding='utf-8')
print('Windows native live bridge PASS:', header)
