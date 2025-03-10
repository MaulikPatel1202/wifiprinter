# This file should be a simple handler, not trying to import from the main app
def handler(request):
    return {
        'statusCode': 200,
        'body': 'WifiPrinter API is running but requires a WSGI environment for full functionality',
        'headers': {
            'Content-Type': 'text/plain'
        }
    }