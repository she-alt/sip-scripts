# sip-options

A small SIP "ping" tool. It sends SIP `OPTIONS` requests over UDP to a server and reports DNS resolution time, round-trip time, packet loss, jitter and percentiles (with enough responses). Replies are validated against the request with proper exit code.

Single file, standard library only.

## Requirements

- Python 3.8 or newer (developed and tested on 3.12)
- No third-party packages

## Quick start

```bash
git clone https://github.com/she-alt/sip-scripts.git
cd sip-scripts
python3 sip-options.py sip.example.com
```

## Usage

```
python3 sip-options.py [-h] [-p PORT] [-c COUNT] [-t TIMEOUT] [-i INTERVAL] [-v] destination
```

| Option | Default | Description |
|---|---|---|
| `destination` | – | SIP server IP or hostname, optionally `host:port` |
| `-p`, `--port` | `5060` | Destination port (a port in `destination` takes precedence) |
| `-c`, `--count` | `5` | Number of requests to send |
| `-t`, `--timeout` | `3` | Seconds to wait for a reply to each request |
| `-i`, `--interval` | `1` | Seconds between requests (measured from send to send) |
| `-v`, `--verbose` | off | Print the full request and response messages |

Examples:

```bash
python3 sip-options.py 203.0.113.10
python3 sip-options.py sbc.example.com:5080 -c 20 -i 0.5
python3 sip-options.py sbc.example.com -p 5080 -t 2 -v
```

## Example output

```
Sending SIP Option to: sip.example.com (203.0.113.10), port 5060
DNS resolution time: 9.81 ms
Requests: 5, Timeout: 3.0s

Reply received: 200 OK - 51.86 ms
Reply received: 200 OK - 51.18 ms
Reply received: 200 OK - 51.27 ms
Request timed out
Reply received: 200 OK - 50.94 ms

----- Summary -----
5 sent, 4 received, 20.00% packet loss
DNS resolution: 9.81 ms
rtt min/avg/max: 50.94/51.31/51.86 ms
stddev: 0.38 ms, jitter: 0.41 ms
```

Percentiles (`p50/p95/p99`) are only printed with 20 or more replies, since they aren't meaningful on small samples.

## Response validation

A packet only counts as a reply if it is a SIP response whose **Call-ID**, **CSeq** (number and method) and top **Via branch** match the request that was just sent. Everything else is ignored.

- `1xx` provisional responses (e.g. `100 Trying`) are ignored while waiting for the final response.
- Any final response (`2xx`–`6xx`) counts as a reply and its status is shown. A `404` or `503` still means the server answered, so it is not counted as loss.
- The UDP socket is `connect()`ed to the target, so packets from other sources are dropped, and an ICMP port-unreachable is reported as `Port unreachable` instead of a timeout.

## Verbose mode

`-v` prints each request and each matching response in full, plus a one-line note for any packet that was ignored and why. Example request:

```
>>> Request sent
    OPTIONS sip:sip.example.com:5060 SIP/2.0
    Via: SIP/2.0/UDP 192.0.2.2:44418;branch=z9hG4bK3f9a1c2e7b4d8a60;rport
    Max-Forwards: 70
    To: <sip:ping@sip.example.com:5060>
    From: <sip:ping@sip.example.com:5060>;tag=73686572617A
    Call-ID: 6f1c0d8e-3b52-4e0a-9a43-0c1d2e3f4a5b
    CSeq: 1 OPTIONS
    Contact: sip:192.0.2.2:44418
    User-Agent: sip-options
    Accept: application/sdp
    Content-Length: 0
```

All requests in one run share a Call-ID, and CSeq increments from 1.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Every request got a reply |
| `1` | At least one request got no reply (timeout, port unreachable, or interrupted with nothing sent) |
| `2` | The tool could not run: bad arguments, DNS failure, socket error, or an unexpected error |

Example monitoring check:

```bash
python3 sip-options.py sbc.example.com -c 3 -t 2 -i 0.5 > /dev/null || echo "SIP OPTIONS check failed"
```

Ctrl-C stops the run and prints the summary of what was sent so far.

## Notes and limitations

- UDP and IPv4 only.
- No retransmissions.
- The local address used in the `Via` and `Contact` headers is found by checking which interface would route to `8.8.4.4`. No traffic is sent there. The tool relies on `rport` for NAT, so replies are expected back to the source address and port of the request.

## To do

- Customizable OPTIONS template, selectable from the command line
- TCP support
- More testing