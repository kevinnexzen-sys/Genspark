import logging
import uvicorn

from database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

if __name__ == "__main__":
    init_db()
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
