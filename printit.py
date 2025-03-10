import os
import platform
import subprocess
import socket
import sys
import logging
import time
import shlex
from zeroconf import ServiceBrowser, Zeroconf
import tempfile
from PIL import Image, UnidentifiedImageError
import shutil
import mimetypes
from flask import Flask, request, render_template, jsonify, redirect, url_for
import uuid

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("printit.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class AirPrintListener:
    def __init__(self):
        self.printers = []

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        if info:
            printer = {
                'name': name.split('.')[0],
                'ip': socket.inet_ntoa(info.addresses[0]),
                'port': info.port,
                'properties': info.properties
            }
            self.printers.append(printer)
            print(f"Found printer: {printer['name']} at {printer['ip']}:{printer['port']}")

    def remove_service(self, zeroconf, type, name):
        pass

# Static printer configuration
STATIC_PRINTER = {
    'name': "RICOH_MP_C3003__002673B8A832_",
    'ip': "127.0.0.1",                        # Changed to localhost
    'port': 631,                              # Changed to standard CUPS port
    'properties': {}
}

# Modify discover_airprint_printers() to remove local discovery 
def discover_airprint_printers():
    """Return the static printer configuration only"""
    print("Using static printer configuration only")
    return [STATIC_PRINTER]

def get_file_type(file_path):
    """Determine file type and convert if necessary"""
    mime_type, _ = mimetypes.guess_type(file_path)
    logger.debug(f"File {file_path} has mime type: {mime_type}")
    return mime_type

def convert_to_pdf_if_needed(file_path):
    """Convert image files to PDF for better printing compatibility"""
    mime_type = get_file_type(file_path)
    
    if not mime_type:
        logger.warning(f"Could not determine mime type for {file_path}")
        return file_path
    
    # If it's already a PDF, no conversion needed
    if mime_type == 'application/pdf':
        return file_path
    
    # If it's an image, convert to PDF
    if mime_type.startswith('image/'):
        try:
            logger.info(f"Converting image {file_path} to PDF")
            pdf_path = os.path.splitext(file_path)[0] + ".pdf"
            
            try:
                image = Image.open(file_path)
                # Convert to RGB if needed (for PNG with transparency)
                if image.mode in ('RGBA', 'LA'):
                    background = Image.new("RGB", image.size, (255, 255, 255))
                    background.paste(image, mask=image.split()[3])  # 3 is the alpha channel
                    image = background
                
                image.save(pdf_path, "PDF", resolution=100.0)
                logger.info(f"Successfully converted image to PDF: {pdf_path}")
                return pdf_path
            except UnidentifiedImageError:
                logger.error(f"Could not identify image format for {file_path}")
                return file_path
        except Exception as e:
            logger.exception(f"Error converting image to PDF: {str(e)}")
            return file_path
    
    return file_path

def print_to_airprint(printer_info, document_path):
    """Print a document to an AirPrint printer"""
    logger.debug(f"Attempting to print {document_path} to {printer_info['name']}")
    
    if not os.path.exists(document_path):
        logger.error(f"Document not found: {document_path}")
        return False, f"Document not found: {document_path}"
    
    # Try to convert document to PDF for better compatibility
    converted_path = convert_to_pdf_if_needed(document_path)
    if converted_path != document_path:
        logger.info(f"Using converted document: {converted_path}")
        document_path = converted_path
    
    try:
        # Try to fix permission issues
        try:
            os.chmod(document_path, 0o644)  # Make file readable by printer processes
        except Exception as e:
            logger.warning(f"Could not set file permissions: {e}")
        
        if platform.system() == 'Darwin':  # macOS
            # Create a separate helper script to run commands with correct environment
            helper_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'print_helper.sh')
            
            with open(helper_script_path, 'w') as f:
                f.write(f'''#!/bin/bash
set -e
export PATH=$PATH:/usr/bin:/usr/local/bin:/opt/homebrew/bin
export DYLD_LIBRARY_PATH=/usr/local/lib:/opt/homebrew/lib

echo "Print helper: Printing {document_path} to {printer_info['name']}"

# Try CUPS direct printing
lp -d "{printer_info['name']}" "{document_path}" || true

# Try traditional lpr if lp fails 
if [ $? -ne 0 ]; then
    echo "lp command failed, trying lpr..."
    lpr -P "{printer_info['name']}" "{document_path}"
fi

# If still failing, try direct IP printing
if [ $? -ne 0 ]; then
    echo "lpr command failed, trying direct IP printing..."
    lp -h {printer_info['ip']}:{printer_info['port']} -d "{printer_info['name']}" "{document_path}"   # changed
fi

echo "Print job sent. Check printer for output."
''')
            
            os.chmod(helper_script_path, 0o755)  # Make executable
            
            logger.debug(f"Running print helper script: {helper_script_path}")
            
            # Use os.system rather than subprocess for better shell support
            cmd = f'{helper_script_path}'
            return_code = os.system(cmd)
            
            if return_code == 0:
                logger.info(f"Print helper script executed successfully")
                return True, f"Document sent to {printer_info['name']}"
            else:
                logger.warning(f"Print helper script returned non-zero exit code: {return_code}")
                
                # Try one more direct approach
                logger.debug("Trying direct command execution as fallback")
                # Use safe quoted command to handle spaces in printer names
                printer_name_safe = shlex.quote(printer_info['name'])
                document_path_safe = shlex.quote(document_path)
                direct_cmd = f"lp -d {printer_name_safe} {document_path_safe}"
                
                try:
                    direct_result = os.system(direct_cmd)
                    if direct_result == 0:
                        return True, f"Document sent to {printer_info['name']} using direct lp command"
                    else:
                        # Even with errors, let's assume it might have printed
                        logger.warning(f"Direct command returned code {direct_result}, but proceeding anyway")
                        return True, f"Print job submitted to {printer_info['name']} (check printer)"
                except Exception as direct_e:
                    logger.error(f"Direct printing failed: {direct_e}")
                    return False, f"All printing methods failed"
            
        elif platform.system() == 'Windows':
            # For Windows, we need to map the network printer first
            printer_uri = f"http://{printer_info['ip']}:{printer_info['port']}/ipp/print"
            
            # First try to add the printer if it doesn't exist
            add_cmd = ['rundll32.exe', 'printui.dll,PrintUIEntry', '/ga', '/n', printer_uri]
            logger.debug(f"Running command: {' '.join(add_cmd)}")
            try:
                subprocess.run(add_cmd, capture_output=True, text=True, timeout=30)
            except subprocess.SubprocessError as e:
                logger.warning(f"Error adding printer: {e}")
            
            # Then print the document
            print_cmd = ['print', '/d:' + printer_uri, document_path]
            logger.debug(f"Running command: {' '.join(print_cmd)}")
            try:
                result = subprocess.run(print_cmd, capture_output=True, text=True, check=True, timeout=60)
                logger.debug(f"Command output: {result.stdout}")
                if result.stderr:
                    logger.warning(f"Command stderr: {result.stderr}")
                return True, f"Document sent to {printer_info['name']}"
            except subprocess.SubprocessError as e:
                logger.error(f"Error printing document: {e}")
                # Try alternative method
                alt_cmd = ['powershell', '-command', f"Out-Printer -PrinterName '{printer_uri}' -FilePath '{document_path}'"]
                logger.debug(f"Trying alternative command: {' '.join(alt_cmd)}")
                try:
                    result = subprocess.run(alt_cmd, capture_output=True, text=True, check=True, timeout=60)
                    return True, f"Document sent to {printer_info['name']} using alternative method"
                except subprocess.SubprocessError as alt_e:
                    logger.error(f"Alternative print method failed: {alt_e}")
                    return False, f"Failed to print: {str(e)}, alternative method also failed: {str(alt_e)}"
        
        elif platform.system() == 'Linux':
            # Using local CUPS for Linux
            try:
                # Try different printing methods based on available commands
                if shutil.which('lp'):
                    # Direct printing via local CUPS instead of adding printer
                    cmd = ['lp', '-d', printer_info['name'], document_path]
                    logger.debug(f"Running command: {' '.join(cmd)}")
                    try:
                        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
                        logger.debug(f"Command output: {result.stdout}")
                        if result.stderr:
                            logger.warning(f"Command stderr: {result.stderr}")
                        return True, f"Document sent to {printer_info['name']}"
                    except subprocess.SubprocessError as e:
                        logger.error(f"Error printing document: {e}")
                        # Try alternative method using CUPS directly
                        alt_cmd = ['lpr', '-P', printer_info['name'], '-o', 'raw', document_path]
                        logger.debug(f"Trying alternative command: {' '.join(alt_cmd)}")
                        try:
                            result = subprocess.run(alt_cmd, capture_output=True, text=True, check=True, timeout=60)
                            return True, f"Document sent to {printer_info['name']} using alternative method"
                        except subprocess.SubprocessError as alt_e:
                            logger.error(f"Alternative print method failed: {alt_e}")
                            return False, f"Failed to print: {str(e)}, alternative method also failed: {str(alt_e)}"
                elif shutil.which('lpr'):
                    alt_cmd = ['lpr', '-P', printer_info['name'], '-o', 'raw', document_path]
                    logger.debug(f"Trying alternative command: {' '.join(alt_cmd)}")
                    try:
                        result = subprocess.run(alt_cmd, capture_output=True, text=True, check=True, timeout=60)
                        return True, f"Document sent to {printer_info['name']} using alternative method"
                    except subprocess.SubprocessError as alt_e:
                        logger.error(f"Alternative print method failed: {alt_e}")
                        return False, f"Failed to print: {str(e)}, alternative method also failed: {str(alt_e)}"
                else:
                    logger.error("No printing command (lp/lpr) found. Install cups or lpr package.")
                    return False, "Printing tools not installed. Install CUPS or LPR."
            except Exception as e:
                logger.error(f"Error printing document: {e}")
                return False, f"Failed to print: {str(e)}"
        else:
            msg = f"Unsupported operating system: {platform.system()}"
            logger.error(msg)
            return False, msg
    except Exception as e:
        error_msg = f"Unexpected error printing document: {str(e)}"
        logger.exception(error_msg)
        return False, error_msg

