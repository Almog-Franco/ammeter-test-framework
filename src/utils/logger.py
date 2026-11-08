import logging
import os
from datetime import datetime

class TestLogger:
    __test__ = False  # not a test class, despite the name (stops pytest from collecting it)

    def __init__(self, test_name: str, log_dir: str = "results/logs"):
        self._test_name = test_name
        self._log_dir = log_dir
        self.log_file = None
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """
        הגדרת הלוגר עם פורמט מותאם וכתיבה לקובץ
        """
        # יצירת תיקיית הלוגים
        os.makedirs(self._log_dir, exist_ok=True)

        # הגדרת שם הקובץ עם תאריך ומזהה הבדיקה
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(self._log_dir, f"{timestamp}_{self._test_name}.log")

        # הגדרת הלוגר
        logger = logging.getLogger(f"test_{self._test_name}")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        if not logger.handlers:
            formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
            file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.ERROR)
            console_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)
        return logger

    def info(self, message: str):
        self.logger.info(message)

    def error(self, message: str):
        self.logger.error(message)

    def debug(self, message: str):
        self.logger.debug(message)

    def warning(self, message: str):
        self.logger.warning(message)

    def close(self):
        for handler in list(self.logger.handlers):
            handler.close()
            self.logger.removeHandler(handler)
