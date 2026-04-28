import asyncio
import socket
import time
import uuid
import sys
import argparse
import signal

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


# SIP OPTIONS request template
OPTIONS_TEMPLATE = (
    "OPTIONS sip:{server}:{port} SIP/2.0\r\n"
    "Via: SIP/2.0/UDP {lan_ip}:{lan_port};branch=z9hG4bK{branch};rport\r\n"
    "Max-Forwards: 70\r\n"
    "To: sip:ping@{server}:{port}\r\n"
    "From: sip:ping@{server}:{port};tag=73686572617A\r\n"
    "Call-ID: {call_id}\r\n"
    "CSeq: {cseq} OPTIONS\r\n"
    "Contact: sip:{lan_ip}:{lan_port}\r\n"
    "Content-Length: 0\r\n"
    "\r\n"
)


# Better way to get local ip. 
def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.4.4", 53))
        return sock.getsockname()[0]
    finally:
        sock.close()


# Create and reuse one socket
def create_socket(timeout):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    sock.bind(("0.0.0.0", 0))
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


def send_and_receive(sock, message, ip, port):
    sock.sendto(message.encode(), (ip, port))
    return sock.recvfrom(1024)


async def send_options_request(sock, ip, host, port, timeout, lan_ip):
    try:
        loop = asyncio.get_running_loop()

        now = int(time.time() * 1000)
        branch = str(now)
        call_id = str(uuid.uuid4())
        cseq = str(now)

        lan_port = sock.getsockname()[1]

        request = OPTIONS_TEMPLATE.format(
            server=host,   # keep hostname in SIP headers
            port=port,
            lan_ip=lan_ip,
            lan_port=lan_port,
            branch=branch,
            call_id=call_id,
            cseq=cseq
        )

        start = time.monotonic()

        try:
            await asyncio.wait_for(
                loop.run_in_executor(
                    None, send_and_receive, sock, request, ip, port
                ),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            print("Request timed out")
            return None
        except socket.timeout:
            print("Socket timeout")
            return None

        rtt = (time.monotonic() - start) * 1000
        print(f"Reply received: {rtt:.2f} ms")
        return rtt

    except Exception as e:
        print(f"Request error: {e}")
        return None


# ---------- Main ----------

async def main():
    parser = argparse.ArgumentParser(
        description="Sends UDP SIP options to an endpoint and shows DNS resolution time, round-trip-time and packet loss percentage ",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("destination", help="SIP server IP/hostname")
    parser.add_argument("-c", "--count", type=int, default=5)
    parser.add_argument("-t", "--timeout", type=float, default=3)

    args = parser.parse_args()

    host = args.destination
    num_requests = args.count
    timeout = args.timeout

    lan_ip = get_local_ip()

    # DNS resolution
    ip, dns_time = resolve_target(host)

    if ip is None:
        print("DNS resolution failed")
        return

    sock = create_socket(timeout)

    print(f"\nSending SIP Option to: {host} ({ip})")
    print(f"DNS resolution time: {dns_time:.2f} ms")
    #print(f"Local IP: {lan_ip}")
    print(f"Requests: {num_requests}, Timeout: {timeout}s\n")

    sent = 0
    received = 0
    rtt_list = []

    try:
        for _ in range(num_requests):
            rtt = await send_options_request(sock, ip, host, SIP_PORT, timeout, lan_ip)

            sent += 1
            if rtt is not None:
                received += 1
                rtt_list.append(rtt)

            await asyncio.sleep(REQUEST_INTERVAL)

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

        print(
            f"percentiles p50/p95/p99: "
            f"{percentile(rtt_list,50):.2f}/"
            f"{percentile(rtt_list,95):.2f}/"
            f"{percentile(rtt_list,99):.2f} ms"
        )
    else:
        print("No successful responses")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        
 
#
# ToDo
# - Add customization for Options Template
# - Add support for TCP 
# - have commandline arguments for template to use, add response validation  
# ########################
# - references
# https://docs.python.org/3/library/socket.html#functions
# https://docs.python.org/3/library/asyncio.html
# https://docs.python.org/3/library/uuid.html
# https://docs.python.org/3/library/time.html#time.monotonic
# https://docs.python.org/3/library/argparse.html#module-argparse
# 