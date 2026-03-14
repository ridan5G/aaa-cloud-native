import os
from dotenv import load_dotenv

load_dotenv()

PRIMARY_URL = os.getenv("PRIMARY_URL", "postgresql://aaa_app:devpassword@localhost:5432/aaa")
HTTP_PORT = int(os.getenv("HTTP_PORT", "8080"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "9091"))

JWT_SKIP_VERIFY = os.getenv("JWT_SKIP_VERIFY", "false").lower() == "true"
JWT_PUBLIC_KEY = os.getenv("JWT_PUBLIC_KEY", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "RS256")

BULK_WORKER_THREADS = int(os.getenv("BULK_WORKER_THREADS", "4"))
BULK_BATCH_SIZE = int(os.getenv("BULK_BATCH_SIZE", "1000"))
