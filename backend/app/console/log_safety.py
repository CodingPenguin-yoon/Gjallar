"""Keep WebSocket protocol debug output from recording cookies or console frames."""
import logging


class ConsoleProtocolFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn passes its error logger to websockets, which adds this protocol
        # object. Its DEBUG messages include raw headers and outbound RFB data.
        # Keep errors and connection lifecycle messages; redact only wire detail.
        if record.levelno <= logging.DEBUG and hasattr(record, 'websocket'):
            record.msg = 'WebSocket protocol detail omitted'
            record.args = ()
        return True


def install_console_log_filter():
    logger = logging.getLogger('uvicorn.error')
    if not any(isinstance(value, ConsoleProtocolFilter) for value in logger.filters):
        logger.addFilter(ConsoleProtocolFilter())
