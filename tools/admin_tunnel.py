"""Run locally to access management at http://127.0.0.1:8765/ over SSH."""
import select
import socketserver

from vps import connect


def main():
    client = connect()
    transport = client.get_transport()

    class Forward(socketserver.BaseRequestHandler):
        def handle(self):
            channel = transport.open_channel('direct-tcpip', ('127.0.0.1', 8765), self.request.getpeername())
            try:
                while True:
                    ready, _, _ = select.select([self.request, channel], [], [], 60)
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        (channel if source is self.request else self.request).sendall(data)
            finally:
                channel.close()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    try:
        with Server(('127.0.0.1', 8765), Forward) as server:
            print('KiiPeak admin: http://127.0.0.1:8765/ (SSH tunnel; Ctrl+C to close)', flush=True)
            server.serve_forever()
    finally:
        client.close()


if __name__ == '__main__':
    main()
