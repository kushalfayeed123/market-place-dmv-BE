import uvicorn
from app.main import app

import time
import urllib.request

# Start server in background thread
config = uvicorn.Config(app, host="127.0.0.1", port=3000, log_level="warning")
server = uvicorn.Server(config)
t = server.run_in_thread()

time.sleep(3)
print("uvicorn started")

try:
    r = urllib.request.urlopen("http://127.0.0.1:3000/health", timeout=5)
    print("health:", r.status, r.read().decode())
except Exception as e:
    print("health check failed:", repr(e))

print("SERVER_READY")
