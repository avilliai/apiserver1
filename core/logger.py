import logging

GREY   = "\033[38;5;245m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

class ColorFormatter(logging.Formatter):
    LEVEL_COLORS = {
        logging.DEBUG:    GREY,
        logging.INFO:     GREEN,
        logging.WARNING:  YELLOW,
        logging.ERROR:    RED,
        logging.CRITICAL: RED + BOLD,
    }

    def format(self, record):
        level_color = self.LEVEL_COLORS.get(record.levelno, RESET)

        # uvicorn access log 长这样: '127.0.0.1:12345 - "GET / HTTP/1.1" 200 OK'
        # 单独处理，不加时间戳，只给 IP 和状态码上色
        if record.name == "uvicorn.access":
            msg = record.getMessage()
            # IP 部分染青色，状态码根据数值染色
            try:
                ip_part, rest = msg.split(" - ", 1)
                # 状态码在最后，取倒数第二个 token（"200 OK" 里的 200）
                tokens = rest.rsplit(" ", 2)
                code = int(tokens[-2]) if len(tokens) >= 2 else 0
                code_color = GREEN if code < 400 else (YELLOW if code < 500 else RED)
                return (
                    f"{CYAN}{ip_part}{RESET} - "
                    f"{GREY}{tokens[0]}{RESET} "
                    f"{code_color}{tokens[-2]} {tokens[-1]}{RESET}"
                )
            except Exception:
                return msg

        # 普通日志：时间戳 + 级别 + 消息
        time_str = self.formatTime(record, "%H:%M:%S")
        return (
            f"{GREY}{time_str}{RESET} | "
            f"{level_color}{record.levelname:<7}{RESET} | "
            f"{CYAN}{record.name}{RESET}  "
            f"{record.getMessage()}"
        )


def setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter())

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)

    # uvicorn 单独挂，不往根 logger 冒泡
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.addHandler(handler)
        uv.propagate = False
