import logging

import uvicorn

from . import config
from .web import build_app


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(build_app(), host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
