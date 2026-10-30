import asyncio
import socket
import time
import uuid
import sys
import argparse
import signal
import statistics

###
'''
# Sends UDP SIP options to an endpoint and shows DNS resolution time, round-trip-time and packet loss percentage.
# //SHAL 2026
###
'''

# Define the SIP port
SIP_PORT = 5060

# Request interval, time to wait between requests
REQUEST_INTERVAL = 1

# Percentiles are only printed with at least this many replies (meaningless on tiny samples)
PERCENTILE_MIN_SAMPLES = 20

# Exit codes for use in monitoring
EXIT_OK = 0       # every request got a reply
EXIT_LOSS = 1     # at least one request got no reply
EXIT_ERROR = 2    # could not run: bad arguments, DNS failure, socket error

# One Call-ID for the whole run; CSeq increments per request (RFC 3261 style keepalive)
CALL_ID = str(uuid.uuid4())


# SIP OPTIONS request template
OPTIONS_TEMPLATE = (
    "OPTIONS sip:{server}:{port} SIP/2.0\r\n"
    "Via: SIP/2.0/UDP {lan_ip}:{lan_port};branch=z9hG4bK{branch};rport\r\n"
    "Max-Forwards: 70\r\n"
    "To: <sip:ping@{server}:{port}>\r\n"
    "From: <sip:ping@{server}:{port}>;tag=73686572617A\r\n"
    "Call-ID: {call_id}\r\n"
    "CSeq: {cseq} OPTIONS\r\n"
    "Contact: sip:{lan_ip}:{lan_port}\r\n"
    "User-Agent: sip-options\r\n"
    "Accept: application/sdp\r\n"
    "Content-Length: 0\r\n"
    "\r\n"
)

# Compact header forms (RFC 3261 7.3.3) we need to recognise in replies
COMPACT_HEADERS = {"i": "call-id", "v": "via"}


# Better way to get local ip. 
def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.4.4", 53))
        return sock.getsockname()[0]
    finally:
        sock.close()


