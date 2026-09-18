import io
import logging
import sys

logger = logging.getLogger("ecommerce")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)-8s %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Windows cp949 인코딩 문제 방지: UTF-8 강제
stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
console_handler = logging.StreamHandler(stream)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
