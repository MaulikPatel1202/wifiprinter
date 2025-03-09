
#!/usr/bin/env python3
import os
import sys
import subprocess
import platform
import socket

def debug_printer_setup():
    """Run diagnostics on the printer setup"""
    print("=== Printer Debugging Tool ===")
    
    # Check OS
    print(f"\nOperating System: {platform.system()} {platform.release()}")
    
    # Check for required tools
    if platform.system() == 'Darwin':  # macOS
        tools = ['lp', 'lpr', 'lpstat']
        for tool in tools:
            try:
                subprocess.run(['which', tool], check=True, capture_output=True)
                print(f"✅ {tool} is installed")
            except subprocess.SubprocessError:
                print(f"❌ {tool} is NOT found")
        
        # Check CUPS
        print("\nChecking CUPS status...")
        try:
            result = subprocess.run(['lpstat', '-p'], capture_output=True, text=True)
            print("Local printers:")
            print(result.stdout or "No printers found")
        except Exception as e:
            print(f"Error checking CUPS: {e}")
    
    # Check for default printer
    print("\nChecking default printer...")
    try:
        if platform.system() == 'Darwin':
            result = subprocess.run(['lpstat', '-d'], capture_output=True, text=True)
            print(result.stdout or "No default printer set")
    except Exception as e:
        print(f"Error checking default printer: {e}")
    
    # Network diagnostic
    print("\nRunning network diagnostics...")
    printer_ip = input("Enter printer IP address to test (leave blank to skip): ")
    if printer_ip:
        ports = [631, 80, 443, 515, 9100]  # Common printer ports
        for port in ports:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                result = s.connect_ex((printer_ip, port))
                if result == 0:
                    print(f"✅ Port {port} is OPEN")
                else:
                    print(f"❌ Port {port} is CLOSED")
                s.close()
            except Exception as e:
                print(f"❌ Error testing port {port}: {e}")
    
    # Try a test print if requested
    test_print = input("\nWould you like to attempt a test print? (y/n): ")
    if test_print.lower() == 'y':
        printer_name = input("Enter the exact printer name: ")
        if printer_name:
            # Create a test file
            test_file = os.path.join(os.path.dirname(__file__), "test_print.txt")
            with open(test_file, 'w') as f:
                f.write("This is a test print from the printer debugging tool.\n")
            
            print(f"Attempting to print to {printer_name}...")
            try:
                if platform.system() == 'Darwin':
                    cmd = ['lp', '-d', printer_name, test_file]
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    print(result.stdout)
                    if result.stderr:
                        print(f"Error: {result.stderr}")
            except Exception as e:
                print(f"Error sending test print: {e}")
            
            os.remove(test_file)

if __name__ == "__main__":
    debug_printer_setup()