# Create and reuse one socket.
# connect() on UDP: the kernel drops packets from other sources and reports
# ICMP port-unreachable as ConnectionRefusedError/ConnectionResetError.
# Non-blocking so asyncio can await it directly (no worker threads).
def create_socket(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect((ip, port))
    sock.setblocking(False)
    return sock

# Percentilr calculation
def percentile(data, p):
    if not data:
        return 0
    data = sorted(data)
    k = (len(data) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(data) - 1)
    if f == c:
        return data[f]
    return data[f] + (data[c] - data[f]) * (k - f)


# DNS resolution time calculation
def resolve_target(host):
    #monotonic for better results
    start = time.monotonic()
    try:
        ip = socket.gethostbyname(host)
        dns_time = (time.monotonic() - start) * 1000
        return ip, dns_time
    except socket.gaierror:
        return None, None


# Accepts host or host:port
def split_host_port(dest, default_port):
    if ":" in dest:
        host, port = dest.rsplit(":", 1)
        return host, int(port)
    return dest, default_port


# Parse a SIP response. Returns (status_code, reason, headers) or None if the
# packet is not a SIP response (garbage, a request, wrong protocol, etc.)
def parse_response(data):
    lines = data.decode("utf-8", errors="replace").splitlines()
    if not lines:
        return None

    try:
        proto, code, reason = (lines[0].split(" ", 2) + [""])[:3]
    except ValueError:
        return None
    if proto != "SIP/2.0" or not code.isdigit():
        return None

    headers = {}
    for line in lines[1:]:
        if not line:        # blank line = end of headers
            break
        if ":" in line:
            name, value = line.split(":", 1)
            name = name.strip().lower()
            name = COMPACT_HEADERS.get(name, name)
            headers.setdefault(name, value.strip())   # keep first (top) occurrence

    return int(code), reason, headers


# Does this response belong to the request we just sent?
def matches_request(headers, call_id, cseq, branch):
    if headers.get("call-id") != call_id:
        return False
    if headers.get("cseq", "").split() != [cseq, "OPTIONS"]:
        return False
    via_params = [p.strip() for p in headers.get("via", "").split(";")]
    return f"branch=z9hG4bK{branch}" in via_params


# Verbose output: print a raw SIP message, indented
def dump(label, text):
    print(label)
    for line in text.rstrip().splitlines():
        print(f"    {line}")
    print()


# Send the request, then keep reading until a valid final response for it arrives.
# Stale, foreign, malformed and 1xx packets are ignored. The caller applies the
# timeout with wait_for; cancelling this coroutine leaves nothing running behind.
async def send_and_receive(sock, message, call_id, cseq, branch, verbose=False):
    loop = asyncio.get_running_loop()
    await loop.sock_sendall(sock, message.encode())
    if verbose:
        dump(">>> Request sent", message)

    while True:
        data = await loop.sock_recv(sock, 4096)

        parsed = parse_response(data)
        if parsed is None:
            if verbose:
                print(f"<<< Ignored: not a SIP response ({len(data)} bytes)\n")
            continue                      # not a SIP response
        status, reason, headers = parsed
        if not matches_request(headers, call_id, cseq, branch):
            if verbose:
                print(f"<<< Ignored: {status} {reason} does not match this request\n")
            continue                      # late reply to an earlier request / unrelated
        if verbose:
            dump("<<< Response received", data.decode("utf-8", errors="replace"))
        if status < 200:
            continue                      # provisional (100 Trying etc.), wait for final
        return status, reason


async def send_options_request(sock, host, port, timeout, lan_ip, seq, verbose=False):
    try:
        branch = uuid.uuid4().hex[:16]
        cseq = str(seq)

        lan_port = sock.getsockname()[1]

        request = OPTIONS_TEMPLATE.format(
            server=host,   # keep hostname in SIP headers
            port=port,
            lan_ip=lan_ip,
            lan_port=lan_port,
            branch=branch,
            call_id=CALL_ID,
            cseq=cseq
        )

        start = time.monotonic()

        try:
            status, reason = await asyncio.wait_for(
                send_and_receive(sock, request, CALL_ID, cseq, branch, verbose),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            print("Request timed out")
            return None
        except ConnectionError:
            print("Port unreachable (ICMP error)")
            return None

        rtt = (time.monotonic() - start) * 1000
        print(f"Reply received: {status} {reason} - {rtt:.2f} ms")
        return rtt

    except Exception as e:
        print(f"Request error: {e}")
        return None


# ---------- Main ----------

async def main():
    parser = argparse.ArgumentParser(
        description="Sends UDP SIP options to an endpoint and shows DNS resolution time, round-trip-time and packet loss percentage ",
        epilog="Exit codes: 0 = all replies received, 1 = packet loss, 2 = error",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("destination", help="SIP server IP/hostname, optionally host:port")
    parser.add_argument("-p", "--port", type=int, default=SIP_PORT)
    parser.add_argument("-c", "--count", type=int, default=5)
    parser.add_argument("-t", "--timeout", type=float, default=3)
    parser.add_argument("-i", "--interval", type=float, default=REQUEST_INTERVAL)
    parser.add_argument("-v", "--verbose", action="store_true", help="print full request and response messages")

    args = parser.parse_args()

    try:
        host, port = split_host_port(args.destination, args.port)
    except ValueError:
        parser.error(f"invalid destination: {args.destination}")

    num_requests = args.count
    timeout = args.timeout

    try:
        lan_ip = get_local_ip()
    except OSError as e:
        print(f"Could not determine local IP: {e}")
        return EXIT_ERROR

    # DNS resolution
    ip, dns_time = resolve_target(host)

    if ip is None:
        print("DNS resolution failed")
        return EXIT_ERROR

    try:
        sock = create_socket(ip, port)
    except OSError as e:
        print(f"Socket error: {e}")
        return EXIT_ERROR

    print(f"\nSending SIP Option to: {host} ({ip}), port {port}")
    print(f"DNS resolution time: {dns_time:.2f} ms")
    #print(f"Local IP: {lan_ip}")
    print(f"Requests: {num_requests}, Timeout: {timeout}s\n")

    sent = 0
    received = 0
    rtt_list = []

    try:
        for seq in range(1, num_requests + 1):
            start = time.monotonic()
            rtt = await send_options_request(sock, host, port, timeout, lan_ip, seq, args.verbose)

            sent += 1
            if rtt is not None:
                received += 1
                rtt_list.append(rtt)

            # sleep only for what is left of the interval so the cadence doesn't drift
            await asyncio.sleep(max(0, args.interval - (time.monotonic() - start)))

    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nInterrupted")      # fall through to the summary, like ping
    finally:
        sock.close()

    # ---------- Summary ----------

    print("\n----- Summary -----")

    loss = ((sent - received) / sent) * 100 if sent else 0
    print(f"{sent} sent, {received} received, {loss:.2f}% packet loss")

    print(f"DNS resolution: {dns_time:.2f} ms")

    if rtt_list:
        avg = sum(rtt_list) / len(rtt_list)

        print(f"rtt min/avg/max: {min(rtt_list):.2f}/{avg:.2f}/{max(rtt_list):.2f} ms")

        if len(rtt_list) >= 2:
            stddev = statistics.stdev(rtt_list)
            # jitter = mean absolute difference between consecutive RTTs
            jitter = sum(abs(b - a) for a, b in zip(rtt_list, rtt_list[1:])) / (len(rtt_list) - 1)
            print(f"stddev: {stddev:.2f} ms, jitter: {jitter:.2f} ms")

        if len(rtt_list) >= PERCENTILE_MIN_SAMPLES:
            print(
                f"percentiles p50/p95/p99: "
                f"{percentile(rtt_list,50):.2f}/"
                f"{percentile(rtt_list,95):.2f}/"
                f"{percentile(rtt_list,99):.2f} ms"
            )
    else:
        print("No successful responses")

    return EXIT_OK if sent and received == sent else EXIT_LOSS


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(EXIT_LOSS)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(EXIT_ERROR)
        
 
#
# ToDo
# - Add customization for Options Template
# - Add support for TCP 
# - have commandline arguments for template to use
# ########################
# - references
# https://docs.python.org/3/library/socket.html#functions
# https://docs.python.org/3/library/asyncio.html
# https://docs.python.org/3/library/uuid.html
# https://docs.python.org/3/library/time.html#time.monotonic
# https://docs.python.org/3/library/argparse.html#module-argparse
# https://docs.python.org/3.12/library/statistics.html
# 
