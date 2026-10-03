"""Preview the research site locally, with consistent MIME types on Windows."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', type=int, default=8080)
args = parser.parse_args()
site = Path(__file__).resolve().parents[1] / 'docs'
SimpleHTTPRequestHandler.extensions_map.update({'.svg': 'image/svg+xml', '.js': 'text/javascript', '.css': 'text/css'})
handler = partial(SimpleHTTPRequestHandler, directory=str(site))
print(f'MatterMind preview: http://127.0.0.1:{args.port}', flush=True)
ThreadingHTTPServer(('127.0.0.1', args.port), handler).serve_forever()
