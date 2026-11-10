import json
import logging
import os
import re
from datetime import datetime, timezone


class SafeFormatter(logging.Formatter):
    def format(self, record):
        message = record.getMessage()
        for name in ('FEISHU_WEBHOOK_URL', 'FEISHU_SIGNING_SECRET', 'THANOS_TOKEN', 'DATABASE_URL', 'API_TOKEN'):
            secret = os.getenv(name)
            if secret:
                message = message.replace(secret, '[redacted]')
        message = re.sub(r'https?://\S+', '[url]', message)
        return json.dumps({'time': datetime.now(timezone.utc).isoformat(), 'level': record.levelname, 'event': message, 'error_type': record.exc_info[0].__name__ if record.exc_info else None}, ensure_ascii=False)


def configure_logging(stream=None):
    logger = logging.getLogger('rackpulse')
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(SafeFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for name in ('httpx', 'httpcore'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    return logger