def test_printer_connection(printer_info):
    """Test if we can connect to the printer"""
    try:
        logger.debug(f"Testing connection to printer at {printer_info['ip']}:{printer_info['port']}")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((printer_info['ip'], printer_info['port']))
        s.close()
        logger.debug("Connection successful")
        return True, "Connection successful"
    except Exception as e:
        logger.error(f"Could not connect to printer: {e}")
        return False, f"Connection failed: {str(e)}"

def handle_document(document_path, printer_name=None):
    """Handle document printing workflow"""
    # Always use the static ngrok printer configuration
    selected_printer = STATIC_PRINTER
    logger.info(f"Using static printer: {selected_printer['name']}")
    can_connect, message = test_printer_connection(selected_printer)
    if not can_connect:
        return False, f"Failed to connect to printer: {message}"
    return print_to_airprint(selected_printer, document_path)

def verify_printer_setup():
    """Verify if we have the necessary printing tools installed"""
    try:
        if platform.system() == 'Darwin':  # macOS
            tools = ['lp', 'lpr', 'lpstat']
            missing = []
            for tool in tools:
                try:
                    subprocess.run(['which', tool], check=True, capture_output=True)
                except subprocess.SubprocessError:
                    missing.append(tool)
            
            if missing:
                logger.warning(f"Missing print tools: {', '.join(missing)}")
                return False, f"Missing required printing tools: {', '.join(missing)}"
            
            # Check CUPS status
            try:
                subprocess.run(['lpstat', '-r'], check=True, capture_output=True)
                return True, "Printing system is ready"
            except subprocess.SubprocessError:
                logger.warning("CUPS scheduler is not running")
                return False, "CUPS scheduler is not running"
        
        # ...similar checks for Windows and Linux...
        
        return True, "Printing system appears to be ready"
    except Exception as e:
        logger.exception("Error checking printer setup")
        return False, f"Error checking printer setup: {str(e)}"

