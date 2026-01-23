import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.zt_monitor import _map_status


def main() -> None:
    assert _map_status("OK") == "подключение установлено"
    assert _map_status("ACCESS_DENIED") == "ошибка аутентификации"
    assert _map_status("REQUESTING_CONFIGURATION") == "ожидание конфигурации"
    assert _map_status("NOT_FOUND") == "сеть не найдена"
    assert _map_status("") == "неизвестно"


if __name__ == "__main__":
    main()
