import asyncio
import socket
import time
import uuid
import sys
import argparse

###
'''
# Sends UDP SIP options to an endpoint and shows the round-trip-time and packet loss percentage.
# //SHAL 2022
###
'''

# Define the SIP server and port
SIP_SERVER = '<server uri>' 
SIP_PORT = 5060

# Request interval, time to wait between requests
REQUEST_INTERVAL = 0.5  

# Define the number of requests to send
NUM_REQUESTS = 10

# Define socket recieve timeout
SOCK_TIMEOUT = 5

# SIP OPTIONS request template
OPTIONS_TEMPLATE = (
    "OPTIONS sip:{server}:{port} SIP/2.0\r\n"
    "Via: SIP/2.0/UDP {lan_ip}:{lan_port};branch=z9hG4bK4ce2.{branch}\r\n"
    "Max-Forwards: 70\r\n"
    "To: <sip:{server}:{port}>\r\n"
    "From: <sip:random_sender@example.com>;tag=73686572617A\r\n"
    "Call-ID: {call_id}\r\n"
    "CSeq: {cseq} OPTIONS\r\n"
    "Contact: <sip:random_sender@example.com>\r\n"
    "Accept: application/sdp\r\n"
    "Content-Length: 0\r\n"
    "\r\n"
)

async def send_options_request():
    try:
        
        # create and bind udp socket
        soxet = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        soxet.bind(("0.0.0.0", 0))
        soxet.settimeout(SOCK_TIMEOUT)
        
        # generate unique values for the SIP packet
        branch = cseq = str(int(time.time()))
        call_id = str(uuid.uuid4())
        lan_ip = socket.gethostbyname(socket.gethostname())
        lan_port = soxet.getsockname()[1]  # getsockname is a method on the socket instance x, not socket module 
        
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
        
        # Create a UDP socket and send to the server
        soxet.sendto(request.encode(), (SIP_SERVER, SIP_PORT))

        # Receive the response 
        response, _ = soxet.recvfrom(1024)
        end_time = time.time()

        # Calculate RTT
        rtt = (end_time - start_time) * 1000  # Convert to milliseconds
        print(f"Reply recieved: {rtt:.2f}ms")

        # Close the socket
        soxet.close()
        return rtt

    except socket.gaierror:
        # indicats issue with getaddressinfo
        print ("Error sending request: Unable to resolve hostname.")
        sys.exit()
    
    except KeyboardInterrupt:
        print("\nCtrl+C pressed. Exiting gracefully.")
        sys.exit()
               
    except Exception as e:
        # generic handler
        print(f"Error sending request: {e}")
        sys.exit(1)
            
    finally:
        soxet.close()

async def main():
    total_rtt = 0
    total_sent_requests = 0
    total_successful_responses = 0
    total_failed_responses = 0
    
    rtt_list = []  
    print(f"Sending SIP OPTIONS request to {SIP_SERVER}")
    for i in range(NUM_REQUESTS):
        rtt = await send_options_request()
        if rtt is not None:
            total_rtt += rtt
            total_successful_responses += 1
            rtt_list.append(rtt)
        else:
            total_failed_responses += 1
        total_sent_requests += 1
        
        #  Ensures non-blocking sleep when running async
        await asyncio.sleep(REQUEST_INTERVAL) 
        #time.sleep(0.500)
        
          
    if total_sent_requests > 0:
        average_rtt = total_rtt / total_successful_responses
        loss_percentage = ((total_sent_requests - total_successful_responses) / total_sent_requests) * 100
        print("\n----- Summary -----")
        print(f"{total_sent_requests} packets sent, {total_successful_responses} recieved, {loss_percentage:.2f}% packet loss")
        print(f"rtt min/max/avg, {min(rtt_list):.2f}/{max(rtt_list):.2f}/{average_rtt:.2f} ms ")
    else:
        print("\nNo responses received.")

if __name__ == "__main__":
    asyncio.run(main())
    
#
# ToDo
# - Add customization for Options Template
# - have commandline arguments for endpooint, number ofpackets, timeout, template to use, help  
# - client based SIP Register testing
# ########################
# - references
# https://docs.python.org/3/library/socket.html#functions
# https://docs.python.org/3/library/asyncio.html
# https://docs.python.org/3/library/uuid.html
#
