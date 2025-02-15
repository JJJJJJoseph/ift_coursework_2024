import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from config.auth import auth_settings  # noqa: E402

if __name__ == "__main__":
    print(auth_settings.MINIO_USERNAME)
