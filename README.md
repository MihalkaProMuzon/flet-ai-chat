Небольшое десктопное приложение для работы с моделями через OpenRouter API.  
UI реализован на Flet.
## Возможности

- работа с моделями OpenRouter
- локальная история сообщений
- экспорт диалога в JSON
- просмотр статистики использования
- базовая аутентификация через PIN

## Стек

- Python
- Flet
- SQLite
- OpenRouter API
- keyring (Windows Credential Manager)

## Запуск

```bash
pip install -r requirements.txt
python src/main.py