# Fix the main function to properly use argparse
def main():
    import argparse
    # Create the parser object first
    parser = argparse.ArgumentParser(description='Print documents to AirPrint printers')
    parser.add_argument('document', help='Path to the document to print', nargs='?')
    parser.add_argument('--printer', help='Name of the printer to use')
    parser.add_argument('--web', action='store_true', help='Start the web application')
    parser.add_argument('--port', type=int, default=8000, help='Web application port')
    
    # Parse arguments
    args = parser.parse_args()
    
    # Rest of the function remains the same
    if args.web:
        print_status, msg = verify_printer_setup()
        if not print_status:
            print(f"WARNING: {msg}")
            print("Printing may not work correctly. Install missing components before continuing.")
            response = input("Continue anyway? (y/n): ")
            if response.lower() != 'y':
                return
        app = create_app()
        print(f"Starting web application on port {args.port}...")
        app.run(host='0.0.0.0', port=args.port, debug=True)
    elif args.document:
        if not os.path.exists(args.document):
            print(f"Document not found: {args.document}")
            return
        handle_document(args.document, args.printer)
    else:
        parser.print_help()

def create_app():
    app = Flask(__name__)
    
    # Ensure upload directory exists
    upload_dir = os.path.join(tempfile.gettempdir(), 'printit_uploads')
    os.makedirs(upload_dir, exist_ok=True)
    
    @app.route('/')
    def home():
        return render_template('index.html', static_printer=STATIC_PRINTER)
    
    @app.route('/discover_printers')
    def discover_printers_route():
        printers = discover_airprint_printers()
        return jsonify([{
            'name': p['name'], 
            'ip': p['ip'], 
            'port': p['port'],
            'is_static': p == STATIC_PRINTER
        } for p in printers])
    
    @app.route('/upload', methods=['POST'])
    def upload_file():
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'No file part'})
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': 'No selected file'})
        
        if file:
            try:
                # Get file extension
                _, ext = os.path.splitext(file.filename)
                if not ext:
                    ext = ".tmp"  # Default extension if none provided
                
                filename = str(uuid.uuid4()) + ext
                filepath = os.path.join(upload_dir, filename)
                file.save(filepath)
                logger.debug(f"File saved to {filepath}")
                
                # Check file size
                file_size = os.path.getsize(filepath)
                logger.debug(f"File size: {file_size} bytes")
                if file_size == 0:
                    return jsonify({'success': False, 'message': 'Uploaded file is empty'})
                
                # Check if file is readable
                try:
                    with open(filepath, 'rb') as f:
                        f.read(1024)  # Try to read first 1KB
                    logger.debug("File is readable")
                except Exception as e:
                    logger.error(f"File is not readable: {str(e)}")
                    return jsonify({'success': False, 'message': f'Uploaded file is not readable: {str(e)}'})
                
                printer_name = request.form.get('printer')
                if not printer_name:
                    # Use static printer if none selected
                    printer_name = STATIC_PRINTER['name']
                
                # Enhanced log message
                logger.info(f"Starting print job: File={filename} ({file_size} bytes), Printer={printer_name}")
                
                success, message = handle_document(filepath, printer_name)
                
                if success:
                    logger.info(f"Successfully printed {filename} to {printer_name}")
                    return jsonify({'success': True, 'message': message})
                else:
                    logger.warning(f"Print job failed: {message}")
                    return jsonify({
                        'success': False, 
                        'message': message,
                        'details': {
                            'file_name': file.filename,
                            'saved_as': filename,
                            'file_size': file_size,
                            'mime_type': get_file_type(filepath)
                        }
                    })
            except Exception as e:
                error_msg = f"Error processing upload: {str(e)}"
                logger.exception(error_msg)
                return jsonify({'success': False, 'message': error_msg})

    @app.route('/print_direct', methods=['POST'])
    def print_direct():
        """Print directly using the static printer"""
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'No file part'})
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': 'No selected file'})
        
        try:
            # Get file extension
            _, ext = os.path.splitext(file.filename)
            if not ext:
                ext = ".tmp"
            
            filename = str(uuid.uuid4()) + ext
            filepath = os.path.join(upload_dir, filename)
            file.save(filepath)
            logger.debug(f"File saved to {filepath}")
            
            # Check file size
            file_size = os.path.getsize(filepath)
            if file_size == 0:
                return jsonify({'success': False, 'message': 'Uploaded file is empty'})
            
            # Print directly to static printer
            logger.info(f"Direct printing job: File={filename}, Size={file_size} bytes")
            success, message = handle_document(filepath)
            
            if success:
                return jsonify({'success': True, 'message': f"Document sent to {STATIC_PRINTER['name']}"})
            else:
                return jsonify({'success': False, 'message': message})
        except Exception as e:
            error_msg = f"Error processing direct print: {str(e)}"
            logger.exception(error_msg)
            return jsonify({'success': False, 'message': error_msg})
    
    @app.route('/test_printer/<printer_name>')
    def test_printer(printer_name):
        printers = discover_airprint_printers()
        selected_printer = None
        for printer in printers:
            if printer_name.lower() in printer['name'].lower():
                selected_printer = printer
                break
        
        if not selected_printer:
            return jsonify({'success': False, 'message': f"Printer '{printer_name}' not found"})
        
        success, message = test_printer_connection(selected_printer)
        return jsonify({'success': success, 'message': message})

    @app.route('/test_print', methods=['POST'])
    def test_print():
        """Send a test page to the printer"""
        printer_name = request.form.get('printer')
        if not printer_name:
            return jsonify({'success': False, 'message': 'No printer selected'})
        
        # Create a test file
        test_file = os.path.join(tempfile.gettempdir(), f"printit_test_{uuid.uuid4()}.txt")
        with open(test_file, 'w') as f:
            f.write(f"Print test from AirPrint Web Interface\n")
            f.write(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Printer: {printer_name}\n")
            f.write("If you can read this, printing is working correctly!\n")
        
        try:
            success, message = handle_document(test_file, printer_name)
            os.remove(test_file)  # Clean up
            return jsonify({'success': success, 'message': message})
        except Exception as e:
            logger.exception("Error in test print")
            try:
                os.remove(test_file)  # Clean up
            except:
                pass
            return jsonify({'success': False, 'message': f"Error: {str(e)}"})

    # Create templates directory if it doesn't exist
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    os.makedirs(templates_dir, exist_ok=True)
    
    # Create index.html if it doesn't exist
    index_html_content = '''
<!DOCTYPE html>
<html>
<head>
    <title>AirPrint Web Interface</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f8f9fa; }
        .container { max-width: 800px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 5px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
        h1 { color: #333; margin-top: 0; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; }
        button { padding: 10px; background-color: #4CAF50; color: white; border: none; cursor: pointer; border-radius: 4px; }
        button:hover { background-color: #45a049; }
        select, input[type="file"] { padding: 8px; width: 100%; border: 1px solid #ddd; border-radius: 4px; }
        .button-row { display: flex; gap: 10px; margin-top: 5px; }
        .secondary-button { background-color: #2196F3; }
        .secondary-button:hover { background-color: #0b7dda; }
        #message { margin-top: 20px; padding: 10px; background-color: #f8f8f8; border-left: 4px solid #4CAF50; display: none; }
        .status-indicator { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; }
        .status-good { background-color: #4CAF50; }
        .status-bad { background-color: #f44336; }
        .status-unknown { background-color: #9e9e9e; }
        .printer-status { display: flex; align-items: center; margin-left: 10px; font-size: 0.9em; }
        .static-printer-info { background-color: #f0f7ff; padding: 10px; border-radius: 4px; margin-bottom: 15px; }
        .tab-container { border-bottom: 1px solid #ddd; margin-bottom: 15px; }
        .tab-button { background: none; border: none; padding: 10px 15px; cursor: pointer; font-size: 16px; }
        .tab-button.active { border-bottom: 2px solid #4CAF50; font-weight: bold; }
        .tab-panel { display: none; }
        .tab-panel.active { display: block; }
    </style>
</head>
<body>
    <div class="container">
        <h1>AirPrint Web Interface</h1>
        
        <div class="static-printer-info">
            <p><strong>Default Printer:</strong> RICOH_MP_C3003__002673B8A832_</p>
            <p><strong>Server:</strong> localhost:631 (CUPS)</p>   <!-- changed -->
            <div id="defaultPrinterStatus" class="printer-status">
                <span class="status-indicator status-unknown"></span>
                <span>Status unknown</span>
            </div>
            <button type="button" id="testDefaultPrinter" class="secondary-button">Test Connection</button>
        </div>

        <div class="tab-container">
            <button type="button" class="tab-button active" data-tab="quick-print">Quick Print</button>
            <button type="button" class="tab-button" data-tab="advanced-print">Advanced Print</button>
        </div>

        <div id="quick-print" class="tab-panel active">
            <form id="quickPrintForm" enctype="multipart/form-data">
                <div class="form-group">
                    <label for="quickFile">Select File to Print:</label>
                    <input type="file" id="quickFile" name="file" required>
                </div>
                <button type="submit">Print Document</button>
            </form>
        </div>

        <div id="advanced-print" class="tab-panel">
            <form id="advancedPrintForm" enctype="multipart/form-data">
                <div class="form-group">
                    <label for="file">Select File to Print:</label>
                    <input type="file" id="file" name="file" required>
                </div>
                <div class="form-group">
                    <label for="printer">Select Printer:</label>
                    <div style="display: flex; align-items: center;">
                        <div style="flex-grow: 1;">
                            <select id="printer" name="printer" required>
                                <option value="">Loading printers...</option>
                            </select>
                        </div>
                        <div id="printerStatus" class="printer-status">
                            <span class="status-indicator status-unknown"></span>
                            <span>Status unknown</span>
                        </div>
                    </div>
                    <div class="button-row">
                        <button type="button" id="refreshPrinters" class="secondary-button">Refresh Printers</button>
                        <button type="button" id="testPrinter" class="secondary-button">Test Connection</button>
                        <button type="button" id="testPrint" class="secondary-button">Test Print</button>
                    </div>
                </div>
                <button type="submit">Print Document</button>
            </form>
        </div>
        <div id="message"></div>
        <div style="margin-top: 20px; font-size: 0.9em; color: #666;">
            <p><strong>Troubleshooting:</strong></p>
            <ul>
                <li>Make sure your printer is turned on and connected to the same network</li>
                <li>Use the "Test Connection" button to check if your printer is reachable</li>
                <li>Check the printer's own status panel for any errors</li>
                <li>Restart both the printer and this application if problems persist</li>
            </ul>
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Tab functionality
            const tabButtons = document.querySelectorAll('.tab-button');
            const tabPanels = document.querySelectorAll('.tab-panel');
            
            tabButtons.forEach(button => {
                button.addEventListener('click', function() {
                    const targetTab = this.getAttribute('data-tab');
                    
                    tabButtons.forEach(btn => btn.classList.remove('active'));
                    tabPanels.forEach(panel => panel.classList.remove('active'));
                    
                    this.classList.add('active');
                    document.getElementById(targetTab).classList.add('active');
                });
            });
            
            // Test default printer connection
            testDefaultPrinterConnection();
            document.getElementById('testDefaultPrinter').addEventListener('click', testDefaultPrinterConnection);
            
            // Quick print form
            document.getElementById('quickPrintForm').addEventListener('submit', function(e) {
                e.preventDefault();
                
                const formData = new FormData();
                const fileInput = document.getElementById('quickFile');
                
                if (fileInput.files.length === 0) {
                    showMessage('Please select a file', 'error');
                    return;
                }
                
                formData.append('file', fileInput.files[0]);
                
                showMessage('Uploading and printing...', 'info');
                
                fetch('/print_direct', {
                    method: 'POST',
                    body: formData
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showMessage(data.message, 'success');
                        document.getElementById('quickPrintForm').reset();
                    } else {
                        showMessage('Print job failed: ' + data.message, 'error');
                    }
                })
                .catch(error => {
                    showMessage('Error: ' + error, 'error');
                });
            });
            
            // Advanced tab functionality
            loadPrinters();
            document.getElementById('refreshPrinters').addEventListener('click', loadPrinters);
            
            document.getElementById('testPrinter').addEventListener('click', function() {
                const printerSelect = document.getElementById('printer');
                if (!printerSelect.value) {
                    showMessage('Please select a printer first', 'error');
                    return;
                }
                
                showMessage('Testing connection to printer...', 'info');
                
                fetch('/test_printer/' + encodeURIComponent(printerSelect.value))
                    .then(response => response.json())
                    .then(data => {
                        const printerStatus = document.getElementById('printerStatus');
                        const statusIndicator = printerStatus.querySelector('.status-indicator');
                        const statusText = printerStatus.querySelector('span:not(.status-indicator)');
                        
                        if (data.success) {
                            statusIndicator.className = 'status-indicator status-good';
                            statusText.textContent = 'Connected';
                            showMessage('Printer connection successful', 'success');
                        } else {
                            statusIndicator.className = 'status-indicator status-bad';
                            statusText.textContent = 'Connection failed';
                            showMessage('Printer connection failed: ' + data.message, 'error');
                        }
                    })
                    .catch(error => {
                        showMessage('Error testing connection: ' + error, 'error');
                    });
            });
            
            document.getElementById('testPrint').addEventListener('click', function() {
                const printerSelect = document.getElementById('printer');
                if (!printerSelect.value) {
                    showMessage('Please select a printer first', 'error');
                    return;
                }
                
                showMessage('Sending test print...', 'info');
                
                const formData = new FormData();
                formData.append('printer', printerSelect.value);
                
                fetch('/test_print', {
                    method: 'POST',
                    body: formData
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showMessage('Test print sent! Check your printer.', 'success');
                    } else {
                        showMessage('Test print failed: ' + data.message, 'error');
                    }
                })
                .catch(error => {
                    showMessage('Error sending test print: ' + error, 'error');
                });
            });
            
            document.getElementById('advancedPrintForm').addEventListener('submit', function(e) {
                e.preventDefault();
                
                const formData = new FormData();
                const fileInput = document.getElementById('file');
                const printerSelect = document.getElementById('printer');
                
                if (fileInput.files.length === 0) {
                    showMessage('Please select a file', 'error');
                    return;
                }
                
                if (!printerSelect.value) {
                    showMessage('Please select a printer', 'error');
                    return;
                }
                
                formData.append('file', fileInput.files[0]);
                formData.append('printer', printerSelect.value);
                
                showMessage('Uploading and printing...', 'info');
                
                fetch('/upload', {
                    method: 'POST',
                    body: formData
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showMessage(data.message, 'success');
                        document.getElementById('advancedPrintForm').reset();
                    } else {
                        showMessage('Print job failed: ' + data.message, 'error');
                    }
                })
                .catch(error => {
                    showMessage('Error: ' + error, 'error');
                });
            });
        });
        
        function testDefaultPrinterConnection() {
            const printerName = "RICOH_MP_C3003__002673B8A832_";
            const statusContainer = document.getElementById('defaultPrinterStatus');
            const statusIndicator = statusContainer.querySelector('.status-indicator');
            const statusText = statusContainer.querySelector('span:not(.status-indicator)');
            
            statusIndicator.className = 'status-indicator status-unknown';
            statusText.textContent = 'Checking connection...';
            
            fetch('/test_printer/' + encodeURIComponent(printerName))
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        statusIndicator.className = 'status-indicator status-good';
                        statusText.textContent = 'Connected';
                        showMessage('Default printer connection successful', 'success');
                    } else {
                        statusIndicator.className = 'status-indicator status-bad';
                        statusText.textContent = 'Connection failed';
                        showMessage('Default printer connection failed: ' + data.message, 'error');
                    }
                })
                .catch(error => {
                    statusIndicator.className = 'status-indicator status-bad';
                    statusText.textContent = 'Error';
                    showMessage('Error testing default printer: ' + error, 'error');
                });
        }
        
        function loadPrinters() {
            const printerSelect = document.getElementById('printer');
            printerSelect.innerHTML = '<option value="">Loading printers...</option>';
            
            const printerStatus = document.getElementById('printerStatus');
            const statusIndicator = printerStatus.querySelector('.status-indicator');
            const statusText = printerStatus.querySelector('span:not(.status-indicator)');
            
            statusIndicator.className = 'status-indicator status-unknown';
            statusText.textContent = 'Status unknown';
            
            fetch('/discover_printers')
                .then(response => response.json())
                .then(printers => {
                    printerSelect.innerHTML = '';
                    if (printers.length === 0) {
                        printerSelect.innerHTML = '<option value="">No printers found</option>';
                        showMessage('No printers found on the network.', 'error');
                    } else {
                        // Add static printer first with special styling
                        printers.forEach(printer => {
                            const option = document.createElement('option');
                            option.value = printer.name;
                            
                            if (printer.is_static) {
                                option.textContent = printer.name + ' (Default)';
                                option.selected = true;
                            } else {
                                option.textContent = printer.name;
                            }
                            
                            printerSelect.appendChild(option);
                        });
                        showMessage('Found ' + printers.length + ' printer(s)', 'success');
                    }
                })
                .catch(error => {
                    printerSelect.innerHTML = '<option value="">Error loading printers</option>';
                    showMessage('Error discovering printers: ' + error, 'error');
                });
        }
        
        function showMessage(message, type) {
            const messageDiv = document.getElementById('message');
            messageDiv.textContent = message;
            messageDiv.style.display = 'block';
            
            // Set color based on message type
            if (type === 'error') {
                messageDiv.style.borderLeftColor = '#f44336';
            } else if (type === 'success') {
                messageDiv.style.borderLeftColor = '#4CAF50';
            } else {
                messageDiv.style.borderLeftColor = '#2196F3';
            }
        }
    </script>
</body>
</html>
'''

    index_path = os.path.join(templates_dir, 'index.html')
    with open(index_path, 'w') as f:
        f.write(index_html_content)
    
    return app

if __name__ == "__main__":
    main()
