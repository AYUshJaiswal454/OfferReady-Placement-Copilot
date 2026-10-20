"""Tiny local web server with deliberately good and broken pages for live-link tests."""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GOOD = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>DevConnect – Q&A for student developers</title></head><body style="font-family:sans-serif;margin:0">
<div id="root"><header><h1>DevConnect</h1><p>Ask questions, chat in real time and find answers from student developers.</p></header>
<main><h2>Trending questions</h2><ul><li>How do I deploy a React app?</li><li>Node.js vs Spring Boot for APIs?</li></ul>
<p>Built with React, Node.js, MongoDB and Socket.io.</p></main></div></body></html>"""
JS_ERROR = """<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>ShopLite store</title></head>
<body><h1>ShopLite</h1><p>Products</p><script>window.addEventListener('load', () => { undefinedFunctionCall(); });</script>
<img src="/missing-logo.png"></body></html>"""
NOT_MOBILE = """<!doctype html><html><head><title>CropDoc crop disease detection</title></head><body>
<div style="width:1200px"><h1>CropDoc</h1><p>Upload a leaf photo to detect crop disease with a CNN model.</p></div></body></html>"""
CRA = """<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>React App</title></head>
<body><div id="root"><p>Edit src/App.js and save to reload.</p></div></body></html>"""
NETLIFY_404 = """<!doctype html><html><head><title>Page not found</title></head><body><h1>Page not found</h1>
<p>Looks like you've followed a broken link or entered a URL that doesn't exist on this site.</p><p>Netlify</p></body></html>"""
UNRELATED = """<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>Portfolio</title></head>
<body><h1>Hi, I'm Asha</h1><p>Photography and travel blog.</p></body></html>"""

ROUTES = {"/good": (200, GOOD), "/good/": (200, GOOD), "/jserror": (200, JS_ERROR), "/notmobile": (200, NOT_MOBILE),
          "/cra": (200, CRA), "/netlify404": (404, NETLIFY_404), "/error500": (500, "<h1>Internal Server Error</h1>"),
          "/unrelated": (200, UNRELATED)}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        status, body = ROUTES.get(self.path, (404, "<title>404</title><h1>Not found</h1>"))
        data = body.encode()
        self.send_response(status)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_HEAD(self):  # noqa: N802
        status, _ = ROUTES.get(self.path, (404, ""))
        self.send_response(status)
        self.end_headers()

    def log_message(self, *args):
        pass


def start() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
