# Импорт необходимых библиотек и модулей
import flet as ft                                  # Фреймворк для создания кроссплатформенных приложений с современным UI
from api.openrouter import OpenRouterClient        # Клиент для взаимодействия с AI API через OpenRouter
from ui.styles import AppStyles                    # Модуль с настройками стилей интерфейса
from ui.components import MessageBubble, ModelSelector  # Компоненты пользовательского интерфейса
from utils.cache import ChatCache                  # Модуль для кэширования истории чата
from utils.logger import AppLogger                 # Модуль для логирования работы приложения
from utils.analytics import Analytics              # Модуль для сбора и анализа статистики использования
from utils.monitor import PerformanceMonitor       # Модуль для мониторинга производительности
import asyncio                                     # Библиотека для асинхронного программирования
import time                                        # Библиотека для работы с временными метками
import json                                        # Библиотека для работы с JSON-данными
from datetime import datetime                      # Класс для работы с датой и временем
import os                                          # Библиотека для работы с операционной системой
import subprocess
import hashlib
import secrets
import keyring


class ChatApp:
    """
    Основной класс приложения чата.
    Управляет всей логикой работы приложения, включая UI и взаимодействие с API.
    """

    SERVICE_NAME = "DesktopEbkaOpenRouter"
    USERNAME = "openrouter_api_key"

    def __init__(self):
        """
        Инициализация основных компонентов приложения:
        - API клиент для связи с языковой моделью
        - Система кэширования для сохранения истории
        - Система логирования для отслеживания работы
        - Система аналитики для сбора статистики
        - Система мониторинга для отслеживания производительности
        """

        # Инициалaизация основных компонентов
        self.api_client = None
        self.cache = ChatCache()                   # Инициализация системы кэширования
        self.logger = AppLogger()                  # Инициализация системы логирования
        self.analytics = Analytics(self.cache)     # Инициализация системы аналитики с передачей кэша
        self.monitor = PerformanceMonitor()        # Инициализация системы мониторинга


        # Создание директории для экспорта истории чата
        self.exports_dir = "exports"               # Путь к директории экспорта
        os.makedirs(self.exports_dir, exist_ok=True)  # Создание директории, если её нет




    def generate_pin(self) -> str:
        return f"{secrets.randbelow(10000):04d}"

    def generate_salt(self) -> str:
        return secrets.token_hex(16)

    def hash_pin(self, pin: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256",
            pin.encode("utf-8"),
            salt.encode("utf-8"),
            100_000,
        ).hex()

    def save_api_key_securely(self, api_key: str):
        keyring.set_password(self.SERVICE_NAME, self.USERNAME, api_key)

    def load_api_key_securely(self) -> str | None:
        return keyring.get_password(self.SERVICE_NAME, self.USERNAME)

    def clear_api_key_securely(self):
        try:
            keyring.delete_password(self.SERVICE_NAME, self.USERNAME)
        except Exception:
            pass


    def show_api_key_screen(self):
        self.page.controls.clear()

        api_key_input = ft.TextField(
            label="OpenRouter API Key",
            password=True,
            can_reveal_password=True,
            width=420,
        )

        status_text = ft.Text("", color=ft.Colors.RED_400)

        async def register_key(e):
            api_key = (api_key_input.value or "").strip()
            if not api_key:
                status_text.value = "Введите API ключ."
                self.page.update()
                return

            try:
                temp_client = OpenRouterClient(api_key)
                temp_client.headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }

                balance = temp_client.get_balance()

                if balance == "Ошибка":
                    status_text.value = "Ключ не прошёл проверку."
                    self.page.update()
                    return

                try:
                    balance_value = float(balance.replace("$", "").strip())
                except Exception:
                    balance_value = 0.0

                if balance_value < 0:
                    status_text.value = "Баланс отрицательный."
                    self.page.update()
                    return

                pin = self.generate_pin()
                salt = self.generate_salt()
                pin_hash = self.hash_pin(pin, salt)

                self.save_api_key_securely(api_key)
                self.cache.save_auth(pin_hash, salt)

                await self.show_generated_pin_dialog(pin)

            except Exception as ex:
                status_text.value = f"Ошибка проверки ключа: {ex}"
                self.page.update()

        self.page.add(
            ft.Column(
                controls=[
                    ft.Text("Первый вход", size=24, weight=ft.FontWeight.BOLD),
                    ft.Text("Введите ключ OpenRouter и подтвердите его."),
                    api_key_input,
                    ft.Button(content="Проверить и сохранить", on_click=register_key),
                    status_text,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=16,
            )
        )
        self.page.update()

    async def show_generated_pin_dialog(self, pin: str):
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("PIN сгенерирован"),
            content=ft.Column(
                controls=[
                    ft.Text("Сохраните PIN. Он будет показан только один раз."),
                    ft.Text(pin, size=28, weight=ft.FontWeight.BOLD),
                ],
                tight=True,
            ),
            actions=[
                ft.TextButton("Продолжить", on_click=lambda e: self.finish_registration(dialog))
            ],
        )
        self.page.show_dialog(dialog)
        self.page.update()


    def finish_registration(self, dialog):
        self.page.pop_dialog()
        self.show_chat_screen()


    def show_pin_screen(self):
        self.page.controls.clear()

        pin_input = ft.TextField(
            label="Введите PIN",
            password=True,
            width=220,
            max_length=4,
        )
        status_text = ft.Text("", color=ft.Colors.RED_400)

        async def login_by_pin(e):
            pin = (pin_input.value or "").strip()
            if len(pin) != 4 or not pin.isdigit():
                status_text.value = "PIN должен состоять из 4 цифр."
                self.page.update()
                return

            auth_data = self.cache.get_auth()
            if not auth_data:
                status_text.value = "Данные авторизации не найдены."
                self.page.update()
                return

            pin_hash, pin_salt, failed_attempts, is_configured = auth_data
            current_hash = self.hash_pin(pin, pin_salt)

            if current_hash == pin_hash:
                self.cache.reset_failed_attempts()
                self.show_chat_screen()
            else:
                self.cache.increment_failed_attempts()
                status_text.value = "Неверный PIN."
                self.page.update()

        def reset_key(e):
            self.cache.clear_auth()
            self.clear_api_key_securely()
            self.show_api_key_screen()

        self.page.add(
            ft.Column(
                controls=[
                    ft.Text("Вход", size=24, weight=ft.FontWeight.BOLD),
                    ft.Text("Введите PIN для доступа к приложению."),
                    pin_input,
                    ft.Row(
                        controls=[
                            ft.Button(content="Войти", on_click=login_by_pin),
                            ft.Button(content="Сбросить ключ", on_click=reset_key),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    status_text,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=16,
            )
        )
        self.page.update()

    def show_chat_screen(self):
        self.page.controls.clear()

        api_key = self.load_api_key_securely()
        self.api_client = OpenRouterClient(api_key)

        models = self.api_client.available_models
        self.model_dropdown = ModelSelector(models)
        self.model_dropdown.value = models[0]["id"] if models else None

        self.balance_text = ft.Text(
            "Баланс: Загрузка...",
            **AppStyles.BALANCE_TEXT
        )
        self.update_balance()

        self.message_input = ft.TextField(**AppStyles.MESSAGE_INPUT)
        self.chat_history = ft.ListView(**AppStyles.CHAT_HISTORY)

        self.load_chat_history()

        save_button = ft.Button(on_click=self.save_dialog, **AppStyles.SAVE_BUTTON)
        clear_button = ft.Button(on_click=self.confirm_clear_history, **AppStyles.CLEAR_BUTTON)
        send_button = ft.Button(on_click=self.send_message_click, **AppStyles.SEND_BUTTON)
        analytics_button = ft.Button(on_click=self.show_analytics, **AppStyles.ANALYTICS_BUTTON)

        control_buttons = ft.Row(
            controls=[save_button, analytics_button, clear_button],
            **AppStyles.CONTROL_BUTTONS_ROW
        )

        input_row = ft.Row(
            controls=[self.message_input, send_button],
            **AppStyles.INPUT_ROW
        )

        controls_column = ft.Column(
            controls=[input_row, control_buttons],
            **AppStyles.CONTROLS_COLUMN
        )

        balance_container = ft.Container(
            content=self.balance_text,
            **AppStyles.BALANCE_CONTAINER
        )

        model_selection = ft.Column(
            controls=[
                self.model_dropdown.search_field,
                self.model_dropdown,
                balance_container
            ],
            **AppStyles.MODEL_SELECTION_COLUMN
        )

        self.main_column = ft.Column(
            controls=[
                model_selection,
                self.chat_history,
                controls_column
            ],
            **AppStyles.MAIN_COLUMN
        )

        self.page.add(self.main_column)
        self.monitor.get_metrics()
        self.logger.info("Приложение запущено")
        self.page.update()


    def setup_page(self):
        for key, value in AppStyles.PAGE_SETTINGS.items():
            setattr(self.page, key, value)
        AppStyles.set_window_size(self.page)

    def show_start_screen(self):
        auth_data = self.cache.get_auth()
        stored_key = self.load_api_key_securely()

        if auth_data and stored_key:
            self.show_pin_screen()
        else:
            self.show_api_key_screen()

    def load_chat_history(self):
        """
        Загрузка истории чата из кэша и отображение её в интерфейсе.
        Сообщения добавляются в обратном порядке для правильной хронологии.
        """
        try:
            history = self.cache.get_chat_history()    # Получение истории из кэша
            for msg in reversed(history):              # Перебор сообщений в обратном порядке
                # Распаковка данных сообщения в отдельные переменные
                _, model, user_message, ai_response, timestamp, tokens = msg
                # Добавление пары сообщений (пользователь + AI) в интерфейс
                self.chat_history.controls.extend([
                    MessageBubble(                     # Создание пузырька сообщения пользователя
                        message=user_message,
                        is_user=True
                    ),
                    MessageBubble(                     # Создание пузырька ответа AI
                        message=ai_response,
                        is_user=False
                    )
                ])
        except Exception as e:
            # Логирование ошибки при загрузке истории
            self.logger.error(f"Ошибка загрузки истории чата: {e}")


    def update_balance(self):
        """
        Обновление отображения баланса API в интерфейсе.
        При успешном получении баланса показывает его зеленым цветом,
        при ошибке - красным с текстом 'н/д' (не доступен).
        """
        try:
            balance = self.api_client.get_balance()         # Запрос баланса через API
            self.balance_text.value = f"Баланс: {balance}"  # Обновление текста с балансом
            self.balance_text.color = ft.Colors.GREEN_400   # Установка зеленого цвета для успешного получения
        except Exception as e:
            # Обработка ошибки получения баланса
            self.balance_text.value = "Баланс: н/д"         # Установка текста ошибки
            self.balance_text.color = ft.Colors.RED_400     # Установка красного цвета для ошибки
            self.logger.error(f"Ошибка обновления баланса: {e}")


    def main(self, page: ft.Page):
        self.page = page
        self.setup_page()
        self.show_start_screen()


    async def send_message_click(self, e):
        """
        Асинхронная функция отправки сообщения.
        """
        if not self.message_input.value:
            return

        try:
            # Визуальная индикация процесса
            self.message_input.border_color = ft.Colors.BLUE_400
            self.page.update()

            # Сохранение данных сообщения
            start_time = time.time()
            user_message = self.message_input.value
            self.message_input.value = ""
            self.page.update()

            # Добавление сообщения пользователя
            self.chat_history.controls.append(
                MessageBubble(message=user_message, is_user=True)
            )

            # Индикатор загрузки
            loading = ft.ProgressRing()
            self.chat_history.controls.append(loading)
            self.page.update()

            # Асинхронная отправка запроса
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.api_client.send_message(
                    user_message,
                    self.model_dropdown.value
                )
            )

            # Удаление индикатора загрузки
            self.chat_history.controls.remove(loading)

            # Обработка ответа
            if "error" in response:
                response_text = f"Ошибка: {response['error']}"
                tokens_used = 0
                self.logger.error(f"Ошибка API: {response['error']}")
            else:
                response_text = response["choices"][0]["message"]["content"]
                tokens_used = response.get("usage", {}).get("total_tokens", 0)

            # Сохранение в кэш
            self.cache.save_message(
                model=self.model_dropdown.value,
                user_message=user_message,
                ai_response=response_text,
                tokens_used=tokens_used
            )

            # Добавление ответа в чат
            self.chat_history.controls.append(
                MessageBubble(message=response_text, is_user=False)
            )

            # Обновление аналитики
            response_time = time.time() - start_time
            self.analytics.track_message(
                model=self.model_dropdown.value,
                message_length=len(user_message),
                response_time=response_time,
                tokens_used=tokens_used
            )

            # Логирование метрик
            self.monitor.log_metrics(self.logger)
            self.page.update()

        except Exception as e:
            self.logger.error(f"Ошибка отправки сообщения: {e}")
            self.message_input.border_color = ft.Colors.RED_500

            # Показ уведомления об ошибке
            snack = ft.SnackBar(
                content=ft.Text(
                    str(e),
                    color=ft.Colors.RED_500,
                    weight=ft.FontWeight.BOLD
                ),
                bgcolor=ft.Colors.GREY_900,
                duration=5000,
            )
            self.page.overlay.append(snack)
            snack.open = True
            self.page.update()



    async def show_analytics(self, e):
        stats = self.analytics.get_statistics()

        dialog = ft.AlertDialog(
            title=ft.Text("Аналитика"),
            content=ft.Column([
                ft.Text(f"Всего сообщений: {stats['total_messages']}"),
                ft.Text(f"Всего токенов: {stats['total_tokens']}"),
                ft.Text(f"Среднее токенов/сообщение: {stats['tokens_per_message']:.2f}"),
                ft.Text(f"Сообщений в минуту: {stats['messages_per_minute']:.2f}")
            ]),
            actions=[
                ft.TextButton("Закрыть", on_click=self.close_dialog),
            ],
        )

        self.page.show_dialog(dialog)
        self.page.update()



    async def clear_history(self, e):
        """
        Очистка истории чата.
        """
        try:
            self.cache.clear_history()          # Очистка кэша
            self.analytics.clear_data()         # Очистка аналитики
            self.chat_history.controls.clear()  # Очистка истории чата
            self.page.update()

        except Exception as e:
            self.logger.error(f"Ошибка очистки истории: {e}")


    async def confirm_clear_history(self, e):

        async def clear_confirmed(e):
            await self.clear_history(e)
            self.page.pop_dialog()
            self.page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Подтверждение удаления"),
            content=ft.Text("Вы уверены?"),
            actions=[
                ft.TextButton("Отмена", on_click=self.close_dialog),
                ft.TextButton("Очистить", on_click=clear_confirmed),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.page.show_dialog(dialog)
        self.page.update()


    async def save_dialog(self, e):
        try:
            history = self.cache.get_chat_history()

            dialog_data = []
            for msg in history:
                dialog_data.append({
                    "timestamp": msg[4],
                    "model": msg[1],
                    "user_message": msg[2],
                    "ai_response": msg[3],
                    "tokens_used": msg[5]
                })

            filename = f"chat_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = os.path.join(self.exports_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(dialog_data, f, ensure_ascii=False, indent=2, default=str)

            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Диалог сохранен"),
                content=ft.Column([
                    ft.Text("Путь сохранения:"),
                    ft.Text(filepath, selectable=True, weight=ft.FontWeight.BOLD),
                ]),
                actions=[
                    ft.TextButton("OK", on_click=self.close_dialog),
                    ft.TextButton(
                        "Открыть папку",
                        on_click=lambda e: subprocess.Popen(f'explorer "{self.exports_dir}"')
                    ),
                ],
            )

            self.page.show_dialog(dialog)
            self.page.update()

        except Exception as e:
            self.logger.error(f"Ошибка сохранения: {e}")



    def close_dialog(self, e=None):
        self.page.pop_dialog()
        self.page.update()





def main():
    """Точка входа в приложение"""
    app = ChatApp()                              # Создание экземпляра приложения
    ft.app(target=app.main)                      # Запуск приложения

if __name__ == "__main__":
    main()    