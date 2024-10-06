import asyncio
import socket
import time
import uuid
import sys
import argparse
import signal

###
'''
# Sends UDP SIP options to an endpoint and shows the round-trip-time and packet loss percentage.
# //SHAL 2024
###
'''

# Define the SIP port
SIP_PORT = 5060

# Request interval, time to wait between requests
REQUEST_INTERVAL = 1

# Define the number of requests to send
NUM_REQUESTS = 5

# Define socket recieve timeout
SOCK_TIMEOUT = 5

# SIP OPTIONS request template
OPTIONS_TEMPLATE = (
    "OPTIONS sip:{server}:{port} SIP/2.0\r\n"
    "Via: SIP/2.0/UDP {lan_ip}:{lan_port};branch=z9hG4bK4ce2.{branch};rport;alias\r\n"
    "Max-Forwards: 70\r\n"
    "To: sip:ping@{server}:{port}\r\n"
    "From: sip:ping@{server}:{port};tag=73686572617A\r\n"
    "Call-ID: {call_id}\r\n"
    "CSeq: {cseq} OPTIONS\r\n"
    "Contact: sip:{server}:{port}\r\n"
    "Accept: application/sdp\r\n"
    "Content-Length: 0\r\n"
    "\r\n"
)

async def send_options_request(SIP_SERVER, SIP_PORT, SOCK_TIMEOUT):
    try:
        # Create and bind UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", 0))
        sock.settimeout(SOCK_TIMEOUT)
        
        # Generate unique values for the SIP packet
        branch = cseq = str(int(time.time()))
        call_id = str(uuid.uuid4())
        lan_ip = socket.gethostbyname(socket.gethostname())
        lan_port = sock.getsockname()[1]
        
        # Format the SIP OPTIONS request
        request = OPTIONS_TEMPLATE.format(
            server=SIP_SERVER,
            port=SIP_PORT,
            lan_ip=lan_ip,
            lan_port=lan_port,
            branch=branch,
            call_id=call_id,
            cseq=cseq
        )

        # Send the request
        start_time = time.time()
        sock.sendto(request.encode(), (SIP_SERVER, SIP_PORT))

        # Receive the response
        response, _ = sock.recvfrom(1024)
        end_time = time.time()

        # Calculate RTT
        rtt = (end_time - start_time) * 1000  # Convert to milliseconds
        print(f"Reply received: {rtt:.2f}ms")

        return rtt

    except socket.gaierror:
        # Indicate issue with getaddressinfo
        print ("Error sending request: Unable to resolve hostname.")
        sys.exit()
    
    except KeyboardInterrupt:
        print("\nProgram interrupted by user. Shutting down...")
        sys.exit()
               
    except Exception as e:
        # Generic handler
        print(f"Error sending request: {e}")
        sys.exit(1)
            
    finally:
        sock.close()


async def main():
    total_rtt = 0
    total_sent_requests = 0
    total_successful_responses = 0
    total_failed_responses = 0

    # total arguments
    n = len(sys.argv)
    if not len(sys.argv) >= 1:
        #SIP_SERVER = sys.argv[1]
        print("No argument given. Destination is required")
        sys.exit(1)
    
    parser = argparse.ArgumentParser(
        description="Sends UDP SIP option packet to an endpoint and shows the round-trip-time and packet loss percentage.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("destination", help="URI/IP of the SIP device to send SIP Option")
    #parser.add_argument("--t", "--timeout", action="store_true", help="socket timeout in seconds")
    args = parser.parse_args()
    config = vars(args)

    if args.destination:
        SIP_SERVER = args.destination

    rtt_list = []

    print(f"Sending SIP OPTION request to {SIP_SERVER}")

    try:
        for i in range(NUM_REQUESTS):
            rtt = await send_options_request(SIP_SERVER, SIP_PORT, SOCK_TIMEOUT)
            if rtt is not None:
                total_rtt += rtt
                total_successful_responses += 1
                rtt_list.append(rtt)
            else:
                total_failed_responses += 1
            total_sent_requests += 1

                # Ensures non-blocking sleep when running async
            await asyncio.sleep(REQUEST_INTERVAL)

        if total_sent_requests > 0:
            average_rtt = total_rtt / total_successful_responses
            loss_percentage = ((total_sent_requests - total_successful_responses) / total_sent_requests) * 100
            print("\n----- Summary -----")
            print(f"{total_sent_requests} packets sent, {total_successful_responses} received, {loss_percentage:.2f}% packet loss")
            print(f"rtt min/max/avg: {min(rtt_list):.2f}/{max(rtt_list):.2f}/{average_rtt:.2f} ms")
        else:
            print("\nNo responses received.")

    except Exception as e:
        print(f'An error occurred: {e}')
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram interrupted by user. Shutting down...")
        sys.exit(0)

#
# ToDo
# - Add customization for Options Template
# - Add support for TCP 
# - have commandline arguments for number of packets, timeout, template to use, help and add validation  
# ########################
# - references
# https://docs.python.org/3/library/socket.html#functions
# https://docs.python.org/3/library/asyncio.html
# https://docs.python.org/3/library/uuid.html
#