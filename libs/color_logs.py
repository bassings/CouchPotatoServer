import logging

def add_coloring_to_emit_ansi(fn):
    def new(*args):
        levelno = args[1].levelno
        if(levelno >= 50):
            color = '\x1b[31m' # red
        elif(levelno >= 40):
            color = '\x1b[31m' # red
        elif(levelno >= 30):
            color = '\x1b[33m' # yellow
        elif(levelno >= 20):
            color = '\x1b[0m'
        elif(levelno >= 10):
            color = '\x1b[36m'
        else:
            color = '\x1b[0m'  # normal

        try:
            msg = args[1].msg
            if isinstance(msg, str) and not msg.startswith(color):
                args[1].msg = color + msg + '\x1b[0m'
        except Exception:
            # Be defensive; never break logging due to coloring
            pass

        try:
            return fn(*args)
        except Exception:
            # Ignore logging errors (e.g., stream closed during interpreter shutdown)
            return None
    return new

logging.StreamHandler.emit = add_coloring_to_emit_ansi(logging.StreamHandler.emit)
