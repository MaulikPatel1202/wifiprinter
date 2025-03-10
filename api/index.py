from http.server import BaseHTTPRequestHandler
import json

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        # Simple HTML response
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>WifiPrinter</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }
                .container { max-width: 800px; margin: 0 auto; }
                h1 { color: #333; }
                .note { background-color: #f8f9fa; padding: 15px; border-left: 4px solid #4CAF50; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>WifiPrinter Web Service</h1>
                <div class="note">
                    <p>This is a web service that enables printing to network printers.</p>
                    <p>Note: The full web interface is not available on this serverless platform.</p>
                    <p>For the complete interface with printing capabilities, please use the local deployment.</p>
                </div>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode())
        return

handler = Handler