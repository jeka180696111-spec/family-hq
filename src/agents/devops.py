from __future__ import annotations
from typing import Any
import structlog

from src.agents.base import BaseAgent

log = structlog.get_logger()

class DevOpsAgent(BaseAgent):
    """
    Прораб — monitors system health, creates GitHub PRs for fixes,
    manages agent hiring/firing workflow.
    """

    agent_id = "devops"
    emoji = "🛠️"
    name = "Прораб"

    def __init__(self, *args, github_client=None, railway_client=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._railway = railway_client
        self._github = github_client

    def get_system_prompt(self) -> str:
        from src.prompts.devops import get_devops_prompt
        return get_devops_prompt(active_agents=[])

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "read_logs",
                "description": "Прочитать логи системы",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "string", "enum": ["INFO", "WARNING", "ERROR", "CRITICAL"], "default": "ERROR"},
                        "agent_id": {"type": "string"},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
            },
            {
                "name": "create_github_pr",
                "description": "Создать Pull Request в GitHub",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "branch": {"type": "string"},
                        "body": {"type": "string"},
                        "files": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "content": {"type": "string"},
                                },
                            },
                        },
                    },
                    "required": ["title", "branch", "body"],
                },
            },
            {
                "name": "ping_external",
                "description": "Проверить внешний сервис",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "enum": ["matveika_bot", "finance_bot", "anthropic_api"]},
                    },
                    "required": ["service"],
                },
            },
            {
                "name": "read_file",
                "description": "Прочитать файл проекта",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Путь относительно корня проекта"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "system_status",
                "description": (
                    "Полная диагностика системы. Используй когда: «статус», «как дела», "
                    "«что там у тебя», «проверь систему», «здоровье системы». "
                    "Покажет: каналы Дозорного (подписки/последний пост), активные тревоги, "
                    "Sheets/Calendar/GitHub/Railway статус, последние ошибки в логах."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "cost_report",
                "description": (
                    "Сколько потратили на Anthropic API. Используй когда: «сколько спалили», "
                    "«отчёт по тратам», «сколько стоит за день/месяц», «cost»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "description": "За сколько дней назад (по умолчанию 30)"},
                    },
                },
            },
            {
                "name": "set_family_fact",
                "description": (
                    "Изменить факт о семье без правки кода. Используй когда: "
                    "«запомни Матвей весит 9.5кг», «измерили рост 73», «новый помощник», "
                    "«у Марины аллергия на X». Также используй для переезда/отпуска: "
                    "set_family_fact('current_location.city', 'Львов'). "
                    "Доступные ключи (примеры): "
                    "matvey.weight_g, matvey.height_cm, "
                    "current_location.city, current_location.district, current_location.until_date, "
                    "father.weight_kg, mother.weight_kg, mother.blood_type."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "required": ["key", "value"],
                },
            },
            {
                "name": "family_wiki",
                "description": (
                    "Полный портрет семьи в одном красивом ответе: все члены, "
                    "состояние малыша, помощники, локация, документы со сроками, "
                    "активные подписки, активные режимы, ключевые контакты. "
                    "Триггеры: «вики», «профиль», «портрет семьи», «всё про семью», «/profile»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "section": {
                            "type": "string",
                            "enum": ["all", "child", "parents", "helpers", "documents", "subscriptions", "modes", "emergency"],
                            "description": "Какую секцию показать (по умолчанию all)",
                        },
                    },
                },
            },
            {
                "name": "write_time_capsule",
                "description": (
                    "Записать короткую запись в «капсулу времени» — особенный момент месяца. "
                    "Будет показано в годовщину. Используй для дней рождения, первых событий, "
                    "запоминающихся моментов."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["title", "text"],
                },
            },
            {
                "name": "add_automation_rule",
                "description": (
                    "Создать правило автоматизации IF-THEN. Будет проверяться каждые 5 минут. "
                    "Примеры:\n"
                    "  «выключи бойлер в 22:00» → condition: time 22:00, action: device off бойлер\n"
                    "  «если в детской >25°C, напиши в чат» → condition: sensor temp >25, action: message\n"
                    "  «когда отбой тревоги в Одессе — выключи ТВ» → condition: alert_ended Одесса, action: device off\n"
                    "  «свет нет → выключи ТВ и бойлер» → нужно ДВА правила или один action на каждое.\n"
                    "Cooldown: минимум N минут между срабатываниями (по умолчанию 60)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Уникальное имя правила"},
                        "description": {"type": "string"},
                        "condition": {
                            "type": "object",
                            "description": (
                                "JSON-условие. Типы: time {cron:'HH:MM', weekday:'sun'?}; "
                                "datetime {at:'YYYY-MM-DDTHH:MM', late_fire:true?} — "
                                "  для one-shot задач ВСЕГДА ставь late_fire:true, "
                                "  иначе при простое сервиса задача пропустится; "
                                "sensor {device, metric:'temperature'|'humidity', op:'>'|'<'|'>='|'<='|'=='|'!=', value}; "
                                "alert_active {region}; alert_ended {region}; "
                                "power_outage {state:'active'|'ended', delay_min:N?, within_min:N?}; "
                                "baby_sleeping {min_minutes:N?} — Матвей спит ≥N мин (окно тишины); "
                                "and {rules:[...]}; or {rules:[...]}"
                            ),
                        },
                        "action": {
                            "type": "object",
                            "description": (
                                "JSON-действие. Типы: device {device, action:'on'|'off'|'toggle'}; "
                                "message {agent:'devops'|'nanny'|..., text}; "
                                "set_mode {mode:'trip'|'sick'|'quiet', enabled:bool, until}; "
                                "tool {agent, tool, input, notify:bool}"
                            ),
                        },
                        "cooldown_min": {"type": "integer", "description": "Минимум минут между срабатываниями. По умолчанию 60."},
                    },
                    "required": ["name", "condition", "action"],
                },
            },
            {
                "name": "list_automation_rules",
                "description": (
                    "Показать ВСЕ правила автоматизации и одноразовые "
                    "таймеры с их статусом (включено/выключено, "
                    "условие, действие, следующий запуск). Триггеры: "
                    "«покажи мои автоматизации», «список правил», "
                    "«какие у меня автоматизации», «правила», "
                    "«что у меня автоматизировано», «список таймеров», "
                    "«показать одноразовые задачи»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "toggle_automation_rule",
                "description": "Включить/выключить правило по имени.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "enabled": {"type": "boolean"},
                    },
                    "required": ["name", "enabled"],
                },
            },
            {
                "name": "delete_automation_rule",
                "description": "Удалить правило автоматизации (по имени) — и из БД, и из вкладки «⚙️ Автоматизации».",
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
            {
                "name": "repair_automation_rules",
                "description": (
                    "Прогнать все существующие правила автоматизации через "
                    "нормализатор JSON — фиксит обёрнутый формат "
                    "{«power_outage»: {...}} → {«type»: «power_outage», ...}. "
                    "Также обновляет вкладку «⚙️ Автоматизации». Триггер: "
                    "«почини правила», «нераспозн в таблице», «триггер не работает»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "inspect_automation_rule",
                "description": (
                    "Показать ТОЧНУЮ структуру JSON конкретного правила: "
                    "что лежит в condition и action. Используй когда юзер "
                    "говорит «покажи правило X», «что внутри правила Y», "
                    "«почему не работает», «триггер не распознан»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
            {
                "name": "delete_all_automation_rules",
                "description": (
                    "Удалить ВСЕ правила автоматизации сразу — и из БД, и из "
                    "вкладки «⚙️ Автоматизации». Триггеры: «удали все автоматизации», "
                    "«снеси все правила», «очисти автоматизации». ОПАСНАЯ ОПЕРАЦИЯ — "
                    "перед вызовом удостоверься что юзер сказал «все/всё»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "list_smart_devices",
                "description": (
                    "Показать smart-устройства (Tuya / Smart Life) — бойлер, ТВ, датчики. "
                    "Триггер: «умный дом», «устройства», «бойлер», «датчик в детской»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "wiki_set",
                "description": (
                    "Запомнить факт о члене семьи. Все агенты будут видеть его "
                    "в контексте и использовать в советах. Триггеры: «запомни что …», "
                    "«у Марины аллергия на X», «Евгений не пьёт алкоголь», "
                    "«добавь в вики». Перезаписывает существующий ключ."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "member": {
                            "type": "string",
                            "description": (
                                "Кого касается: matvey/marina/eugene/family или имя бабушки. "
                                "Если общее семейное — family."
                            ),
                        },
                        "key": {
                            "type": "string",
                            "description": "Тип факта: 'аллергия', 'любит', 'не любит', 'размер одежды', 'предпочтения', 'привычки' и т.п.",
                        },
                        "value": {"type": "string", "description": "Сам факт"},
                    },
                    "required": ["member", "key", "value"],
                },
            },
            {
                "name": "wiki_list",
                "description": "Показать все факты о члене семьи (или все, если member не указан).",
                "input_schema": {
                    "type": "object",
                    "properties": {"member": {"type": "string"}},
                },
            },
            {
                "name": "wiki_delete",
                "description": "Удалить факт по члену семьи и ключу.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "member": {"type": "string"},
                        "key": {"type": "string"},
                    },
                    "required": ["member", "key"],
                },
            },
            {
                "name": "family_search",
                "description": (
                    "Поиск по всей памяти семьи: чат, дневник малыша, фото в архиве, "
                    "поездки, заправки, family wiki. Триггеры: «когда мы», «найди», "
                    "«где про», «покажи где», «помнишь как»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Свободный запрос на русском"},
                        "days_back": {"type": "integer", "description": "За сколько дней искать (по умолчанию 365)"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "parcel_track",
                "description": (
                    "Отследить посылку Nova Poshta по ТТН. Триггеры: «отследи ТТН», "
                    "«посылка», «когда придёт», «новая почта». Если юзер написал "
                    "ТТН (14 цифр) в чате — авто-детект сработает сам, этот tool "
                    "вызывай только при явной просьбе или для повторной проверки."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ttn": {"type": "string", "description": "Номер накладной (14 цифр)"},
                        "title": {"type": "string", "description": "Короткое имя посылки, опц."},
                        "phone_last4": {
                            "type": "string",
                            "description": "Последние 4 цифры телефона получателя (для полных деталей)",
                        },
                    },
                    "required": ["ttn"],
                },
            },
            {
                "name": "parcel_list",
                "description": "Показать активные посылки (не доставленные).",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "ai_set_provider",
                "description": (
                    "Принудительно переключить AI на Claude или Gemini до "
                    "указанного времени. Используй когда юзер просит «используй "
                    "Gemini до 16:00», «переключись на Claude», «отключи Gemini». "
                    "Передай provider=null чтобы снять override и вернуться к "
                    "обычной логике (Claude по умолчанию, Gemini fallback)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "provider": {
                            "type": "string",
                            "enum": ["claude", "gemini", "off"],
                            "description": "claude / gemini для override, off — снять",
                        },
                        "until": {
                            "type": "string",
                            "description": "ISO datetime Kyiv-local когда снять override (опц)",
                        },
                    },
                    "required": ["provider"],
                },
            },
            {
                "name": "ai_status",
                "description": (
                    "Показать какой AI сейчас работает (Claude или Gemini fallback) "
                    "и статистику вызовов. Триггеры: «какой AI», «кто отвечает», "
                    "«статус AI», «текущий ключ»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "gemini_discover_models",
                "description": (
                    "Узнать какие модели Gemini доступны для текущего "
                    "GEMINI_API_KEY. Полезно когда fallback падает с "
                    "«модель не найдена». Триггеры: «какие модели Gemini», "
                    "«проверь модели Gemini», «список Gemini»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "gemini_ping",
                "description": (
                    "Проверить что Gemini API (резервный AI) отвечает. "
                    "Триггеры: «проверь gemini», «пингани gemini», «работает ли gemini»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "morning_brief_now",
                "description": (
                    "Собрать и прислать утренний брифинг прямо сейчас. "
                    "ВЫЗЫВАЙ ТОЛЬКО при ЯВНОЙ просьбе именно про брифинг: "
                    "«тригерни брифинг», «утренний брифинг сейчас», "
                    "«пришли утренний отчёт», «сводка утром», «morning brief». "
                    "НЕ вызывай на: «привет», «на связи», «как дела», "
                    "обращения к другим агентам, любые упоминания других имён "
                    "(Штурман/Няня/Дозорный и т.д.)."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "list_baby_photos",
                "description": (
                    "Показать список фото малыша в БД: id, дата (created_at), "
                    "подпись, есть ли в Drive. Полезно когда backfill не нашёл "
                    "дату и нужно понять какие конкретно фото поправить вручную. "
                    "Триггеры: «покажи фото», «список фото», «какие фото есть»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "missing_only": {
                            "type": "boolean",
                            "description": "Показать только те где дата подозрительная (далеко от даты загрузки или равна сейчас)",
                        },
                    },
                },
            },
            {
                "name": "sync_photos_with_drive",
                "description": (
                    "Просканировать папки 👶 Матвей · Фото в Google Drive и "
                    "добавить в БД отсутствующие записи (для фото которые юзер "
                    "загружал руками через веб-интерфейс Drive, минуя Family HQ). "
                    "Триггеры: «синхронизируй фото с диском», «подцепи фото из "
                    "диска», «у меня в Drive больше чем в БД»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "months": {
                            "type": "integer",
                            "description": "Сколько месяцев назад сканировать (по умолчанию 3)",
                        },
                    },
                },
            },
            {
                "name": "cleanup_orphan_photos",
                "description": (
                    "Удалить из БД фото-записи без drive_file_id — это «мусор» от "
                    "старых неудачных загрузок (когда Drive не работал из-за SA "
                    "quota). Они дублируют успешно загруженные фото. Триггеры: "
                    "«почисти мусорные фото», «удали дубликаты фото», «у меня в "
                    "БД больше чем в Drive»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dry_run": {
                            "type": "boolean",
                            "description": "Только показать что удалится, не удалять (по умолчанию false)",
                        },
                    },
                },
            },
            {
                "name": "set_photo_caption",
                "description": (
                    "Вручную поставить подпись под конкретное фото "
                    "(если в Drive имя без подписи). Триггеры: «подпиши "
                    "фото 17 — Матвей улыбается», «caption фото 8»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "photo_id": {"type": "integer"},
                        "caption": {"type": "string"},
                    },
                    "required": ["photo_id", "caption"],
                },
            },
            {
                "name": "set_photo_date",
                "description": (
                    "Установить дату для конкретного фото вручную (если backfill "
                    "не смог автоматически). Триггеры: «дата фото 42 — 03.06», "
                    "«поставь фото 17 на 5 июня»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "photo_id": {"type": "integer"},
                        "date": {"type": "string", "description": "DD.MM или DD.MM.YYYY"},
                    },
                    "required": ["photo_id", "date"],
                },
            },
            {
                "name": "backfill_photo_dates",
                "description": (
                    "Пересчитать даты фото малыша по подписям (для уже "
                    "загруженных фото где created_at сохранён как время "
                    "загрузки вместо реальной даты события). Триггеры: "
                    "«пересчитай даты фото», «backfill фото», «фото не "
                    "находятся по датам»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "chronicle_now",
                "description": (
                    "Сгенерировать PDF-хронику. По умолчанию — последние 7 дней. "
                    "Правило: одно фото за каждый день недели. Если хотя бы один день "
                    "без фото — НЕ генерирую, а сообщаю какие дни пустые; юзер доливает "
                    "и снова просит. Если хочется собрать с пропусками — передай "
                    "force=true. Можно указать конкретный период через "
                    "start_date/end_date (для ретро-хроники). "
                    "Триггеры: «сгенерируй хронику», «хроника за 02.06-08.06», "
                    "«хроника force», «сделай PDF за прошлую неделю»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "start_date": {
                            "type": "string",
                            "description": "Начало периода YYYY-MM-DD или DD.MM.YYYY",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "Конец периода (включительно)",
                        },
                        "force": {
                            "type": "boolean",
                            "description": "Игнорировать дни без фото, собрать как есть",
                        },
                    },
                },
            },
            {
                "name": "battery_autonomy",
                "description": (
                    "Прогноз сколько часов хватит батареи инвертора при текущем "
                    "потреблении + рекомендации что выключить чтобы продлить. "
                    "Триггеры: «на сколько хватит батареи», «автономность», "
                    "«сколько проживём без света», «что выключить»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "notebook_add",
                "description": (
                    "Записать задачу/обещание в свой блокнот на Google Sheet. "
                    "ОБЯЗАТЕЛЬНО используй когда обещаешь юзеру что-то сделать "
                    "в будущем («включу бойлер в 15:00», «напомню утром», "
                    "«проверю позже») — ЭТО первый шаг до того как отвечаешь юзеру. "
                    "Если задача автоматизируемая (включить/выключить устройство в "
                    "конкретное время) — ВМЕСТО блокнота создай add_automation_rule. "
                    "Блокнот для того, что нельзя автоматизировать или для будущего разбора."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "Краткое описание задачи (1-2 строки)."},
                        "due_at": {
                            "type": "string",
                            "description": "Срок ISO 'YYYY-MM-DDTHH:MM' в Киевском времени. Опционально.",
                        },
                        "note": {"type": "string", "description": "Дополнительный контекст."},
                    },
                    "required": ["task"],
                },
            },
            {
                "name": "notebook_list",
                "description": (
                    "Показать задачи из блокнота. Триггеры: «что в блокноте», "
                    "«какие задачи», «что ты обещал», «список дел». По умолчанию "
                    "только открытые."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["open", "done", "skip", "all"],
                            "description": "По умолчанию 'open'.",
                        },
                    },
                },
            },
            {
                "name": "notebook_done",
                "description": "Отметить задачу как выполненную. Триггеры: «выполнено», «сделано», «закрой задачу N».",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "note": {"type": "string", "description": "Что именно сделано."},
                    },
                    "required": ["id"],
                },
            },
            {
                "name": "schedule_device_action",
                "description": (
                    "ПРОСТОЙ способ запланировать включение/выключение устройства "
                    "на конкретное время. ИСПОЛЬЗУЙ ЭТО вместо ручного "
                    "add_automation_rule когда надо просто включить/выключить "
                    "устройство через N минут / в HH:MM. "
                    "Триггеры: «включи бойлер в 15:00», «через 2 минуты вкл свет», "
                    "«выключи ТВ через час», «в 22:00 выкл бойлер». "
                    "Параметр when принимает: «через 5 минут», «через 2 часа», "
                    "«в 15:00», «в 22:30», или ISO «2026-06-12T15:00»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "device": {"type": "string", "description": "Имя устройства как в умном доме (бойлер, ТВ, свет)."},
                        "action": {"type": "string", "enum": ["on", "off", "toggle"]},
                        "when": {"type": "string", "description": "«через N минут», «в HH:MM», или ISO."},
                    },
                    "required": ["device", "action", "when"],
                },
            },
            {
                "name": "notebook_diag",
                "description": (
                    "Диагностика блокнота: пытается создать/найти вкладку и "
                    "вернуть точную ошибку если что-то не так. Использовать "
                    "только когда юзер говорит «блокнот не работает» / «нет вкладки»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "notebook_sync_rules",
                "description": (
                    "Перенести в блокнот все ВКЛЮЧЁННЫЕ автоматизации из БД, "
                    "которых там ещё нет. Триггер: «синхронизируй блокнот», "
                    "«перенеси автоматизации в блокнот», «занеси правила в блокнот»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "solar_status",
                "description": (
                    "Текущее состояние инвертора: солнечная генерация, заряд батареи, "
                    "потребление дома, сеть. Триггер: «солнце», «батарея», «инвертор», "
                    "«сколько генерирует», «заряд»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "solar_today",
                "description": "Энергобаланс за сегодня в кВт·ч: произведено солнцем, потреблено домом, импорт/экспорт.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "vacuum_status",
                "description": (
                    "Статус робота-пылесоса Samsung POWERbot (через SmartThings). "
                    "Возвращает заряд батареи, режим уборки, текущее движение."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Имя устройства если их несколько (опционально)"},
                    },
                },
            },
            {
                "name": "vacuum_start",
                "description": (
                    "Запустить уборку. Режимы: auto (вся квартира), part (точечная), "
                    "repeat (повторно), manual, map (по карте). Триггер: «запусти пылесос», "
                    "«пропылесось», «убери»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["auto", "part", "repeat", "manual", "map"]},
                        "name": {"type": "string"},
                    },
                },
            },
            {
                "name": "vacuum_stop",
                "description": "Отправить пылесос на базу. Триггер: «стоп пылесос», «домой», «на базу».",
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
            {
                "name": "plan_trip",
                "description": (
                    "Запланировать поездку: создаст автоматические правила для "
                    "выключения устройств при отъезде и включения к приезду. "
                    "Используй когда: «уезжаю DD.MM в HH:MM, приезжаю DD.MM в HH:MM», "
                    "«запланируй поездку», «отпуск с .. по ..»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "leave_at": {"type": "string", "description": "ISO datetime отъезда (2026-06-25T13:00:00)"},
                        "return_at": {"type": "string", "description": "ISO datetime приезда"},
                        "destination": {"type": "string", "description": "Куда едете (опционально)"},
                        "devices_off": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Какие устройства выключить при отъезде. По умолчанию: ТВ, бойлер.",
                        },
                        "devices_on_before_return": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Какие устройства включить за 2 часа до приезда. По умолчанию: бойлер.",
                        },
                    },
                    "required": ["leave_at", "return_at"],
                },
            },
            {
                "name": "control_smart_device",
                "description": (
                    "Включить/выключить smart-устройство. Триггеры: «включи бойлер», "
                    "«выключи телевизор», «отключи кондиционер»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "device": {"type": "string", "description": "Название или ID устройства"},
                        "action": {"type": "string", "enum": ["on", "off", "toggle", "status"]},
                    },
                    "required": ["device", "action"],
                },
            },
            {
                "name": "control_device_for_duration",
                "description": (
                    "Включить устройство СЕЙЧАС и автоматически выключить через "
                    "N минут (или наоборот: выключить сейчас и включить через N). "
                    "Триггеры: «включи кондер на 10 минут», «выключи бойлер на полчаса», "
                    "«кондер на 5 мин», «включи свет на 20 минут», «вырубай на 1 час». "
                    "Сам собирает обе операции в один шаг — юзеру не нужно "
                    "писать два раза «включи» и «через N выключи»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "device": {"type": "string", "description": "Имя устройства"},
                        "action": {
                            "type": "string", "enum": ["on", "off"],
                            "description": "Что сделать СЕЙЧАС (обратное произойдёт через N минут).",
                        },
                        "duration_min": {
                            "type": "integer",
                            "description": "Длительность в минутах. Принимай «полчаса»=30, «час»=60.",
                        },
                    },
                    "required": ["device", "action", "duration_min"],
                },
            },
            {
                "name": "smart_set_temperature",
                "description": (
                    "Установить целевую температуру на кондиционере (16-30°C). "
                    "Триггеры: «кондер на 22 градуса», «поставь сплит на 24», "
                    "«охлади до 21», «нагрей до 26». ВАЖНО: используй именно этот "
                    "инструмент, а не control_smart_device, когда юзер называет "
                    "градусы."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "device": {"type": "string", "description": "Имя устройства (кондер / кондиционер)"},
                        "temperature": {"type": "integer", "description": "Целевая температура 16-30°C"},
                    },
                    "required": ["device", "temperature"],
                },
            },
            {
                "name": "smart_set_mode",
                "description": (
                    "Установить режим работы кондиционера: cold (охлаждение/холод), "
                    "hot (обогрев/тепло), wet (осушение), wind (вентилятор), auto (авто). "
                    "Триггеры: «кондер на холод», «включи обогрев», «поставь на осушение», "
                    "«режим вентилятора»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "device": {"type": "string", "description": "Имя устройства (кондер / кондиционер)"},
                        "mode": {
                            "type": "string",
                            "description": "Режим: cold/hot/wet/wind/auto или ru-алиасы (холод/тепло/осушение/вентилятор/авто)",
                        },
                        "temperature": {
                            "type": "integer",
                            "description": "Опционально: целевая температура (16-30°C). По умолчанию 24.",
                        },
                    },
                    "required": ["device", "mode"],
                },
            },
            {
                "name": "smart_set_fan_speed",
                "description": (
                    "Установить скорость вентилятора кондиционера: auto / low / "
                    "med / high. Триггеры: «кондер тише», «тихий режим», "
                    "«низкая скорость», «макс обдув», «турбо», «средний обдув», "
                    "«автоматическая скорость»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "device": {"type": "string", "description": "Имя устройства (кондер / кондиционер)"},
                        "speed": {
                            "type": "string",
                            "description": "auto / low / med / high или ru-алиасы (тихо/средняя/высокая/макс/турбо/sleep)",
                        },
                        "mode": {
                            "type": "string",
                            "description": "Опционально: оставить тот же режим. cold/hot/wet/wind/auto.",
                        },
                        "temperature": {
                            "type": "integer",
                            "description": "Опционально: оставить ту же температуру (16-30°C).",
                        },
                    },
                    "required": ["device", "speed"],
                },
            },
            {
                "name": "dump_device_dps",
                "description": (
                    "Диагностика: дамп всех DPs (data points) устройства "
                    "Tuya as-is. Используется чтобы увидеть какие коды "
                    "и значения отдаёт смарт-розетка (cur_power, "
                    "cur_current, voltage и т.п.). Триггер: «дамп <устр>», "
                    "«покажи DPs <устр>», «состояние датчиков <устр>»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "device": {"type": "string", "description": "Имя устройства (бойлер, тв, кондер...)"},
                    },
                    "required": ["device"],
                },
            },
            {
                "name": "inverter_runtime",
                "description": (
                    "Сколько света осталось от батареи при текущей нагрузке. "
                    "Возвращает % батареи, нагрузку в Вт, время до 20% резерва, "
                    "и подсказки «если выкл бойлер → +Xч». Триггеры: "
                    "«сколько света осталось», «сколько батареи осталось», "
                    "«состояние инвертора», «инвертор», «батарея», «сколько часов "
                    "продержимся», «надолго ли батареи». Сразу возвращай юзеру "
                    "поле `text` целиком (он уже отформатирован)."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "run_tuya_scene",
                "description": (
                    "🚀 ПРЕДПОЧТИТЕЛЬНЫЙ способ управлять кондиционером. "
                    "Запускает заранее созданную в Smart Life сцену «Tap-to-Run» "
                    "(«Миттєвий сценарій»). У юзера есть сцены вида «Кондер 25», "
                    "«Кондер ВЫКЛ», «Кондер ВКЛ», «Кондер 17» и т.д. "
                    "Принимает естественный запрос юзера («поставь кондер на 25», "
                    "«выключи кондер», «холоднее») — внутри fuzzy match по имени. "
                    "Этот путь надёжнее чем прямые smart_set_mode/smart_set_temperature: "
                    "сцена выполняется хабом локально по триггеру из облака, а не "
                    "собирается на лету. ВСЕГДА пробуй сначала ЕГО, fallback на "
                    "старые smart_* только если run_tuya_scene вернул "
                    "no_match/ambiguous."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Запрос юзера как есть, например «кондер 25 холод» или «выключи кондер».",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "diagnose_tuya_scenes",
                "description": (
                    "Диагностика: ПОЧЕМУ сцены не подтягиваются. Возвращает "
                    "сырые ответы Tuya по homes / scenes v1 / scenes v2. "
                    "Триггер: «почему пусто», «список сцен пустой», "
                    "«диагностика сцен», «проверь сцены»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "list_tuya_scenes",
                "description": (
                    "Показать все Tap-to-Run сцены в Tuya Smart Life. "
                    "Используй когда run_tuya_scene вернул no_match или "
                    "ambiguous, чтобы предложить юзеру варианты по имени."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "enter_away_mode",
                "description": (
                    "Сценарий «уехал из дома»: ВЫКЛЮЧИТЬ всё лишнее (бойлер, "
                    "кондер, телевизор), включить family-mode «trip». "
                    "Триггеры: «я уехал», «уехал из дома», «не дома», «вышли из дома»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "exit_away_mode",
                "description": (
                    "Выключить trip-режим (я дома, вернулся). Триггеры: "
                    "«я дома», «вернулся», «приехал», «дома»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "schedule_homecoming",
                "description": (
                    "Сценарий «еду домой буду в HH:MM». Запланирует подготовку: "
                    "бойлер ON за 3 часа, кондер ON за 1 час (с учётом сезона), "
                    "ТВ остаётся выкл (юзер сам решит). Все три правила пишутся "
                    "в ⚙️ Автоматизации. Триггеры: «еду домой буду в HH:MM», "
                    "«приеду к HH:MM», «дома буду в HH:MM», «возвращаюсь к HH:MM»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "arrival": {
                            "type": "string",
                            "description": "Время прибытия: «в 18:30», «к 21:00», ISO «2026-06-14T18:30».",
                        },
                        "boiler_hours_before": {
                            "type": "integer",
                            "description": "За сколько часов до прибытия включить бойлер. По умолчанию 3.",
                        },
                        "ac_hours_before": {
                            "type": "integer",
                            "description": "За сколько часов до прибытия включить кондер. По умолчанию 1.",
                        },
                        "ac_mode": {
                            "type": "string",
                            "description": "Режим кондера: cold/hot/auto. По умолчанию — выбирай по сезону (лето=cold, зима=hot).",
                        },
                        "ac_temperature": {
                            "type": "integer",
                            "description": "Целевая температура кондера. По умолчанию 22 (cold) / 23 (hot).",
                        },
                    },
                    "required": ["arrival"],
                },
            },
            {
                "name": "smart_sensor_read",
                "description": (
                    "📍 ПРИОРИТЕТ для вопросов про температуру/влажность ДОМА. "
                    "Триггеры: «температура», «температура в детской», «влажность», "
                    "«сколько градусов», «душно ли», «холодно ли», «показания датчиков», "
                    "«как там малышу», «жарко в комнате». "
                    "Если юзер НЕ уточнил «на улице» — это всегда про датчик дома."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "sensor": {"type": "string", "description": "Название датчика, например «детская». Если пусто — вернёт все датчики."},
                    },
                },
            },
            {
                "name": "temperature_full",
                "description": (
                    "Полная температурная сводка: датчики дома + погода на улице "
                    "одним ответом. Используй когда юзер хочет общую картину: "
                    "«как с температурой», «жарко ли», «надо ли проветрить», "
                    "«одеть малыша теплее?»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "add_document",
                "description": (
                    "Записать документ (паспорт/ВУ/военный билет/страховка/виза) с датой истечения. "
                    "Прораб напомнит за месяц до окончания."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "member": {"type": "string", "enum": ["eugene", "marina", "matvey"]},
                        "kind": {"type": "string", "description": "passport/ВУ/military/insurance/visa/birth_certificate"},
                        "number": {"type": "string"},
                        "issued_at": {"type": "string", "description": "YYYY-MM-DD"},
                        "expires_at": {"type": "string", "description": "YYYY-MM-DD"},
                        "notes": {"type": "string"},
                    },
                    "required": ["member", "kind"],
                },
            },
            {
                "name": "list_documents",
                "description": "Показать документы. Сортировка: скоро истекают сверху.",
                "input_schema": {
                    "type": "object",
                    "properties": {"member": {"type": "string"}},
                },
            },
            {
                "name": "add_subscription",
                "description": (
                    "Записать подписку (Netflix/Spotify/мобильный тариф/iCloud и т.п.) "
                    "с суммой и днём списания. Прораб напомнит за день до."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "amount": {"type": "number"},
                        "currency": {"type": "string", "default": "UAH"},
                        "billing_day": {"type": "integer", "description": "1-28"},
                        "notes": {"type": "string"},
                    },
                    "required": ["name", "amount", "billing_day"],
                },
            },
            {
                "name": "list_subscriptions",
                "description": "Показать активные подписки + общая месячная стоимость.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "cancel_subscription",
                "description": "Отметить подписку отменённой (active=0).",
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
            {
                "name": "log_utility_bill",
                "description": (
                    "Записать оплату коммуналки. Используй когда говорят «оплатил газ 450», "
                    "«пришла квитанция за свет 800»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "description": "газ/свет/вода/интернет/квартплата/тепло"},
                        "amount": {"type": "number"},
                        "currency": {"type": "string", "default": "UAH"},
                        "paid": {"type": "boolean", "description": "True если уже оплачено, False если только пришла квитанция"},
                        "due_at": {"type": "string", "description": "YYYY-MM-DD дедлайн оплаты"},
                        "notes": {"type": "string"},
                    },
                    "required": ["kind", "amount"],
                },
            },
            {
                "name": "list_utility_bills",
                "description": "Показать коммуналку за месяц/период с группировкой по типу.",
                "input_schema": {
                    "type": "object",
                    "properties": {"days": {"type": "integer", "default": 60}},
                },
            },
            {
                "name": "log_power_outage",
                "description": (
                    "Зафиксировать отключение света. «света нет» → start. «свет дали» → end. "
                    "Прораб ведёт статистику для прогнозов."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["start", "end"]},
                        "notes": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "probe_luxcloud_hosts",
                "description": (
                    "Диагностика: проверить какие домены LuxCloud доступны "
                    "(eu / inverter / us / asia / luxcloud.eu / api.luxcloud.eu и т.д.). "
                    "Используется когда инвертор перестал отвечать. Триггер: "
                    "«инвертор не отвечает», «проверь хосты луксклауд», «диагностика DNS»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "probe_luxcloud_events",
                "description": (
                    "Диагностика: попробовать все известные API-пути LuxCloud Plant Event "
                    "и показать какие отвечают. Используется чтобы найти рабочий endpoint "
                    "для конкретной версии облака. Триггер: «попробуй найти историю», "
                    "«проверь луксклауд», «диагностика инвертора»."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "record_past_outage",
                "description": (
                    "Вручную добавить запись об отключении света. "
                    "Используй когда юзер диктует данные из приложения инвертора, "
                    "например «запиши отключение 7 июня 01:23 до 02:15»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "started_iso": {"type": "string", "description": "Начало отключения ISO, напр. 2026-06-07T01:23:30"},
                        "ended_iso": {"type": "string", "description": "Конец отключения ISO"},
                        "source": {"type": "string", "description": "Откуда взято: «LuxCloud app» / «вручную»"},
                    },
                    "required": ["started_iso", "ended_iso"],
                },
            },
            {
                "name": "clean_outage_records",
                "description": (
                    "Удалить ложные/устаревшие записи об отключениях света. "
                    "Используй когда юзер говорит «удали ложные» или хочет сбросить историю."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "all": {"type": "boolean", "description": "Удалить ВСЁ"},
                        "before_iso": {"type": "string", "description": "Удалить старше этой даты ISO"},
                        "duration_max_min": {"type": "integer", "description": "Удалить короче N минут (ложные триггеры)"},
                    },
                },
            },
            {
                "name": "power_history_from_inverter",
                "description": (
                    "📍 ПРИОРИТЕТ для вопросов «когда пропадал свет», «когда был свет», "
                    "«отключения за сегодня/ночь», «история света». Берёт ТОЧНЫЕ данные "
                    "из event log инвертора LuxCloud (теже что показывают push в приложении). "
                    "Возвращает периоды Active/Recovered с длительностью."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "hours": {"type": "integer", "description": "За сколько часов назад (по умолчанию 24)"},
                    },
                },
            },
            {
                "name": "power_outage_stats",
                "description": "Статистика по отключениям света за период (всего часов без света, среднее, паттерн).",
                "input_schema": {
                    "type": "object",
                    "properties": {"days": {"type": "integer", "default": 7}},
                },
            },
            {
                "name": "set_family_mode",
                "description": (
                    "Включить/выключить режим семьи. trip — поездка/отпуск (отключает дайджесты, "
                    "меняет приоритеты регионов). sick — кто-то болеет (Айболит активен, тихо). "
                    "quiet — принудительный тихий режим."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["trip", "sick", "quiet"]},
                        "enabled": {"type": "boolean"},
                        "payload": {"type": "string", "description": "Доп.инфо: для trip — куда/до какого числа. Для sick — кто болеет."},
                        "until": {"type": "string", "description": "YYYY-MM-DD до какого числа"},
                    },
                    "required": ["mode", "enabled"],
                },
            },
            {
                "name": "list_active_modes",
                "description": "Показать какие режимы сейчас включены.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "import_milestones_from_diary",
                "description": (
                    "Один раз: пройти по Дневнику и автоматически создать записи в «Достижения» "
                    "для первых вхождений ключевых событий (первый раз кабачок, первое какал, "
                    "перевернулся, сел и т.п.). Не дублирует существующие записи."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "restart_main_service",
                "description": "Перезапустить главный сервис family-hq на Railway. Применяется когда Дозорный добавил новые каналы и нужно чтобы userbot подписался, или когда AI ведёт себя странно. Требует подтверждения от пользователя.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "reason": {"type": "string", "description": "Кратко зачем рестарт"},
                    },
                    "required": ["reason"],
                },
            },
        ]

    async def _call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "read_logs":
            async with self._memory._engine.connect() as conn:
                from src.db.models import EventLog
                from sqlalchemy import select
                query = select(EventLog).order_by(EventLog.created_at.desc()).limit(tool_input.get("limit", 50))
                if tool_input.get("level"):
                    query = query.where(EventLog.level == tool_input["level"])
                if tool_input.get("agent_id"):
                    query = query.where(EventLog.agent_id == tool_input["agent_id"])
                rows = await conn.execute(query)
                return [{"level": r.level, "agent": r.agent_id, "msg": r.message, "at": r.created_at} for r in rows]

        elif tool_name == "create_github_pr" and self._github:
            branch = tool_input["branch"]
            await self._github.create_branch(branch)

            for file_info in tool_input.get("files", []):
                await self._github.create_or_update_file(
                    path=file_info["path"],
                    content=file_info["content"],
                    message=f"[Прораб] {tool_input['title']}",
                    branch=branch,
                )

            pr = await self._github.create_pull_request(
                title=tool_input["title"],
                body=tool_input["body"],
                head_branch=branch,
            )
            return {"pr_url": pr.html_url, "pr_number": pr.number}

        elif tool_name == "ping_external":
            import httpx
            service = tool_input["service"]
            if service == "anthropic_api":
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get("https://api.anthropic.com/v1/models", timeout=10)
                        return {"status": "ok" if resp.status_code < 500 else "degraded"}
                except Exception as e:
                    return {"status": "down", "error": str(e)}
            return {"status": "unknown", "service": service}

        elif tool_name == "read_file":
            import aiofiles
            import os
            path = tool_input["path"].lstrip("/")
            # Security: only allow reading project files
            safe_path = os.path.normpath(os.path.join("/home/user/family-hq", path))
            if not safe_path.startswith("/home/user/family-hq"):
                return {"error": "Access denied"}
            try:
                async with aiofiles.open(safe_path, "r") as f:
                    content = await f.read()
                return {"content": content[:5000], "truncated": len(content) > 5000}
            except FileNotFoundError:
                return {"error": f"File not found: {path}"}

        elif tool_name == "system_status":
            return await self._system_status()

        elif tool_name == "cost_report":
            return await self._cost_report(int(tool_input.get("days", 30)))

        elif tool_name == "set_family_fact":
            return await self._set_family_fact(tool_input.get("key", ""), tool_input.get("value", ""))

        elif tool_name == "family_wiki":
            return await self._family_wiki(tool_input.get("section", "all"))

        elif tool_name == "write_time_capsule":
            return await self._write_time_capsule(tool_input.get("title", ""), tool_input.get("text", ""))

        elif tool_name == "add_automation_rule":
            return await self._automation_add(tool_input)
        elif tool_name == "list_automation_rules":
            return await self._automation_list()
        elif tool_name == "toggle_automation_rule":
            return await self._automation_toggle(tool_input.get("name", ""), bool(tool_input.get("enabled", True)))
        elif tool_name == "delete_automation_rule":
            return await self._automation_delete(tool_input.get("name", ""))
        elif tool_name == "delete_all_automation_rules":
            return await self._automation_delete_all()
        elif tool_name == "repair_automation_rules":
            import json as _json
            from sqlalchemy import select, update as sql_update
            from src.db.models import AutomationRule
            fixed: list[str] = []
            unchanged: list[str] = []
            errors: list[str] = []
            async with self._memory._engine.begin() as conn:
                rows = list(await conn.execute(select(AutomationRule)))
                for r in rows:
                    try:
                        old_c = _json.loads(r.condition or "{}")
                        old_a = _json.loads(r.action or "{}")
                        new_c = self._normalize_rule_dict(old_c)
                        new_a = self._normalize_rule_dict(old_a)
                        if new_c == old_c and new_a == old_a:
                            unchanged.append(r.name)
                            continue
                        await conn.execute(
                            sql_update(AutomationRule)
                            .where(AutomationRule.name == r.name)
                            .values(
                                condition=_json.dumps(new_c, ensure_ascii=False),
                                action=_json.dumps(new_a, ensure_ascii=False),
                            )
                        )
                        fixed.append(r.name)
                    except Exception as e:
                        errors.append(f"{r.name}: {e}")
            # Re-mirror everything into notebook so the user sees fresh triggers/actions
            peers = getattr(self, "_peer_agents", {})
            sheets = getattr(peers.get("nanny"), "_sheets", None)
            if sheets:
                async with self._memory._engine.connect() as conn:
                    rows2 = list(await conn.execute(select(AutomationRule)))
                for r in rows2:
                    try:
                        await self._notebook_mirror_rule(
                            name=r.name,
                            description=r.description or "",
                            condition=_json.loads(r.condition or "{}"),
                            action=_json.loads(r.action or "{}"),
                            enabled=bool(r.enabled),
                            cooldown_min=r.cooldown_min or 60,
                        )
                    except Exception as e:
                        errors.append(f"mirror {r.name}: {e}")
            return {
                "total": len(fixed) + len(unchanged),
                "fixed": fixed, "unchanged": unchanged, "errors": errors,
                "display_instruction": (
                    "Скажи юзеру: «✅ Починил <fixed.length> из <total> правил. "
                    "Открой вкладку «⚙️ Автоматизации» и проверь триггеры — "
                    "вместо «нераспозн.» должны быть нормальные описания.»"
                ),
            }

        elif tool_name == "inspect_automation_rule":
            from sqlalchemy import select
            from src.db.models import AutomationRule
            name = tool_input.get("name", "")
            async with self._memory._engine.connect() as conn:
                row = (await conn.execute(
                    select(AutomationRule).where(AutomationRule.name == name)
                )).first()
            if not row:
                return {"error": f"Правило {name!r} не найдено."}
            return {
                "name": row.name,
                "description": row.description,
                "enabled": bool(row.enabled),
                "cooldown_min": row.cooldown_min,
                "condition_json": row.condition,
                "action_json": row.action,
                "last_fired_at": row.last_fired_at,
                "display_instruction": (
                    "Покажи юзеру condition_json и action_json В ТОЧНОСТИ как "
                    "пришло, БЕЗ переформатирования. Если есть очевидная "
                    "ошибка в JSON — укажи её одной строкой в конце."
                ),
            }

        elif tool_name == "wiki_set":
            return await self._wiki_set(
                tool_input.get("member", "family"),
                tool_input.get("key", ""),
                tool_input.get("value", ""),
            )
        elif tool_name == "wiki_list":
            return await self._wiki_list(tool_input.get("member"))
        elif tool_name == "wiki_delete":
            return await self._wiki_delete(
                tool_input.get("member", ""), tool_input.get("key", ""),
            )

        elif tool_name == "family_search":
            return await self._family_search(
                tool_input.get("query", ""),
                int(tool_input.get("days_back", 365)),
            )
        elif tool_name == "parcel_track":
            return await self._parcel_track(
                tool_input.get("ttn", ""), tool_input.get("title", ""),
                "family", tool_input.get("phone_last4", ""),
            )
        elif tool_name == "parcel_list":
            return await self._parcel_list()

        elif tool_name == "ai_set_provider":
            from src.integrations.claude_client import set_provider_override
            prov = tool_input.get("provider", "off")
            until = tool_input.get("until")
            target = None if prov == "off" else prov
            return set_provider_override(target, until)

        elif tool_name == "ai_status":
            from src.config import get_settings
            from src.integrations.claude_client import get_ai_stats
            stats = get_ai_stats()
            settings = get_settings()
            primary = bool(getattr(settings, "gemini_api_key", ""))
            extras_raw = getattr(settings, "gemini_api_keys", "") or ""
            extras = [k.strip() for k in extras_raw.split(",") if k.strip()]
            stats["gemini_configured"] = primary or bool(extras)
            stats["gemini_key_count"] = (1 if primary else 0) + len(extras)
            stats["anthropic_primary_set"] = bool(getattr(settings, "anthropic_api_key_primary", ""))
            stats["anthropic_backup_set"] = bool(getattr(settings, "anthropic_api_key_backup", ""))
            stats["display_instruction"] = (
                "Покажи юзеру кратко: какой провайдер сейчас работает "
                "(current_provider), сколько успешных вызовов у каждого, "
                "сколько падений, сколько ключей Gemini загружено "
                "(gemini_key_count) и last_gemini_error если есть."
            )
            return stats

        elif tool_name == "gemini_discover_models":
            from src.config import get_settings
            from src.integrations.gemini_client import discover_models
            import aiohttp
            settings = get_settings()
            primary = getattr(settings, "gemini_api_key", "")
            extras_raw = getattr(settings, "gemini_api_keys", "") or ""
            extras = [k.strip() for k in extras_raw.split(",") if k.strip()]
            all_keys: list[str] = []
            if primary:
                all_keys.append(primary)
            all_keys.extend(extras)
            if not all_keys:
                return {"error": "Не задан ни GEMINI_API_KEY ни GEMINI_API_KEYS"}
            configured = getattr(settings, "gemini_model", "")
            test_body = {
                "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
                "generationConfig": {"maxOutputTokens": 5},
            }
            test_models = (
                "gemini-flash-lite-latest",
                "gemini-2.5-flash-lite",
                "gemini-2.0-flash-lite",
                "gemini-2.5-flash",
                "gemini-2.0-flash",
                "gemini-1.5-flash",
            )
            per_key = []
            async with aiohttp.ClientSession() as session:
                for key_idx, key in enumerate(all_keys):
                    models = await discover_models(key)
                    probes = []
                    for m in test_models:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
                        try:
                            async with session.post(url, json=test_body) as resp:
                                status = resp.status
                                err_snippet = ""
                                if status >= 400:
                                    err_snippet = (await resp.text())[:120]
                                probes.append({
                                    "model": m, "status": status,
                                    "ok": status < 400,
                                    "error": err_snippet,
                                })
                        except Exception as e:
                            probes.append({
                                "model": m, "status": "exception",
                                "error": str(e)[:80], "ok": False,
                            })
                    per_key.append({
                        "key_index": key_idx,
                        "key_suffix": key[-6:] if len(key) > 6 else "(short)",
                        "discovered_count": len(models),
                        "discovered_sample": models[:5],
                        "probes": probes,
                        "working": [p["model"] for p in probes if p.get("ok")],
                    })
            return {
                "configured_model": configured,
                "total_keys": len(all_keys),
                "per_key": per_key,
                "display_instruction": (
                    "Покажи юзеру для КАЖДОГО ключа: суффикс (key_suffix), "
                    "сколько моделей он видит (discovered_count), и какие из "
                    "тестовых моделей реально отвечают (working). "
                    "Если у ключа discovered_count=0 — значит у него не включён "
                    "Generative Language API в его Google Cloud проекте. "
                    "Если working=[] и все probes показывают 429 — реально квота. "
                    "Если 403 — права/API не включён."
                ),
            }

        elif tool_name == "gemini_ping":
            from src.config import get_settings
            from src.integrations.gemini_client import GeminiClient
            settings = get_settings()
            client = GeminiClient.from_settings(settings)
            if not client:
                return {"status": "not_configured",
                        "message": "GEMINI_API_KEY не задан в Railway env"}
            # Test BOTH paths: plain complete() and tool-using complete_with_tools().
            # If lite works for plain but fails for tools, we know lite doesn't
            # support function calling and we need a flash-variant for tool calls.
            plain_ok = False
            plain_err = None
            tool_ok = False
            tool_err = None
            try:
                reply = await client.complete(
                    system="Ответь одним словом.",
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=10,
                )
                plain_ok = True
            except Exception as e:
                plain_err = str(e)[:200]
            try:
                msg = await client.complete_with_tools(
                    system="Используй tool get_weather с city='Odessa'.",
                    messages=[{"role": "user", "content": "Какая погода?"}],
                    tools=[{
                        "name": "get_weather",
                        "description": "Get weather",
                        "input_schema": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    }],
                    max_tokens=100,
                )
                tool_ok = True
            except Exception as e:
                tool_err = str(e)[:200]
            return {
                "configured_model": client.model,
                "working_model": client._working_model,
                "plain_complete": "✅" if plain_ok else f"❌ {plain_err}",
                "complete_with_tools": "✅" if tool_ok else f"❌ {tool_err}",
                "display_instruction": (
                    "Скажи юзеру: какая модель configured/working, "
                    "работает ли plain и tool режимы по отдельности. "
                    "Если plain ✅ а tool ❌ — значит модель не поддерживает "
                    "function calling, надо в env поставить другую "
                    "(gemini-2.0-flash, gemini-1.5-flash)."
                ),
            }

        elif tool_name == "morning_brief_now":
            from src.scheduler.morning_brief import send_morning_brief
            peers = getattr(self, "_peer_agents", {})
            await send_morning_brief(
                self, peers.get("news"), peers.get("nanny"),
                peers.get("calendar"), self._memory,
            )
            return {"status": "sent"}

        elif tool_name == "list_smart_devices":
            return await self._smart_list()

        elif tool_name == "vacuum_status":
            return await self._vacuum_status(tool_input.get("name", ""))
        elif tool_name == "vacuum_start":
            return await self._vacuum_start(tool_input.get("name", ""), tool_input.get("mode", "auto"))
        elif tool_name == "vacuum_stop":
            return await self._vacuum_stop(tool_input.get("name", ""))

        elif tool_name == "backfill_photo_dates":
            return await self._backfill_photo_dates()

        elif tool_name == "list_baby_photos":
            return await self._list_baby_photos(
                bool(tool_input.get("missing_only", False))
            )

        elif tool_name == "cleanup_orphan_photos":
            return await self._cleanup_orphan_photos(
                dry_run=bool(tool_input.get("dry_run", False))
            )

        elif tool_name == "sync_photos_with_drive":
            return await self._sync_photos_with_drive(
                months=int(tool_input.get("months", 3))
            )

        elif tool_name == "set_photo_caption":
            from sqlalchemy import update as sql_update
            from src.db.models import BabyPhoto
            photo_id = int(tool_input.get("photo_id", 0))
            caption = (tool_input.get("caption") or "").strip()[:120]
            if not (photo_id and caption):
                return {"error": "photo_id и caption обязательны"}
            async with self._memory._engine.begin() as conn:
                res = await conn.execute(
                    sql_update(BabyPhoto).where(BabyPhoto.id == photo_id).values(
                        caption=caption,
                    )
                )
            if not res.rowcount:
                return {"error": f"Фото id={photo_id} не найдено"}
            return {"updated_id": photo_id, "caption": caption}

        elif tool_name == "set_photo_date":
            return await self._set_photo_date(
                int(tool_input.get("photo_id", 0)),
                tool_input.get("date", ""),
            )

        elif tool_name == "chronicle_now":
            from datetime import datetime, timedelta
            from src.config import get_settings
            from src.integrations.drive import DriveClient
            from src.scheduler.chronicle import generate_weekly_chronicle
            from src.utils.time import KYIV_TZ, now_kyiv

            def _parse(s: str):
                s = (s or "").strip()
                for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
                    try:
                        d = datetime.strptime(s, fmt)
                        return d.replace(tzinfo=KYIV_TZ)
                    except ValueError:
                        continue
                return None

            start_dt = _parse(tool_input.get("start_date", ""))
            end_dt = _parse(tool_input.get("end_date", ""))
            if start_dt and not end_dt:
                end_dt = start_dt + timedelta(days=7)
            if end_dt and not start_dt:
                start_dt = end_dt - timedelta(days=7)
            if end_dt:
                end_dt = end_dt + timedelta(days=1)

            # Dedup guard: prevent the LLM tool-loop from firing the same
            # chronicle generation 5 times in a row. The tool returns
            # `status: started` and the actual PDF goes to chat via a
            # different code path — the LLM doesn't see the result so it
            # often re-decides to call us again. Same (start, end) within
            # 90 seconds → no-op.
            key = (
                start_dt.isoformat() if start_dt else "",
                end_dt.isoformat() if end_dt else "",
            )
            now_ts = now_kyiv().timestamp()
            recent = getattr(self, "_chronicle_recent", {})
            last = recent.get(key)
            if last and (now_ts - last) < 90:
                return {
                    "status": "deduped",
                    "display_instruction": (
                        "Скажи юзеру: «📖 Хроника уже запущена минуту назад, "
                        "жду пока придёт PDF. Не дёргай повторно.» Не вызывай "
                        "chronicle_now снова — PDF уже идёт."
                    ),
                }
            recent[key] = now_ts
            # Trim old entries to prevent unbounded growth
            self._chronicle_recent = {
                k: v for k, v in recent.items() if now_ts - v < 600
            }

            await generate_weekly_chronicle(
                self._memory, self._bots, self._chat_id,
                DriveClient.from_settings(get_settings()),
                start_dt=start_dt, end_dt=end_dt,
                force=bool(tool_input.get("force", False)),
            )
            return {
                "status": "started",
                "display_instruction": (
                    "Скажи юзеру: «📖 Запустил генерацию хроники, ссылку "
                    "пришлю сразу как готова». Сам PDF Прораб не показывает — "
                    "хроника шлёт отдельным сообщением со ссылкой на Drive. "
                    "НЕ вызывай chronicle_now повторно — одного раза достаточно."
                ),
            }

        elif tool_name == "battery_autonomy":
            return await self._battery_autonomy()

        elif tool_name == "notebook_add":
            peers = getattr(self, "_peer_agents", {})
            sheets = getattr(peers.get("nanny"), "_sheets", None)
            if not sheets:
                return {"error": "Google Sheets не настроен — блокнот недоступен."}
            from src.integrations.prorab_notebook import add_task
            return await add_task(
                sheets,
                task=tool_input.get("task", ""),
                due_at=tool_input.get("due_at", ""),
                note=tool_input.get("note", ""),
            )

        elif tool_name == "notebook_list":
            peers = getattr(self, "_peer_agents", {})
            sheets = getattr(peers.get("nanny"), "_sheets", None)
            if not sheets:
                return {"error": "Google Sheets не настроен — блокнот недоступен."}
            from src.integrations.prorab_notebook import list_tasks
            status = tool_input.get("status", "open")
            tasks = await list_tasks(sheets, status=None if status == "all" else status)
            return {
                "count": len(tasks),
                "tasks": tasks[-50:],
                "display_instruction": (
                    "Если задач нет — скажи «📋 Блокнот пустой». "
                    "Иначе покажи списком: '◆ #ID — задача (срок: ...)'."
                ),
            }

        elif tool_name == "notebook_done":
            peers = getattr(self, "_peer_agents", {})
            sheets = getattr(peers.get("nanny"), "_sheets", None)
            if not sheets:
                return {"error": "Google Sheets не настроен — блокнот недоступен."}
            from src.integrations.prorab_notebook import mark_status
            return await mark_status(
                sheets,
                task_id=int(tool_input.get("id", 0)),
                status="done",
                note=tool_input.get("note", ""),
            )

        elif tool_name == "schedule_device_action":
            return await self._schedule_device_action(
                device=tool_input.get("device", ""),
                action=tool_input.get("action", "on"),
                when=tool_input.get("when", ""),
            )

        elif tool_name == "notebook_sync_rules":
            import json as _json
            from sqlalchemy import select
            from src.db.models import AutomationRule
            peers = getattr(self, "_peer_agents", {})
            sheets = getattr(peers.get("nanny"), "_sheets", None)
            if not sheets:
                return {"error": "Sheets не настроен — блокнот недоступен."}
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(AutomationRule).where(AutomationRule.enabled == 1)
                ))
            added: list[str] = []
            skipped: list[str] = []
            errors: list[str] = []
            for r in rows:
                try:
                    condition = _json.loads(r.condition or "{}")
                    action = _json.loads(r.action or "{}")
                except Exception as e:
                    errors.append(f"{r.name}: bad json {e}")
                    continue
                # Compare rules tab before/after — the previous version
                # compared the manual-tasks tab (📋 Блокнот), which never
                # changes during a rules sync, so this always reported
                # "skipped" even when a row was actually added.
                from src.integrations.prorab_notebook import list_rules_from_sheet
                try:
                    before_names = {
                        x["name"] for x in await list_rules_from_sheet(sheets)
                    }
                    await self._notebook_mirror_rule(
                        name=r.name,
                        description=r.description or "",
                        condition=condition,
                        action=action,
                    )
                    after_names = {
                        x["name"] for x in await list_rules_from_sheet(sheets)
                    }
                    if r.name in after_names and r.name not in before_names:
                        added.append(r.name)
                    else:
                        skipped.append(r.name)
                except Exception as e:
                    errors.append(f"{r.name}: {e}")
            return {
                "total_rules": len(rows),
                "added": added,
                "already_present": skipped,
                "errors": errors,
                "display_instruction": (
                    "Скажи юзеру: «📋 Синхронизировал блокнот. "
                    "Добавлено: <added.length>, уже было: <already_present.length>»."
                    "Если errors не пустой — покажи их одной строкой."
                ),
            }

        elif tool_name == "notebook_diag":
            peers = getattr(self, "_peer_agents", {})
            sheets = getattr(peers.get("nanny"), "_sheets", None)
            if not sheets:
                return {
                    "ok": False,
                    "step": "config",
                    "error": "У nanny нет атрибута _sheets — SheetsClient не инициализирован. Проверь env GOOGLE_SERVICE_ACCOUNT_JSON и SHEET_BABY_ID.",
                }
            try:
                gc = await sheets._get_client()
            except Exception as e:
                return {"ok": False, "step": "gspread_auth", "error": f"{type(e).__name__}: {e}"}
            try:
                spreadsheet = await sheets._run_sync(gc.open_by_key, sheets._baby_sheet_id)
            except Exception as e:
                return {
                    "ok": False, "step": "open_spreadsheet",
                    "error": f"{type(e).__name__}: {e}",
                    "hint": "Проверь что service account имеет доступ Editor к таблице по ID " + str(sheets._baby_sheet_id),
                }
            try:
                titles = await sheets._run_sync(lambda: [w.title for w in spreadsheet.worksheets()])
            except Exception as e:
                return {"ok": False, "step": "list_worksheets", "error": f"{type(e).__name__}: {e}"}
            from src.integrations.prorab_notebook import WORKSHEET, _ensure_worksheet
            already = WORKSHEET in titles
            try:
                await _ensure_worksheet(sheets)
            except Exception as e:
                return {
                    "ok": False, "step": "ensure_worksheet",
                    "error": f"{type(e).__name__}: {e}",
                    "existing_tabs": titles,
                    "target_name": WORKSHEET,
                }
            return {
                "ok": True,
                "worksheet_name": WORKSHEET,
                "already_existed": already,
                "existing_tabs": titles,
                "display_instruction": (
                    "Скажи юзеру: 'Вкладка <name> создана/найдена. "
                    "Список существующих вкладок: ...'. "
                    "Если already_existed=False — попроси юзера обновить таблицу в браузере."
                ),
            }

        elif tool_name == "solar_status":
            return await self._solar_status()
        elif tool_name == "solar_today":
            return await self._solar_today()
        elif tool_name == "plan_trip":
            return await self._plan_trip(tool_input)

        elif tool_name == "control_smart_device":
            return await self._smart_control(tool_input.get("device", ""), tool_input.get("action", "status"))

        elif tool_name == "control_device_for_duration":
            return await self._control_device_for_duration(
                device=tool_input.get("device", ""),
                action=tool_input.get("action", "on"),
                duration_min=int(tool_input.get("duration_min", 10)),
            )

        elif tool_name == "smart_set_temperature":
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            client = TuyaClient.from_settings(get_settings())
            if not client:
                return {"error": "Tuya не настроен"}
            return await client.set_temperature(
                tool_input.get("device", ""),
                int(tool_input.get("temperature", 24)),
            )

        elif tool_name == "smart_set_mode":
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            client = TuyaClient.from_settings(get_settings())
            if not client:
                return {"error": "Tuya не настроен"}
            return await client.set_mode(
                tool_input.get("device", ""),
                tool_input.get("mode", "auto"),
                temperature=int(tool_input.get("temperature", 24)),
            )

        elif tool_name == "smart_set_fan_speed":
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            client = TuyaClient.from_settings(get_settings())
            if not client:
                return {"error": "Tuya не настроен"}
            return await client.set_fan_speed(
                tool_input.get("device", ""),
                tool_input.get("speed", "auto"),
                mode=tool_input.get("mode"),
                temperature=tool_input.get("temperature"),
            )

        elif tool_name == "dump_device_dps":
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            client = TuyaClient.from_settings(get_settings())
            if not client:
                return {"error": "Tuya не настроен"}
            devices = await client.list_devices()
            target = client._find_device(devices, tool_input.get("device", ""))
            if not target:
                return {
                    "error": f"Не нашёл устройство '{tool_input.get('device')}'",
                    "available": [d["name"] for d in devices],
                }
            # Translate raw Tuya DPs into a human-readable card.
            dps = {s.get("code", ""): s.get("value") for s in target.get("status", []) or []}
            lines = [f"🛠 <b>{target['name']}</b>"]
            lines.append("🟢 online" if target.get("online") else "🔴 offline")

            # Switch state
            switch_val = None
            for code in ("switch", "switch_1", "switch_led"):
                if code in dps:
                    switch_val = dps[code]
                    break
            if switch_val is not None:
                lines.append("🔌 Включён" if switch_val else "⚫ Выключен")

            # Power (0.1 W units на большинстве плагов)
            if "cur_power" in dps and dps["cur_power"] is not None:
                try:
                    p = float(dps["cur_power"]) * 0.1
                    if p < 1:
                        lines.append(f"⚡ Мощность: 0 Вт (standby)")
                    else:
                        lines.append(f"⚡ Мощность: <b>{p:.0f} Вт</b>")
                except (TypeError, ValueError):
                    pass
            # Voltage (0.1 V units)
            if "cur_voltage" in dps and dps["cur_voltage"] is not None:
                try:
                    v = float(dps["cur_voltage"]) * 0.1
                    lines.append(f"🔋 Напряжение: {v:.1f} В")
                except (TypeError, ValueError):
                    pass
            # Current (mA)
            if "cur_current" in dps and dps["cur_current"] is not None:
                try:
                    a_ma = float(dps["cur_current"])
                    if a_ma < 1000:
                        lines.append(f"📈 Ток: {int(a_ma)} мА")
                    else:
                        lines.append(f"📈 Ток: {a_ma / 1000:.2f} А")
                except (TypeError, ValueError):
                    pass
            # Energy counter (0.01 kWh units typical для add_ele)
            if "add_ele" in dps and dps["add_ele"] is not None:
                try:
                    e_kwh = float(dps["add_ele"]) * 0.01
                    lines.append(f"📊 Накоплено: {e_kwh:.2f} кВт·ч")
                except (TypeError, ValueError):
                    pass
            # Countdown timer
            if "countdown_1" in dps and dps["countdown_1"]:
                try:
                    sec = int(dps["countdown_1"])
                    if sec > 0:
                        lines.append(f"⏳ Таймер: ещё {sec // 60} мин")
                except (TypeError, ValueError):
                    pass
            # Fault
            if "fault" in dps:
                lines.append("✅ Без ошибок" if not dps["fault"] else f"⚠️ Ошибка: {dps['fault']}")

            return {
                "pretty": "\n".join(lines),
                "display_instruction": (
                    "Отправь юзеру поле `pretty` КАК ЕСТЬ. Без своих "
                    "комментариев, без префиксов 'вот', без эмодзи "
                    "помимо тех что в pretty. ОДНИМ блоком."
                ),
            }

        elif tool_name == "inverter_runtime":
            from src.config import get_settings
            from src.integrations.luxcloud import LuxCloudClient
            from src.integrations.tuya import TuyaClient
            from src.utils.inverter import runtime_report
            settings = get_settings()
            lux = LuxCloudClient.from_settings(settings)
            if not lux:
                return {"error": "LuxCloud не настроен"}
            try:
                data = await lux.runtime()
            except Exception as e:
                return {"error": f"LuxCloud недоступен: {type(e).__name__}: {e}"}
            tuya = TuyaClient.from_settings(settings)
            report = await runtime_report(
                lux_data=data,
                capacity_wh=int(getattr(settings, "battery_capacity_wh", 5184)),
                reserve_pct=int(getattr(settings, "battery_reserve_pct", 20)),
                tuya_client=tuya,
            )
            return report

        elif tool_name == "run_tuya_scene":
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            client = TuyaClient.from_settings(get_settings())
            if not client:
                return {"error": "Tuya не настроен"}
            query = str(tool_input.get("query", "")).strip()
            if not query:
                return {"error": "пустой query"}
            match = await client.find_scene(query)
            if not match:
                scenes = await client.list_scenes()
                return {
                    "no_match": True,
                    "query": query,
                    "available_scenes": [s["name"] for s in scenes],
                    "hint": "ни одна сцена не подошла. Перечисли юзеру available_scenes и спроси какую запустить.",
                }
            if match.get("ambiguous"):
                return {
                    "ambiguous": True,
                    "query": query,
                    "candidates": [c["name"] for c in match.get("candidates", [])],
                    "hint": "несколько сцен подходят одинаково. Переспроси юзера какую именно.",
                }
            result = await client.run_scene(match["id"])
            if result.get("success"):
                try:
                    from src.utils.family import track_user_action
                    track_user_action(f"сцена: {match['name']}")
                except Exception:
                    pass
            return {
                "matched_scene": match["name"],
                "scene_id": match["id"],
                "success": result.get("success", False),
                "raw": result.get("raw", ""),
            }

        elif tool_name == "diagnose_tuya_scenes":
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            client = TuyaClient.from_settings(get_settings())
            if not client:
                return {"error": "Tuya не настроен"}
            return await client.diagnose_scenes()

        elif tool_name == "list_tuya_scenes":
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            client = TuyaClient.from_settings(get_settings())
            if not client:
                return {"error": "Tuya не настроен"}
            scenes = await client.list_scenes()
            return {"scenes": [s["name"] for s in scenes], "count": len(scenes)}

        elif tool_name == "enter_away_mode":
            return await self._enter_away_mode()

        elif tool_name == "exit_away_mode":
            return await self._exit_away_mode()

        elif tool_name == "schedule_homecoming":
            return await self._schedule_homecoming(
                arrival=tool_input.get("arrival", ""),
                boiler_hours_before=int(tool_input.get("boiler_hours_before", 3)),
                ac_hours_before=int(tool_input.get("ac_hours_before", 1)),
                ac_mode=tool_input.get("ac_mode", "") or "",
                ac_temperature=int(tool_input.get("ac_temperature", 0)),
            )

        elif tool_name == "temperature_full":
            return await self._temperature_full()
        elif tool_name == "smart_sensor_read":
            return await self._smart_sensor(tool_input.get("sensor", ""))

        elif tool_name == "add_document":
            from sqlalchemy import insert
            from src.db.models import Document
            async with self._memory._engine.begin() as conn:
                result = await conn.execute(insert(Document).values(
                    member=tool_input["member"], kind=tool_input["kind"],
                    number=tool_input.get("number"), issued_at=tool_input.get("issued_at"),
                    expires_at=tool_input.get("expires_at"), notes=tool_input.get("notes"),
                ))
            return {"success": True, "id": result.inserted_primary_key[0] if result.inserted_primary_key else None}

        elif tool_name == "list_documents":
            from sqlalchemy import select
            from src.db.models import Document
            async with self._memory._engine.connect() as conn:
                stmt = select(Document)
                if tool_input.get("member"):
                    stmt = stmt.where(Document.member == tool_input["member"])
                rows = list(await conn.execute(stmt))
            from datetime import date
            today = date.today().isoformat()
            items = []
            for r in rows:
                days_left = None
                if r.expires_at:
                    try:
                        days_left = (date.fromisoformat(r.expires_at) - date.today()).days
                    except Exception:
                        pass
                items.append({
                    "id": r.id, "member": r.member, "kind": r.kind, "number": r.number,
                    "expires_at": r.expires_at, "days_left": days_left, "notes": r.notes,
                })
            items.sort(key=lambda x: x["days_left"] if x["days_left"] is not None else 99999)
            return {"count": len(items), "documents": items}

        elif tool_name == "add_subscription":
            from sqlalchemy import insert
            from src.db.models import Subscription
            async with self._memory._engine.begin() as conn:
                result = await conn.execute(insert(Subscription).values(
                    name=tool_input["name"], amount=tool_input["amount"],
                    currency=tool_input.get("currency", "UAH"),
                    billing_day=int(tool_input["billing_day"]),
                    notes=tool_input.get("notes"),
                ))
            return {"success": True, "id": result.inserted_primary_key[0] if result.inserted_primary_key else None}

        elif tool_name == "list_subscriptions":
            from sqlalchemy import select
            from src.db.models import Subscription
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(select(Subscription).where(Subscription.active == 1)))
            total = sum(r.amount for r in rows)
            return {
                "count": len(rows), "total_month": round(total, 2),
                "items": [{"id": r.id, "name": r.name, "amount": r.amount,
                           "currency": r.currency, "billing_day": r.billing_day} for r in rows],
            }

        elif tool_name == "cancel_subscription":
            from sqlalchemy import select, update as sql_update
            from src.db.models import Subscription
            async with self._memory._engine.begin() as conn:
                res = await conn.execute(
                    sql_update(Subscription).where(Subscription.name == tool_input["name"]).values(active=0)
                )
            return {"success": True, "cancelled": res.rowcount}

        elif tool_name == "log_utility_bill":
            from sqlalchemy import insert
            from src.db.models import UtilityBill
            from src.utils.time import iso_now
            paid = bool(tool_input.get("paid", True))
            async with self._memory._engine.begin() as conn:
                result = await conn.execute(insert(UtilityBill).values(
                    kind=tool_input["kind"], amount=tool_input["amount"],
                    currency=tool_input.get("currency", "UAH"),
                    paid_at=iso_now() if paid else None,
                    due_at=tool_input.get("due_at"),
                    notes=tool_input.get("notes"),
                ))
            return {"success": True, "paid": paid}

        elif tool_name == "list_utility_bills":
            from datetime import timedelta
            from sqlalchemy import select
            from src.db.models import UtilityBill
            from src.utils.time import now_kyiv
            days = int(tool_input.get("days", 60))
            cutoff = (now_kyiv() - timedelta(days=days)).isoformat()
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(select(UtilityBill)))
            recent = []
            by_kind: dict[str, float] = {}
            for r in rows:
                marker = r.paid_at or r.due_at or ""
                if marker and marker < cutoff:
                    continue
                recent.append({
                    "id": r.id, "kind": r.kind, "amount": r.amount,
                    "paid_at": r.paid_at, "due_at": r.due_at, "notes": r.notes,
                })
                by_kind[r.kind] = by_kind.get(r.kind, 0) + r.amount
            return {"days": days, "by_kind_total": by_kind, "items": recent}

        elif tool_name == "log_power_outage":
            from sqlalchemy import insert, select, update as sql_update
            from src.db.models import PowerOutage
            from src.utils.time import iso_now, now_kyiv
            action = tool_input["action"]
            automation = getattr(self, "_automation", None)
            if action == "start":
                # Idempotency — if an open outage already exists, don't
                # start another. Just return the existing one.
                async with self._memory._engine.begin() as conn:
                    open_row = (await conn.execute(
                        select(PowerOutage).where(PowerOutage.ended_at.is_(None))
                        .order_by(PowerOutage.id.desc()).limit(1)
                    )).first()
                    if open_row:
                        return {
                            "success": True, "status": "already_open",
                            "id": open_row.id, "started_at": open_row.started_at,
                        }
                    result = await conn.execute(insert(PowerOutage).values(
                        started_at=iso_now(), notes=tool_input.get("notes"),
                    ))
                # Trigger user automations now (boiler off etc.) — previously
                # this tool only wrote to DB and didn't fire any rules.
                triggered = False
                if automation:
                    try:
                        await automation.trigger_power_outage(active=True)
                        triggered = True
                    except Exception:
                        log.exception("log_power_outage_trigger_failed")
                return {
                    "success": True, "status": "started",
                    "id": result.inserted_primary_key[0] if result.inserted_primary_key else None,
                    "automations_triggered": triggered,
                }
            else:  # end
                async with self._memory._engine.begin() as conn:
                    last = (await conn.execute(
                        select(PowerOutage).where(PowerOutage.ended_at.is_(None))
                        .order_by(PowerOutage.id.desc()).limit(1)
                    )).first()
                    if not last:
                        return {"success": False, "error": "Нет открытого отключения"}
                    from datetime import datetime
                    started = datetime.fromisoformat(last.started_at)
                    duration_min = int((now_kyiv() - started).total_seconds() / 60)
                    await conn.execute(
                        sql_update(PowerOutage).where(PowerOutage.id == last.id).values(
                            ended_at=iso_now(), duration_min=duration_min,
                        )
                    )
                triggered = False
                if automation:
                    try:
                        await automation.trigger_power_outage(active=False)
                        triggered = True
                    except Exception:
                        log.exception("log_power_outage_trigger_failed")
                return {
                    "success": True, "duration_min": duration_min,
                    "automations_triggered": triggered,
                }

        elif tool_name == "probe_luxcloud_hosts":
            from src.config import get_settings
            from src.integrations.luxcloud import LuxCloudClient
            client = LuxCloudClient.from_settings(get_settings())
            if not client:
                return {"error": "LuxCloud не настроен"}
            return await client.probe_hosts()

        elif tool_name == "probe_luxcloud_events":
            from src.config import get_settings
            from src.integrations.luxcloud import LuxCloudClient
            client = LuxCloudClient.from_settings(get_settings())
            if not client:
                return {"error": "LuxCloud не настроен"}
            return await client.probe_event_endpoints()

        elif tool_name == "record_past_outage":
            return await self._record_past_outage(tool_input)
        elif tool_name == "clean_outage_records":
            return await self._clean_outage_records(tool_input)
        elif tool_name == "power_history_from_inverter":
            return await self._power_history_from_inverter(int(tool_input.get("hours", 24)))

        elif tool_name == "power_outage_stats":
            from datetime import timedelta
            from sqlalchemy import select
            from src.db.models import PowerOutage
            from src.utils.time import now_kyiv
            days = int(tool_input.get("days", 7))
            cutoff = (now_kyiv() - timedelta(days=days)).isoformat()
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(
                    select(PowerOutage).where(PowerOutage.started_at >= cutoff)
                ))
            closed = [r for r in rows if r.duration_min is not None]
            total_min = sum(r.duration_min for r in closed)
            return {
                "days": days, "outages_count": len(rows),
                "still_no_light": any(r.ended_at is None for r in rows),
                "total_hours_without_light": round(total_min / 60, 1),
                "avg_min_per_outage": round(total_min / max(len(closed), 1)),
                "raw": [{"started": r.started_at, "ended": r.ended_at,
                         "duration_min": r.duration_min} for r in rows[-20:]],
            }

        elif tool_name == "set_family_mode":
            import json as _json
            from sqlalchemy import insert
            from sqlalchemy import select, update as sql_update
            from src.db.models import FamilyMode
            from src.utils.time import iso_now
            payload = tool_input.get("payload")
            payload_str = _json.dumps({"info": payload}) if payload else None
            mode_name = tool_input["mode"]
            enabled_val = 1 if tool_input.get("enabled") else 0
            async with self._memory._engine.begin() as conn:
                existing = (await conn.execute(
                    select(FamilyMode).where(FamilyMode.name == mode_name)
                )).first()
                if existing:
                    # Preserve the original started_at — toggling enabled
                    # shouldn't reset the start time we recorded earlier.
                    await conn.execute(
                        sql_update(FamilyMode).where(FamilyMode.name == mode_name).values(
                            enabled=enabled_val,
                            payload=payload_str,
                            expires_at=tool_input.get("until"),
                        )
                    )
                else:
                    await conn.execute(insert(FamilyMode).values(
                        name=mode_name,
                        enabled=enabled_val,
                        payload=payload_str,
                        started_at=iso_now(),
                        expires_at=tool_input.get("until"),
                    ))
            return {"success": True, "mode": mode_name, "enabled": tool_input.get("enabled")}

        elif tool_name == "list_active_modes":
            from sqlalchemy import select
            from src.db.models import FamilyMode
            async with self._memory._engine.connect() as conn:
                rows = list(await conn.execute(select(FamilyMode).where(FamilyMode.enabled == 1)))
            return {
                "count": len(rows),
                "modes": [{"name": r.name, "payload": r.payload,
                           "started_at": r.started_at, "expires_at": r.expires_at} for r in rows],
            }

        elif tool_name == "import_milestones_from_diary":
            return await self._import_milestones()

        elif tool_name == "restart_main_service":
            from src.config import get_settings
            settings = get_settings()
            reason = tool_input.get("reason", "")

            # Strategy 1: Railway GraphQL API (fails on Hobby plan)
            railway_error: str | None = None
            if self._railway and settings.matveika_service_id:
                try:
                    await self._railway.restart_service(
                        settings.matveika_service_id, environment_id=""
                    )
                    return {"success": True, "via": "railway_api", "reason": reason}
                except Exception as e:
                    railway_error = str(e)
                    log.warning("railway_restart_failed", error=railway_error)

            # Strategy 2: trigger redeploy via empty commit on main (works on Hobby)
            if self._github:
                try:
                    sha = await self._github.trigger_redeploy_via_commit(
                        branch="main", reason=reason or "devops restart"
                    )
                    return {
                        "success": True,
                        "via": "github_empty_commit",
                        "sha": sha,
                        "reason": reason,
                        "note": "Railway autodeploy picks this up in 1-2 min",
                        "railway_api_error": railway_error,
                    }
                except Exception as e:
                    return {
                        "error": "Both Railway API and GitHub fallback failed",
                        "railway_api_error": railway_error,
                        "github_error": str(e),
                    }

            return {
                "error": "No restart method available — Railway не настроен и GitHub-токен отсутствует",
                "railway_api_error": railway_error,
            }

        return await super()._call_tool(tool_name, tool_input)

    async def analyze_error(self, error_log: dict[str, Any]) -> str:
        """Analyze an error log entry and decide if PR is needed."""
        resp = await self._claude.complete(
            model=self._get_model(),
            system=self.get_system_prompt(),
            messages=[{
                "role": "user",
                "content": f"Вижу ошибку:\n{error_log}\n\nПроанализируй и скажи нужен ли патч.",
            }],
            max_tokens=1024,
        )
        return resp

    async def _system_status(self) -> dict:
        from datetime import timedelta
        from sqlalchemy import func, select
        from src.db.models import ActiveAlert, NewsChannel, NewsPost
        from src.utils.time import now_kyiv

        async with self._memory._engine.connect() as conn:
            channels = list(await conn.execute(select(NewsChannel)))
            alerts = list(await conn.execute(select(ActiveAlert)))
            last_post = (await conn.execute(
                select(NewsPost.date).order_by(NewsPost.date.desc()).limit(1)
            )).first()

        ch_by_cat: dict[str, int] = {}
        inactive = 0
        for c in channels:
            ch_by_cat[c.category] = ch_by_cat.get(c.category, 0) + 1
            if not c.active:
                inactive += 1

        last_post_iso = last_post[0] if last_post else None
        last_post_lag_min = None
        if last_post_iso:
            try:
                from datetime import datetime
                lag = now_kyiv() - datetime.fromisoformat(last_post_iso)
                last_post_lag_min = int(lag.total_seconds() / 60)
            except Exception:
                pass

        from src.config import get_settings
        settings = get_settings()
        return {
            "userbot": {
                "enabled": settings.enable_userbot,
                "hq_chat_id": settings.hq_chat_id,
                "phone": settings.tg_phone[:6] + "…" if settings.tg_phone else None,
            },
            "news_channels": {
                "total": len(channels),
                "by_category": ch_by_cat,
                "inactive": inactive,
            },
            "news_posts": {
                "last_saved_at": last_post_iso,
                "minutes_ago": last_post_lag_min,
                "stale": (last_post_lag_min or 0) > 120 if last_post_lag_min is not None else None,
            },
            "active_alerts": [
                {"region": a.region, "started": a.started_at, "last_update": a.last_update_at}
                for a in alerts
            ],
            "integrations": {
                "google_sheets": bool(settings.sheet_baby_id and settings.google_service_account_b64),
                "google_calendar": bool(settings.calendar_id and settings.google_service_account_b64),
                "github": bool(settings.github_token),
                "railway": bool(settings.railway_api_token and settings.railway_project_id),
            },
            "model": {
                "main": settings.model_main,
                "cheap": settings.model_cheap,
            },
        }

    async def _cost_report(self, days: int) -> dict:
        from datetime import date, timedelta
        from sqlalchemy import func, select
        from src.db.models import ApiUsage

        # Pricing per 1M tokens (USD) — public Anthropic rates (June 2026)
        prices = {
            "sonnet": {"in": 3.0, "out": 15.0, "cache_w": 3.75, "cache_r": 0.30},
            "haiku":  {"in": 0.80, "out": 4.0, "cache_w": 1.00, "cache_r": 0.08},
            "opus":   {"in": 15.0, "out": 75.0, "cache_w": 18.75, "cache_r": 1.50},
        }

        def family_of(model_name: str) -> str:
            n = (model_name or "").lower()
            if "opus" in n: return "opus"
            if "haiku" in n: return "haiku"
            return "sonnet"

        cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(ApiUsage).where(ApiUsage.date >= cutoff)
            ))

        per_day: dict[str, float] = {}
        per_model: dict[str, dict] = {}
        total_in = total_out = total_cw = total_cr = 0
        total_cost = 0.0
        for r in rows:
            fam = family_of(r.model)
            p = prices[fam]
            cost = (
                r.input_tokens * p["in"] / 1e6
                + r.output_tokens * p["out"] / 1e6
                + r.cache_creation_tokens * p["cache_w"] / 1e6
                + r.cache_read_tokens * p["cache_r"] / 1e6
            )
            per_day[r.date] = per_day.get(r.date, 0.0) + cost
            pm = per_model.setdefault(r.model, {"in": 0, "out": 0, "cw": 0, "cr": 0, "cost": 0.0})
            pm["in"] += r.input_tokens
            pm["out"] += r.output_tokens
            pm["cw"] += r.cache_creation_tokens
            pm["cr"] += r.cache_read_tokens
            pm["cost"] += cost
            total_in += r.input_tokens
            total_out += r.output_tokens
            total_cw += r.cache_creation_tokens
            total_cr += r.cache_read_tokens
            total_cost += cost

        return {
            "days": days,
            "total_cost_usd": round(total_cost, 4),
            "today_usd": round(per_day.get(date.today().isoformat(), 0.0), 4),
            "tokens": {
                "input": total_in,
                "output": total_out,
                "cache_write": total_cw,
                "cache_read": total_cr,
            },
            "per_day_usd": {d: round(v, 4) for d, v in sorted(per_day.items())},
            "per_model": {m: {**v, "cost": round(v["cost"], 4)} for m, v in per_model.items()},
        }

    async def _set_family_fact(self, key: str, value: str) -> dict:
        if not key:
            return {"success": False, "error": "key пуст"}
        from sqlalchemy import insert
        from src.db.models import FamilyOverride
        from src.utils.family import apply_overrides
        from src.utils.time import iso_now

        async with self._memory._engine.begin() as conn:
            await conn.execute(
                insert(FamilyOverride).prefix_with("OR REPLACE").values(
                    key=key,
                    value=value,
                    updated_at=iso_now(),
                    updated_by=getattr(self, "_current_sender", "") or "",
                )
            )
            from sqlalchemy import select
            rows = list(await conn.execute(select(FamilyOverride)))
        apply_overrides({r.key: r.value for r in rows})
        return {"success": True, "key": key, "value": value, "total_overrides": len(rows)}

    async def _import_milestones(self) -> dict:
        """Scan Дневник for 'first occurrence' events and write to Достижения."""
        if not self._memory:
            return {"error": "memory not available"}
        # Use Nanny's sheets — search via Архивариус helper
        from src.integrations.history_search import _search_sheet
        from datetime import datetime
        # We need a sheets client — DevOps doesn't have one directly, but we can
        # ask via the agents map at runtime through a peer-call. Simpler: piggyback
        # on the bot manager registry expects sheets on Nanny. Use raw API later.
        # Strategy: just return TODO until coordinated — but for now do best-effort
        # via filesystem if Sheets unavailable.
        return {
            "note": "Запустить нужно через прямой вызов SheetsClient.append_milestone. "
                    "Эту функцию вызовет Прораб через peer-chain с Няней: «Няня, импортируй "
                    "milestones из дневника». Няня выполнит, потому что у неё есть sheets_client.",
            "next_step": "Скажи: «Няня, импортируй milestones из дневника»",
        }

    async def _family_wiki(self, section: str) -> dict:
        """Compact portrait of the whole family + system state."""
        from datetime import date
        from sqlalchemy import select
        from src.db.models import Document, FamilyMode, Subscription
        from src.utils.family import (
            CHILD, EMERGENCY_CONTACTS, FATHER, HELPERS, LOCATION, MOTHER, PEDIATRICS,
            _current_location, _override_int,
        )
        from src.utils.baby import matvey_age_short

        loc = _current_location()
        weight_g = _override_int("matvey.weight_g", CHILD["weight_g"])
        height_cm = _override_int("matvey.height_cm", CHILD["height_cm"])

        portrait: dict = {}

        if section in ("all", "child"):
            portrait["child"] = {
                "name": CHILD["full_name"],
                "age": matvey_age_short(),
                "born": CHILD["birth_date"].strftime("%d.%m.%Y"),
                "weight_g": weight_g,
                "height_cm": height_cm,
                "feeding": CHILD["feeding"],
                "delivery": CHILD["delivery"],
                "introduced_foods": CHILD["introduced_foods"],
                "vaccines_done": CHILD["vaccines_done"],
                "vaccines_upcoming": [(n, d.isoformat()) for n, d in CHILD["vaccines_upcoming"]],
            }
        if section in ("all", "parents"):
            portrait["father"] = {
                "name": FATHER["full_name"],
                "role": FATHER["role"],
                "born": FATHER["birth_date"].strftime("%d.%m.%Y"),
                "weight_kg": FATHER["weight_kg"],
                "blood_type": FATHER["blood_type"],
                "anamnesis": FATHER["medical_history"],
                "schedule": FATHER["schedule"],
            }
            portrait["mother"] = {
                "name": MOTHER["full_name"],
                "role": MOTHER["role"],
                "born": MOTHER["birth_date"].strftime("%d.%m.%Y"),
                "weight_kg": MOTHER["weight_kg"],
                "blood_type": MOTHER["blood_type"],
                "lactating": MOTHER.get("lactating"),
                "schedule": MOTHER["schedule"],
            }
        if section in ("all", "helpers"):
            portrait["helpers"] = HELPERS
        if section == "all":
            portrait["location"] = loc
            portrait["pediatrics"] = PEDIATRICS

        # DB-backed sections
        async with self._memory._engine.connect() as conn:
            if section in ("all", "documents"):
                docs = list(await conn.execute(select(Document)))
                today = date.today()
                docs_view = []
                for d in docs:
                    days_left = None
                    if d.expires_at:
                        try:
                            days_left = (date.fromisoformat(d.expires_at) - today).days
                        except Exception:
                            pass
                    docs_view.append({"member": d.member, "kind": d.kind, "expires_at": d.expires_at, "days_left": days_left})
                docs_view.sort(key=lambda x: x["days_left"] if x["days_left"] is not None else 99999)
                portrait["documents"] = docs_view

            if section in ("all", "subscriptions"):
                subs = list(await conn.execute(select(Subscription).where(Subscription.active == 1)))
                portrait["subscriptions"] = {
                    "total_month": round(sum(s.amount for s in subs), 2),
                    "items": [{"name": s.name, "amount": s.amount, "currency": s.currency, "billing_day": s.billing_day} for s in subs],
                }

            if section in ("all", "modes"):
                modes = list(await conn.execute(select(FamilyMode).where(FamilyMode.enabled == 1)))
                portrait["active_modes"] = [{"name": m.name, "expires_at": m.expires_at} for m in modes]

        if section in ("all", "emergency"):
            portrait["emergency_contacts"] = EMERGENCY_CONTACTS[:5]

        return portrait

    async def _write_time_capsule(self, title: str, text: str) -> dict:
        """Append a row to «Заметки» tagged TIME_CAPSULE so Архивариус can resurface annually."""
        # Try to use the Nanny's sheets client by calling through nanny is overkill;
        # if our DevOps agent had sheets we'd write directly. For now: save to event_log
        # and let scheduler/wave3 pull it on anniversary.
        from sqlalchemy import insert
        from src.db.models import EventLog
        from src.utils.time import iso_now
        if not title or not text:
            return {"error": "title и text обязательны"}
        async with self._memory._engine.begin() as conn:
            await conn.execute(insert(EventLog).values(
                level="INFO",
                event="time_capsule",
                agent_id=self.agent_id,
                message=f"{title} :: {text}",
                created_at=iso_now(),
            ))
        return {"success": True, "title": title, "saved": "В капсулу времени. Архивариус напомнит через год."}

    async def _smart_list(self) -> dict:
        """List Tuya/Smart Life devices via integration if configured."""
        try:
            from src.integrations.tuya import TuyaClient
            from src.config import get_settings
            settings = get_settings()
            client = TuyaClient.from_settings(settings)
            if not client:
                return {
                    "error": "Tuya/Smart Life не настроен",
                    "setup_instructions": (
                        "1. Зайди на https://iot.tuya.com и создай developer account\n"
                        "2. Cloud → Project → Create — выбери Smart Home / Custom Development\n"
                        "3. Linked Devices → Link App Account — привяжи свой Smart Life аккаунт\n"
                        "4. Из проекта возьми Access ID и Access Secret\n"
                        "5. Добавь в Railway env:\n"
                        "   TUYA_ACCESS_ID=<id>\n"
                        "   TUYA_ACCESS_SECRET=<secret>\n"
                        "   TUYA_REGION=eu  (или us / cn / in)\n"
                        "   TUYA_APP_USER_UID=<твой UID из связанного Smart Life>"
                    ),
                }
            devices = await client.list_devices()
            return {"count": len(devices), "devices": devices}
        except Exception as e:
            return {"error": str(e)}

    async def _smart_control(self, device: str, action: str) -> dict:
        try:
            from src.integrations.tuya import TuyaClient
            from src.config import get_settings
            client = TuyaClient.from_settings(get_settings())
            if not client:
                return {"error": "Tuya не настроен — скажи «список устройств» для инструкции"}
            # For ACs prefer Tap-to-Run scenes — direct IR API is unreliable.
            dev_l = (device or "").lower()
            looks_like_ac = any(
                t in dev_l for t in ("кондер", "кондиц", "ac ", "ac_")
            ) or dev_l == "ac"
            if looks_like_ac and action in ("on", "off"):
                intent = "выкл" if action == "off" else "вкл"
                try:
                    match = await client.find_scene(f"{device} {intent}")
                    if match and not match.get("ambiguous"):
                        scene_res = await client.run_scene(match["id"])
                        if scene_res.get("success"):
                            return {
                                "device": device,
                                "action": action,
                                "via_scene": match["name"],
                                "success": True,
                            }
                except Exception:
                    pass
            return await client.control(device, action)
        except Exception as e:
            return {"error": str(e)}

    async def _smart_sensor(self, sensor: str) -> dict:
        try:
            from src.integrations.tuya import TuyaClient
            from src.config import get_settings
            client = TuyaClient.from_settings(get_settings())
            if not client:
                return {"error": "Tuya не настроен"}
            return await client.read_sensor(sensor)
        except Exception as e:
            return {"error": str(e)}

    # ─── Automation rules ────────────────────────────────────────────

    _KNOWN_RULE_TYPES = frozenset({
        "datetime", "datetime_range", "time", "sensor",
        "alert_active", "alert_ended", "power_outage", "baby_sleeping",
        "and", "or",
        "device", "message", "set_mode", "tool", "ac_command",
    })

    @staticmethod
    def _normalize_rule_dict(d: Any) -> Any:
        """Coerce frequent LLM JSON shapes to the canonical
        {"type": "<kind>", <fields>} form the automation engine expects.
        Recursively normalizes nested and/or children — sub-rules wrapped
        in LLM-shaped JSON used to silently fail before this."""
        if not isinstance(d, dict):
            return d
        result = DevOpsAgent._infer_rule_type(d)
        # If the inferred type is a composite (and/or), recursively
        # normalize each sub-rule. This was missing before — a hybrid
        # like {"and": {"rules": [{"sensor": {...}, "op": ">"}, ...]}}
        # would be unwrapped at the top but inner rules left as-is.
        if (isinstance(result, dict)
                and result.get("type") in ("and", "or")
                and isinstance(result.get("rules"), list)):
            result = {
                **result,
                "rules": [DevOpsAgent._normalize_rule_dict(r) for r in result["rules"]],
            }
        return result

    @staticmethod
    def _infer_rule_type(d: dict) -> Any:
        if "type" in d:
            return d
        # Shape A: wrapped — {<type>: {<rest>}}
        if len(d) == 1:
            key, val = next(iter(d.items()))
            if isinstance(val, dict):
                return {"type": key, **val}
        # Shape A2: hybrid — {<type>: {<some_fields>}, <other_fields>}
        for key, val in d.items():
            if key in DevOpsAgent._KNOWN_RULE_TYPES and isinstance(val, dict):
                siblings = {k: v for k, v in d.items() if k != key}
                return {"type": key, **val, **siblings}
        # Shape C: AC compound action — {"device": "кондер", "mode": "hot",
        # "temperature": 24} meaning "set the AC to hot 24°C".
        if isinstance(d.get("device"), str) and (
            "mode" in d or "temperature" in d or "fan_speed" in d or "speed" in d
        ) and "action" not in d:
            return {"type": "ac_command", **d}
        # Shape B: flat — characteristic-field inference, most-specific first.
        if "device" in d and "action" in d and isinstance(d.get("device"), str):
            return {"type": "device", **d}
        if "agent" in d and "text" in d:
            return {"type": "message", **d}
        if "mode" in d and "enabled" in d:
            return {"type": "set_mode", **d}
        if "agent" in d and "tool" in d:
            return {"type": "tool", **d}
        if "at" in d:
            return {"type": "datetime", **d}
        if "cron" in d or ("hour" in d and "minute" in d):
            return {"type": "time", **d}
        if "from" in d and "to" in d:
            return {"type": "datetime_range", **d}
        if "metric" in d and "op" in d and "value" in d:
            return {"type": "sensor", **d}
        if "region" in d:
            st = (d.get("state") or "").lower()
            if st == "ended":
                return {"type": "alert_ended", **d}
            return {"type": "alert_active", **d}
        if "state" in d and d.get("state") in ("active", "ended"):
            return {"type": "power_outage", **d}
        if "min_minutes" in d:
            return {"type": "baby_sleeping", **d}
        return d

    async def _automation_add(self, tool_input: dict) -> dict:
        import json as _json
        from sqlalchemy import insert
        from src.db.models import AutomationRule
        from src.utils.time import iso_now
        # Normalize wrapper-style JSON ({"power_outage": {...}} → {"type": "power_outage", ...})
        condition = self._normalize_rule_dict(tool_input.get("condition"))
        action = self._normalize_rule_dict(tool_input.get("action"))
        tool_input = {**tool_input, "condition": condition, "action": action}
        try:
            cond_json = _json.dumps(condition, ensure_ascii=False)
            act_json = _json.dumps(action, ensure_ascii=False)
        except Exception as e:
            return {"error": f"bad JSON: {e}"}
        async with self._memory._engine.begin() as conn:
            await conn.execute(insert(AutomationRule).prefix_with("OR REPLACE").values(
                name=tool_input["name"],
                description=tool_input.get("description"),
                condition=cond_json,
                action=act_json,
                enabled=1,
                cooldown_min=int(tool_input.get("cooldown_min", 60)),
                created_at=iso_now(),
                created_by=getattr(self, "_current_sender", "") or "",
            ))
        # Mirror into Прораб's notebook so user has one place to see all
        # promises (manual reminders + automations).
        mirror_status = "ok"
        mirror_error = None
        try:
            mirrored = await self._notebook_mirror_rule(
                name=tool_input["name"],
                description=tool_input.get("description") or "",
                condition=tool_input["condition"],
                action=tool_input["action"],
                enabled=True,
                cooldown_min=int(tool_input.get("cooldown_min", 60)),
            )
            if not mirrored:
                mirror_status = "skipped"
        except Exception as e:
            log.exception("notebook_mirror_rule_failed", name=tool_input["name"])
            mirror_status = "error"
            mirror_error = f"{type(e).__name__}: {str(e)[:200]}"
        return {
            "success": True,
            "name": tool_input["name"],
            "notebook_mirror": mirror_status,
            "notebook_mirror_error": mirror_error,
        }

    _TRIP_PAUSE_MARKER = "[paused-by-trip]"

    async def _pause_standing_rules(self) -> list[str]:
        """Disable all currently-enabled non-one-shot rules and mark them
        so we can restore the same set when the user comes home."""
        import json as _json
        from sqlalchemy import select, update as sql_update
        from src.db.models import AutomationRule
        paused: list[str] = []
        async with self._memory._engine.begin() as conn:
            rows = list(await conn.execute(
                select(AutomationRule).where(AutomationRule.enabled == 1)
            ))
            for r in rows:
                try:
                    cond = _json.loads(r.condition or "{}")
                except Exception:
                    continue
                # Skip one-shot datetime rules — those are explicit
                # planned events (homecoming prep etc) and should keep firing.
                if cond.get("type") == "datetime":
                    continue
                desc = r.description or ""
                if self._TRIP_PAUSE_MARKER not in desc:
                    desc = (desc + " " + self._TRIP_PAUSE_MARKER).strip()
                await conn.execute(
                    sql_update(AutomationRule).where(AutomationRule.id == r.id).values(
                        enabled=0, description=desc,
                    )
                )
                paused.append(r.name)
        # Re-mirror each to the notebook so user sees the ⏸ status.
        await self._remirror_rules(paused)
        return paused

    async def _resume_paused_rules(self) -> list[str]:
        """Re-enable rules previously paused by trip-mode."""
        import json as _json
        from sqlalchemy import select, update as sql_update
        from src.db.models import AutomationRule
        resumed: list[str] = []
        async with self._memory._engine.begin() as conn:
            rows = list(await conn.execute(select(AutomationRule)))
            for r in rows:
                desc = r.description or ""
                if self._TRIP_PAUSE_MARKER not in desc:
                    continue
                new_desc = desc.replace(self._TRIP_PAUSE_MARKER, "").strip()
                await conn.execute(
                    sql_update(AutomationRule).where(AutomationRule.id == r.id).values(
                        enabled=1, description=new_desc,
                    )
                )
                resumed.append(r.name)
        await self._remirror_rules(resumed)
        return resumed

    async def _remirror_rules(self, names: list[str]) -> None:
        if not names:
            return
        import json as _json
        from sqlalchemy import select
        from src.db.models import AutomationRule
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(AutomationRule).where(AutomationRule.name.in_(names))
            ))
        for r in rows:
            try:
                await self._notebook_mirror_rule(
                    name=r.name,
                    description=r.description or "",
                    condition=_json.loads(r.condition or "{}"),
                    action=_json.loads(r.action or "{}"),
                    enabled=bool(r.enabled),
                    cooldown_min=r.cooldown_min or 60,
                )
            except Exception:
                log.exception("remirror_failed", name=r.name)

    # TV intentionally omitted — IR transmitter not paired yet; the smart
    # socket would work but user prefers not to include it until ready.
    _AWAY_DEVICES = ("бойлер", "кондер")

    async def _enter_away_mode(self) -> dict:
        """Turn off non-essential devices, pause standing rules, mark trip
        mode active. Inverter / sensors / hub stay on (not in our off-list)."""
        from src.config import get_settings
        from src.integrations.tuya import TuyaClient
        from src.utils.time import iso_now, now_kyiv
        client = TuyaClient.from_settings(get_settings())
        results: list[dict] = []
        if client:
            for dev in self._AWAY_DEVICES:
                try:
                    r = await client.control(dev, "off")
                    results.append({"device": dev, "ok": bool(r.get("success")), "raw": r})
                except Exception as e:
                    results.append({"device": dev, "ok": False, "error": str(e)[:160]})
        # Pause standing automation rules
        paused: list[str] = []
        try:
            paused = await self._pause_standing_rules()
        except Exception:
            log.exception("away_mode_pause_failed")
        # Set family-mode trip = active — preserve started_at if a prior
        # row exists (rare; but if it does we don't want to lose the
        # original timestamp).
        try:
            from sqlalchemy import insert, select, update as sql_update
            from src.db.models import FamilyMode
            async with self._memory._engine.begin() as conn:
                existing = (await conn.execute(
                    select(FamilyMode).where(FamilyMode.name == "trip")
                )).first()
                if existing:
                    await conn.execute(
                        sql_update(FamilyMode).where(FamilyMode.name == "trip").values(
                            enabled=1, expires_at=None,
                        )
                    )
                else:
                    await conn.execute(insert(FamilyMode).values(
                        name="trip", enabled=1, payload=None,
                        started_at=iso_now(), expires_at=None,
                    ))
        except Exception:
            log.exception("away_mode_db_failed")
        # Mark in notebook
        try:
            peers = getattr(self, "_peer_agents", {})
            sheets = getattr(peers.get("nanny"), "_sheets", None)
            if sheets:
                from src.integrations.prorab_notebook import add_task
                ok_devs = ", ".join(r["device"] for r in results if r["ok"]) or "—"
                fail_devs = ", ".join(r["device"] for r in results if not r["ok"]) or "—"
                await add_task(
                    sheets,
                    task=f"✈️ Уехал — выключено: {ok_devs}",
                    note=f"trip start {now_kyiv().strftime('%Y-%m-%d %H:%M')}; failed: {fail_devs}; paused: {len(paused)}",
                )
        except Exception:
            log.exception("away_mode_notebook_failed")
        return {
            "mode": "trip",
            "enabled": True,
            "results": results,
            "paused_rules": paused,
            "display_instruction": (
                "Скажи юзеру коротко: «✈️ Уехал. Выключил <список ok>. "
                "Trip-режим включён. На паузу N правил (N=len(paused_rules)).» "
                "Если есть failed — добавь строку про что не получилось."
            ),
        }

    async def _exit_away_mode(self) -> dict:
        """Mark trip mode finished and resume all rules paused by trip."""
        from src.utils.time import iso_now
        try:
            from sqlalchemy import update as sql_update
            from src.db.models import FamilyMode
            async with self._memory._engine.begin() as conn:
                await conn.execute(
                    sql_update(FamilyMode).where(FamilyMode.name == "trip").values(
                        enabled=0, expires_at=iso_now(),
                    )
                )
        except Exception as e:
            return {"error": f"db update failed: {e}"}
        # Re-enable paused rules
        resumed: list[str] = []
        try:
            resumed = await self._resume_paused_rules()
        except Exception:
            log.exception("exit_away_resume_failed")
        # Notebook closer
        try:
            peers = getattr(self, "_peer_agents", {})
            sheets = getattr(peers.get("nanny"), "_sheets", None)
            if sheets:
                from src.integrations.prorab_notebook import add_task
                await add_task(
                    sheets,
                    task=f"🏠 Я дома — trip-режим выключен, восстановлено {len(resumed)} правил",
                )
        except Exception:
            log.exception("exit_away_notebook_failed")
        return {
            "mode": "trip", "enabled": False,
            "resumed_rules": resumed,
            "display_instruction": (
                "Скажи юзеру: «🏠 С возвращением! Trip-режим выключен. "
                "Восстановил N правил автоматизации (N=len(resumed_rules)).»"
            ),
        }

    async def _schedule_homecoming(
        self, *, arrival: str, boiler_hours_before: int,
        ac_hours_before: int, ac_mode: str, ac_temperature: int,
    ) -> dict:
        """Parse arrival time, schedule boiler & AC prep before user gets home."""
        import re as _re
        from datetime import datetime as _dt, timedelta
        from src.utils.time import KYIV_TZ, now_kyiv
        text = (arrival or "").strip().lower()
        now = now_kyiv()
        target_dt = None
        # ISO «YYYY-MM-DDTHH:MM»
        try:
            parsed = _dt.fromisoformat(arrival)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=KYIV_TZ)
            target_dt = parsed
        except Exception:
            pass
        # «в HH:MM», «к HH:MM», «HH:MM»
        if target_dt is None:
            m = _re.search(r"(\d{1,2}):(\d{2})", text)
            if m:
                h, mn = int(m.group(1)), int(m.group(2))
                target_dt = now.replace(hour=h, minute=mn, second=0, microsecond=0)
                if target_dt <= now:
                    target_dt += timedelta(days=1)
        # «через N часов / минут»
        if target_dt is None:
            m = _re.search(r"через\s+(\d+)\s*(час|hour|мин|min)", text)
            if m:
                n = int(m.group(1))
                unit = m.group(2)
                if "час" in unit or "hour" in unit:
                    target_dt = now + timedelta(hours=n)
                else:
                    target_dt = now + timedelta(minutes=n)
        if target_dt is None:
            return {"error": f"Не разобрал время прибытия «{arrival}». Поддержка: «в HH:MM», «через N часов»."}

        # Decide AC mode/temp by season unless user passed values
        month = now.month
        if not ac_mode:
            ac_mode = "hot" if month in (11, 12, 1, 2, 3) else "cold"
        if not ac_temperature:
            ac_temperature = 23 if ac_mode == "hot" else 22

        # Build prep schedule
        scheduled: list[dict] = []
        # Boiler ON
        boiler_at = target_dt - timedelta(hours=boiler_hours_before)
        if boiler_at <= now:
            # Already past — just fire it now (we'll skip)
            scheduled.append({"device": "бойлер", "skipped": "уже прошло время"})
        else:
            r = await self._schedule_device_action(
                device="бойлер", action="on",
                when=boiler_at.strftime("%Y-%m-%dT%H:%M"),
            )
            scheduled.append({"device": "бойлер", "at": boiler_at.strftime("%H:%M"), "result": r})

        # AC ON — for IR AC we use schedule_device_action for power, then chain set_mode/temp
        # via a second one-shot rule at the same moment (kept simple — single rule with action=on).
        ac_at = target_dt - timedelta(hours=ac_hours_before)
        if ac_at <= now:
            scheduled.append({"device": "кондер", "skipped": "уже прошло время"})
        else:
            r = await self._schedule_device_action(
                device="кондер", action="on",
                when=ac_at.strftime("%Y-%m-%dT%H:%M"),
            )
            scheduled.append({
                "device": "кондер", "at": ac_at.strftime("%H:%M"),
                "mode_hint": ac_mode, "temp_hint": ac_temperature, "result": r,
            })

        # User is on the way home — wake the standing rules NOW so by the
        # time he arrives, sensor-based automation (temp >26 → AC etc.)
        # is already active.
        resumed: list[str] = []
        try:
            resumed = await self._resume_paused_rules()
        except Exception:
            log.exception("homecoming_resume_failed")

        # Notebook overview entry
        try:
            peers = getattr(self, "_peer_agents", {})
            sheets = getattr(peers.get("nanny"), "_sheets", None)
            if sheets:
                from src.integrations.prorab_notebook import add_task
                await add_task(
                    sheets,
                    task=f"🏠 Возвращение в {target_dt.strftime('%H:%M')}: бойлер +{boiler_hours_before}ч, кондер +{ac_hours_before}ч ({ac_mode} {ac_temperature}°)",
                    due_at=target_dt.strftime("%Y-%m-%dT%H:%M"),
                    note=f"resumed {len(resumed)} paused rules",
                )
        except Exception:
            log.exception("homecoming_notebook_failed")

        return {
            "arrival": target_dt.strftime("%Y-%m-%dT%H:%M"),
            "ac_mode": ac_mode, "ac_temperature": ac_temperature,
            "scheduled": scheduled,
            "resumed_rules": resumed,
            "display_instruction": (
                "Скажи юзеру 3-4 строки: «🏠 Прибытие в HH:MM. "
                "🚿 Бойлер в HH:MM. ❄️ Кондер в HH:MM (<mode> <temp>°). "
                "Восстановил N правил автоматизации.» "
                "Если что-то skipped — упомяни."
            ),
        }

    async def _control_device_for_duration(
        self, *, device: str, action: str, duration_min: int,
    ) -> dict:
        """One-liner: do `action` now, schedule the reverse after N min.

        Covers the common wife-mode pattern «включи кондер на 10 минут».
        """
        if duration_min < 1:
            return {"error": "длительность должна быть ≥1 мин"}
        if action not in ("on", "off"):
            return {"error": f"action должно быть on/off, было {action!r}"}

        # 1) immediate control
        immediate = await self._smart_control(device, action)
        immediate_ok = isinstance(immediate, dict) and (
            immediate.get("success") or "error" not in immediate
        )

        # 2) schedule the reverse action
        reverse_action = "off" if action == "on" else "on"
        scheduled = await self._schedule_device_action(
            device=device,
            action=reverse_action,
            when=f"через {duration_min} минут",
        )
        return {
            "device": device,
            "immediate_action": action,
            "immediate_ok": immediate_ok,
            "immediate_raw": immediate,
            "reverse_in_min": duration_min,
            "reverse_scheduled": scheduled,
            "display_instruction": (
                "Скажи юзеру одной строкой: "
                "«✅ <device> <on/off> сейчас, через <N> мин — <reverse>.» "
                "Если immediate_ok=false — упомяни что текущая команда не "
                "сработала, но обратная всё равно запланирована."
            ),
        }

    async def _schedule_device_action(
        self, *, device: str, action: str, when: str,
    ) -> dict:
        """Translate a free-form `when` string into a datetime automation
        rule. Bullet-proof against LLM JSON errors — we build the JSON."""
        import re as _re
        from datetime import timedelta
        from src.utils.time import now_kyiv
        if not device:
            return {"error": "device обязателен"}
        if action not in ("on", "off", "toggle"):
            return {"error": f"action должен быть on/off/toggle, было {action!r}"}

        text = (when or "").strip().lower()
        now = now_kyiv()
        target_dt = None

        # «через N минут / N часов»
        m = _re.search(r"через\s+(\d+)\s*(минут|мин|час|часов|hour|hr|min)", text)
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            if "час" in unit or "hour" in unit or "hr" in unit:
                target_dt = now + timedelta(hours=n)
            else:
                target_dt = now + timedelta(minutes=n)

        # «в HH:MM»
        if target_dt is None:
            m = _re.search(r"в\s+(\d{1,2}):(\d{2})", text)
            if m:
                h, mn = int(m.group(1)), int(m.group(2))
                target_dt = now.replace(hour=h, minute=mn, second=0, microsecond=0)
                if target_dt <= now:
                    target_dt += timedelta(days=1)

        # plain «HH:MM»
        if target_dt is None:
            m = _re.match(r"(\d{1,2}):(\d{2})\s*$", text)
            if m:
                h, mn = int(m.group(1)), int(m.group(2))
                target_dt = now.replace(hour=h, minute=mn, second=0, microsecond=0)
                if target_dt <= now:
                    target_dt += timedelta(days=1)

        # ISO «YYYY-MM-DDTHH:MM[:SS]»
        if target_dt is None:
            try:
                from datetime import datetime as _dt
                from src.utils.time import KYIV_TZ
                parsed = _dt.fromisoformat(when)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=KYIV_TZ)
                target_dt = parsed
            except Exception:
                pass

        if target_dt is None:
            return {
                "error": (
                    f"Не разобрал время «{when}». "
                    "Поддержано: «через N минут», «через N часов», «в HH:MM», "
                    "«HH:MM», ISO «YYYY-MM-DDTHH:MM»."
                ),
            }

        at_iso = target_dt.strftime("%Y-%m-%dT%H:%M")
        slug = _re.sub(r"[^a-zA-Z0-9_]+", "_", device.lower())[:20] or "device"
        rule_name = f"{slug}_{action}_{target_dt.strftime('%Y%m%d_%H%M')}"

        rule_result = await self._automation_add({
            "name": rule_name,
            "description": f"{action.upper()} {device} в {at_iso}",
            "condition": {"type": "datetime", "at": at_iso, "late_fire": True},
            "action": {"type": "device", "device": device, "action": action},
            "cooldown_min": 5,
        })

        return {
            **rule_result,
            "scheduled_at": at_iso,
            "device": device,
            "action": action,
            "display_instruction": (
                "Скажи юзеру ОДНОЙ короткой строкой: «✅ <device> <on/off> в "
                "<scheduled_at>. Правило в таблице «⚙️ Автоматизации».» "
                "НИЧЕГО ДРУГОГО не пиши. Не упоминай Финна, Киевстар, "
                "баланс, предыдущие разговоры. Не повторяй про блокнот — "
                "одноразовые таймеры в ⚙️ Автоматизации, не в 📋 Блокнот."
            ),
        }

    async def _notebook_mirror_rule(
        self, *, name: str, description: str,
        condition: dict, action: dict, enabled: bool = True,
        cooldown_min: int = 60,
    ) -> bool:
        """Write/update this rule's row in the ⚙️ Автоматизации tab.
        Returns True (always upsert succeeds when sheets are available)."""
        peers = getattr(self, "_peer_agents", {})
        sheets = getattr(peers.get("nanny"), "_sheets", None)
        if not sheets:
            raise RuntimeError("sheets client not available for mirror")
        from src.integrations.prorab_notebook import (
            upsert_rule, describe_trigger, describe_action,
        )
        await upsert_rule(
            sheets,
            name=name,
            enabled=enabled,
            description=description or name,
            trigger=describe_trigger(condition),
            action=describe_action(action),
            cooldown_min=cooldown_min,
        )
        return True

    @staticmethod
    def _extract_due_from_condition(condition: dict) -> str:
        """Best-effort: pull a human-readable due time from rule condition."""
        kind = (condition or {}).get("type", "")
        if kind == "datetime":
            return (condition.get("at") or "")[:16]
        if kind == "time":
            cron = condition.get("cron") or ""
            wd = condition.get("weekday")
            if cron:
                return f"ежедн. {cron}" + (f" ({wd})" if wd else "")
            h = condition.get("hour")
            m = condition.get("minute", 0)
            if h is not None:
                return f"ежедн. {int(h):02d}:{int(m):02d}"
        if kind == "datetime_range":
            return f"{condition.get('from','')[:16]} … {condition.get('to','')[:16]}"
        if kind in ("sensor", "alert_active", "alert_ended", "power_outage", "baby_sleeping"):
            return f"условие: {kind}"
        return ""

    @staticmethod
    def _summarize_action(action: dict) -> str:
        kind = (action or {}).get("type", "")
        if kind == "device":
            return f"{action.get('device','')} → {action.get('action','')}"
        if kind == "message":
            return f"сообщение от {action.get('agent','')}"
        if kind == "set_mode":
            return f"режим {action.get('mode','')} = {action.get('enabled')}"
        if kind == "tool":
            return f"tool {action.get('tool','')} у {action.get('agent','')}"
        return kind or "?"

    async def _automation_list(self) -> dict:
        """Sync DB → notebook first, then return the notebook view (which
        is the user-facing source of truth). Falls back to DB read if the
        sheet isn't available."""
        import json as _json
        from sqlalchemy import select
        from src.db.models import AutomationRule
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(select(AutomationRule)))

        # Mirror every DB rule into the notebook so what user sees is what
        # actually runs.
        peers = getattr(self, "_peer_agents", {})
        sheets = getattr(peers.get("nanny"), "_sheets", None)
        sync_errors: list[str] = []
        if sheets:
            for r in rows:
                try:
                    await self._notebook_mirror_rule(
                        name=r.name,
                        description=r.description or "",
                        condition=_json.loads(r.condition or "{}"),
                        action=_json.loads(r.action or "{}"),
                        enabled=bool(r.enabled),
                        cooldown_min=r.cooldown_min or 60,
                    )
                except Exception as e:
                    sync_errors.append(f"{r.name}: {e}")
                    log.exception("notebook_sync_failed", name=r.name)

        # Read back from the notebook for the display payload — this way
        # Prorab shows the user the same view they'd open in the sheet.
        notebook_rules: list[dict] = []
        if sheets:
            try:
                from src.integrations.prorab_notebook import list_rules_from_sheet
                notebook_rules = await list_rules_from_sheet(sheets)
            except Exception as e:
                sync_errors.append(f"read: {e}")
                log.exception("notebook_read_failed")

        return {
            "count": len(notebook_rules) if notebook_rules else len(rows),
            "rules": notebook_rules or [
                {
                    "name": r.name, "description": r.description,
                    "enabled": bool(r.enabled), "cooldown_min": r.cooldown_min,
                    "fired_count": r.fired_count, "last_fired_at": r.last_fired_at,
                    "condition": r.condition, "action": r.action,
                }
                for r in rows
            ],
            "source": "notebook" if notebook_rules else "db_fallback",
            "sync_errors": sync_errors,
            "display_instruction": (
                "Покажи юзеру список ВКЛЮЧЁННЫХ правил и (если есть) "
                "ПРИОСТАНОВЛЕННЫХ отдельно. Формат: '◆ <description> — "
                "<trigger> → <action>'. Не вызывай list_automation_rules "
                "больше одного раза подряд."
            ),
        }

    async def _automation_toggle(self, name: str, enabled: bool) -> dict:
        import json as _json
        from sqlalchemy import select, update as sql_update
        from src.db.models import AutomationRule
        async with self._memory._engine.begin() as conn:
            res = await conn.execute(
                sql_update(AutomationRule).where(AutomationRule.name == name).values(enabled=1 if enabled else 0)
            )
            row = (await conn.execute(
                select(AutomationRule).where(AutomationRule.name == name)
            )).first()
        # Reflect new enabled flag in the notebook
        if row:
            try:
                await self._notebook_mirror_rule(
                    name=row.name,
                    description=row.description or "",
                    condition=_json.loads(row.condition or "{}"),
                    action=_json.loads(row.action or "{}"),
                    enabled=bool(enabled),
                    cooldown_min=row.cooldown_min or 60,
                )
            except Exception:
                log.exception("notebook_toggle_mirror_failed", name=name)
        return {"success": True, "updated": res.rowcount}

    async def _automation_delete(self, name: str) -> dict:
        from sqlalchemy import delete
        from src.db.models import AutomationRule
        async with self._memory._engine.begin() as conn:
            res = await conn.execute(delete(AutomationRule).where(AutomationRule.name == name))
        # Remove the row from the notebook too
        notebook_removed = False
        try:
            peers = getattr(self, "_peer_agents", {})
            sheets = getattr(peers.get("nanny"), "_sheets", None)
            if sheets:
                from src.integrations.prorab_notebook import delete_rule
                notebook_removed = await delete_rule(sheets, name)
        except Exception:
            log.exception("notebook_delete_mirror_failed", name=name)
        return {
            "success": True,
            "deleted_from_db": res.rowcount,
            "notebook_removed": notebook_removed,
        }

    async def _automation_delete_all(self) -> dict:
        from sqlalchemy import delete, select
        from src.db.models import AutomationRule
        async with self._memory._engine.begin() as conn:
            count_row = (await conn.execute(select(AutomationRule))).all()
            db_total = len(count_row)
            await conn.execute(delete(AutomationRule))
        notebook_cleared = 0
        try:
            peers = getattr(self, "_peer_agents", {})
            sheets = getattr(peers.get("nanny"), "_sheets", None)
            if sheets:
                from src.integrations.prorab_notebook import clear_all_rules
                notebook_cleared = await clear_all_rules(sheets)
        except Exception:
            log.exception("notebook_delete_all_failed")
        return {
            "success": True,
            "deleted_from_db": db_total,
            "notebook_cleared": notebook_cleared,
        }

    # ─── Family wiki ─────────────────────────────────────────────────

    async def _wiki_set(self, member: str, key: str, value: str) -> dict:
        from sqlalchemy import insert, select
        from sqlalchemy import update as sql_update
        from src.db.models import FamilyFact
        from src.utils.family import apply_wiki_facts
        from src.utils.time import iso_now
        if not (member and key and value):
            return {"error": "member, key и value обязательны"}
        async with self._memory._engine.begin() as conn:
            existing = (await conn.execute(
                select(FamilyFact).where(FamilyFact.member == member).where(FamilyFact.key == key)
            )).first()
            now = iso_now()
            if existing:
                await conn.execute(
                    sql_update(FamilyFact).where(FamilyFact.id == existing.id).values(
                        value=value, updated_at=now,
                    )
                )
            else:
                await conn.execute(insert(FamilyFact).values(
                    member=member, key=key, value=value, source="devops",
                    created_at=now, updated_at=now,
                ))
            rows = list(await conn.execute(select(FamilyFact)))
        apply_wiki_facts([
            {"member": r.member, "key": r.key, "value": r.value} for r in rows
        ])
        return {"saved": {"member": member, "key": key, "value": value}, "total": len(rows)}

    async def _wiki_list(self, member: str | None) -> dict:
        from sqlalchemy import select
        from src.db.models import FamilyFact
        async with self._memory._engine.connect() as conn:
            stmt = select(FamilyFact)
            if member:
                stmt = stmt.where(FamilyFact.member == member)
            rows = list(await conn.execute(stmt.order_by(FamilyFact.member, FamilyFact.key)))
        return {"facts": [
            {"member": r.member, "key": r.key, "value": r.value, "updated_at": r.updated_at}
            for r in rows
        ]}

    async def _wiki_delete(self, member: str, key: str) -> dict:
        from sqlalchemy import delete, select
        from src.db.models import FamilyFact
        from src.utils.family import apply_wiki_facts
        async with self._memory._engine.begin() as conn:
            res = await conn.execute(
                delete(FamilyFact).where(FamilyFact.member == member).where(FamilyFact.key == key)
            )
            rows = list(await conn.execute(select(FamilyFact)))
        apply_wiki_facts([
            {"member": r.member, "key": r.key, "value": r.value} for r in rows
        ])
        return {"deleted": res.rowcount}

    # ─── Search ──────────────────────────────────────────────────────

    async def _family_search(self, query: str, days_back: int) -> dict:
        from src.integrations.family_search import search_everywhere
        peers = getattr(self, "_peer_agents", {})
        sheets_client = getattr(peers.get("nanny"), "_sheets", None)
        result = await search_everywhere(query, self._memory, sheets_client, days_back)
        # Append calendar events too
        try:
            cal = getattr(peers.get("calendar"), "_calendar", None)
            if cal:
                events = await cal.find_events(query)
                result["groups"]["calendar"] = [
                    {"title": getattr(e, "title", ""),
                     "when": getattr(e, "start", None).isoformat() if getattr(e, "start", None) else "",
                     "id": getattr(e, "event_id", "")}
                    for e in events[:6]
                ]
        except Exception:
            log.exception("search_calendar_failed")
        # Compact display instruction
        result["display_instruction"] = (
            "Покажи юзеру сгруппированный ответ: для каждой группы где есть "
            "результаты — 2-5 строк. Если ничего не найдено в группе — пропусти её. "
            "Сами Drive ID не показывай, замени на 📷 если есть фото."
        )
        return result

    # ─── Nova Poshta parcels ─────────────────────────────────────────

    async def _parcel_track(self, ttn: str, title: str,
                            member: str = "family", phone_last4: str = "") -> dict:
        from sqlalchemy import insert, select
        from sqlalchemy import update as sql_update
        from src.config import get_settings
        from src.db.models import Parcel
        from src.integrations.nova_poshta import NovaPoshtaClient
        from src.utils.time import iso_now
        ttn = (ttn or "").strip().replace(" ", "")
        if not ttn:
            return {"error": "ТТН обязателен"}
        client = NovaPoshtaClient.from_settings(get_settings())
        if not client:
            return {"error": "NOVA_POSHTA_API_KEY не настроен в Railway"}
        status = await client.track(ttn, phone_last4=phone_last4)
        async with self._memory._engine.begin() as conn:
            existing = (await conn.execute(
                select(Parcel).where(Parcel.ttn == ttn)
            )).first()
            now = iso_now()
            values = {
                "status": status.get("status"),
                "status_code": str(status.get("status_code") or ""),
                "last_checked_at": now,
            }
            if status.get("actual_delivery"):
                values["delivered_at"] = status["actual_delivery"]
            if existing:
                if title:
                    values["title"] = title
                if member:
                    values["member"] = member
                await conn.execute(
                    sql_update(Parcel).where(Parcel.id == existing.id).values(**values)
                )
            else:
                await conn.execute(insert(Parcel).values(
                    carrier="nova_poshta", ttn=ttn,
                    title=title or None, member=member or "family",
                    created_at=now, **values,
                ))
        status["member"] = member
        status["display_instruction"] = (
            "Покажи юзеру: статус, маршрут (city_from → city_to), отделение, "
            "вес (weight_kg), стоимость доставки (shipping_uah), "
            "наложенный платёж (cod_uah, если есть) и общую сумму (total_uah). "
            "Если cod_uah = null или 0 — наложенного нет, не упоминай. "
            "Если total = shipping — пиши только стоимость доставки."
        )
        return status

    async def _parcel_list(self) -> dict:
        from sqlalchemy import select
        from src.db.models import Parcel
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(Parcel).where(Parcel.delivered_at.is_(None))
                .order_by(Parcel.id.desc())
            ))
        return {"parcels": [
            {"ttn": r.ttn, "title": r.title, "status": r.status,
             "checked_at": r.last_checked_at}
            for r in rows
        ]}

    # ─── Solar (LuxCloud) ────────────────────────────────────────────

    # Battery capacity in kWh — for Lux 6kW the user has ~109 kWh worth
    # configured (showing 96% = 104 kWh free). Hardcoded per his install;
    # could move to env later.
    _BATTERY_CAPACITY_KWH = 109.0

    async def _backfill_photo_dates(self) -> dict:
        """Re-parse caption + Drive filename + path/tags for every BabyPhoto
        and rewrite created_at + caption."""
        import os as _os
        import re
        from datetime import datetime
        from sqlalchemy import select, update as sql_update
        from src.config import get_settings
        from src.db.models import BabyPhoto
        from src.integrations.caption_parser import parse_caption_date
        from src.integrations.drive import DriveClient
        from src.utils.time import KYIV_TZ
        FNAME_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
        FNAME_CAP = re.compile(r"\d{4}-\d{2}-\d{2}_Matvey_[^_]+_(.+)$")
        DUP_DATE = re.compile(r"^\d{1,2}\.\d{1,2}\s*")

        drive = DriveClient.from_settings(get_settings())

        updated = 0
        captions_added = 0
        skipped = 0
        skipped_info: list[dict] = []
        async with self._memory._engine.begin() as conn:
            rows = list(await conn.execute(select(BabyPhoto)))
            for r in rows:
                parsed = None
                drive_name = None
                if drive and r.drive_file_id:
                    drive_name = await drive.get_filename(r.drive_file_id)
                # Date: drive filename → caption → local_path/tags
                if drive_name:
                    m = FNAME_DATE.search(drive_name)
                    if m:
                        try:
                            parsed = datetime(
                                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                12, 0, tzinfo=KYIV_TZ,
                            )
                        except Exception:
                            pass
                if not parsed:
                    parsed = parse_caption_date(r.caption or "")
                if not parsed:
                    for src in (r.local_path or "", r.tags or ""):
                        m = FNAME_DATE.search(src)
                        if m:
                            try:
                                parsed = datetime(
                                    int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                    12, 0, tzinfo=KYIV_TZ,
                                )
                                break
                            except Exception:
                                continue
                # Caption: pull from drive filename if DB row has no caption
                new_caption = None
                if not (r.caption and r.caption.strip()) and drive_name:
                    name_no_ext = _os.path.splitext(drive_name)[0]
                    cap_match = FNAME_CAP.match(name_no_ext)
                    if cap_match:
                        raw = cap_match.group(1).replace("_", " ").strip()
                        raw = DUP_DATE.sub("", raw)
                        if raw and raw.lower() != "foto":
                            new_caption = raw[:120]

                values: dict = {}
                if parsed:
                    new_iso = parsed.isoformat()
                    if r.created_at != new_iso:
                        values["created_at"] = new_iso
                if new_caption:
                    values["caption"] = new_caption
                if values:
                    await conn.execute(
                        sql_update(BabyPhoto).where(BabyPhoto.id == r.id).values(**values)
                    )
                    if "created_at" in values:
                        updated += 1
                    if "caption" in values:
                        captions_added += 1
                if not parsed:
                    skipped += 1
                    skipped_info.append({
                        "id": r.id, "caption": (r.caption or "")[:60],
                    })
        return {
            "updated_dates": updated,
            "added_captions": captions_added,
            "skipped_no_date": skipped,
            "skipped_info": skipped_info[:20],
            "total": len(rows),
            "display_instruction": (
                "Скажи юзеру: обновлено дат N, добавлено подписей M, "
                "пропущено P без даты. Для пропущенных перечисли id."
            ),
        }

    async def _list_baby_photos(self, missing_only: bool = False) -> dict:
        from sqlalchemy import select
        from src.db.models import BabyPhoto
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(BabyPhoto).order_by(BabyPhoto.id.asc())
            ))
        photos = []
        for r in rows:
            created = (r.created_at or "")[:10]
            # Suspicious: date == today (likely upload time, not real date)
            from src.utils.time import now_kyiv
            today = now_kyiv().strftime("%Y-%m-%d")
            suspicious = (created == today and not (r.caption or "").strip())
            if missing_only and not suspicious:
                continue
            photos.append({
                "id": r.id,
                "date": created,
                "caption": (r.caption or "")[:60] or "—",
                "in_drive": bool(r.drive_file_id),
                "suspicious": suspicious,
            })
        return {
            "count": len(photos),
            "photos": photos,
            "display_instruction": (
                "Покажи юзеру как таблицу: id · дата · подпись · ☁️ если в Drive. "
                "Если suspicious=true — пометь ⚠️ значит дата = сегодня и подписи нет. "
                "Предложи юзеру set_photo_date для проблемных."
            ),
        }

    async def _sync_photos_with_drive(self, months: int = 3) -> dict:
        """Scan '👶 Матвей · Фото / YYYY-MM' folders in Drive for files not
        present in BabyPhoto.drive_file_id; insert them with the date
        parsed from the filename."""
        import re
        from datetime import datetime
        from sqlalchemy import insert, select
        from src.config import get_settings
        from src.db.models import BabyPhoto
        from src.integrations.drive import DriveClient
        from src.utils.time import KYIV_TZ, iso_now, now_kyiv
        FNAME_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

        drive = DriveClient.from_settings(get_settings())
        if not drive:
            return {"error": "Drive не настроен"}

        # Build the list of YYYY-MM subfolders to scan
        now = now_kyiv()
        scan_months: list[str] = []
        y, m = now.year, now.month
        for _ in range(max(1, months)):
            scan_months.append(f"{y:04d}-{m:02d}")
            m -= 1
            if m == 0:
                m = 12
                y -= 1

        # Existing drive_file_ids in DB
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(
                select(BabyPhoto.drive_file_id).where(BabyPhoto.drive_file_id.is_not(None))
            ))
        existing = {r[0] for r in rows}

        added = 0
        scanned = 0
        added_list: list[dict] = []
        for ym in scan_months:
            try:
                folder_id = await drive.ensure_path(["👶 Матвей · Фото", ym])
            except Exception:
                continue
            files = await drive.list_folder_files(folder_id)
            for f in files:
                scanned += 1
                if f["id"] in existing:
                    continue
                if not f.get("mime", "").startswith("image/"):
                    continue
                # Parse date from filename like '2026-06-02_Matvey_...'
                m_match = FNAME_DATE.search(f["name"])
                if m_match:
                    try:
                        captured = datetime(
                            int(m_match.group(1)), int(m_match.group(2)), int(m_match.group(3)),
                            12, 0, tzinfo=KYIV_TZ,
                        )
                    except Exception:
                        captured = now
                else:
                    captured = now
                # Parse caption from filename. Format:
                # 'YYYY-MM-DD_Matvey_<age>_<caption>.ext' — keep whatever
                # comes after the third underscore as the user's note.
                import os as _os
                name_no_ext = _os.path.splitext(f["name"])[0]
                caption = None
                cap_match = re.match(
                    r"\d{4}-\d{2}-\d{2}_Matvey_[^_]+_(.+)$",
                    name_no_ext,
                )
                if cap_match:
                    raw = cap_match.group(1).replace("_", " ").strip()
                    raw = re.sub(r"^\d{1,2}\.\d{1,2}\s*", "", raw)
                    if raw and raw.lower() != "foto":
                        caption = raw[:120]
                async with self._memory._engine.begin() as conn:
                    await conn.execute(insert(BabyPhoto).values(
                        local_path=f["name"],
                        drive_file_id=f["id"],
                        caption=caption,
                        age_label="",
                        tags=f"baby,matvey,{ym}",
                        created_at=captured.isoformat(),
                    ))
                added += 1
                added_list.append({
                    "name": f["name"], "date": captured.strftime("%Y-%m-%d"),
                })
        return {
            "scanned_months": scan_months,
            "files_scanned": scanned,
            "added": added,
            "added_list": added_list[:20],
            "display_instruction": (
                "Скажи юзеру: просканировал N папок, нашёл K файлов, добавил "
                "M записей. Перечисли добавленные с датами. Если added > 0 — "
                "теперь хроника увидит все фото."
            ),
        }

    async def _cleanup_orphan_photos(self, dry_run: bool = False) -> dict:
        """Delete: (a) BabyPhoto rows without drive_file_id; (b) DUPLICATES
        — multiple rows pointing to the same drive_file_id (keep newest)."""
        from sqlalchemy import delete, select
        from src.db.models import BabyPhoto
        async with self._memory._engine.begin() as conn:
            # Orphans without drive_file_id
            orphan_rows = list(await conn.execute(
                select(BabyPhoto).where(BabyPhoto.drive_file_id.is_(None))
            ))
            orphan_ids = [r.id for r in orphan_rows]
            if not dry_run and orphan_ids:
                await conn.execute(
                    delete(BabyPhoto).where(BabyPhoto.drive_file_id.is_(None))
                )
            # Duplicates: same drive_file_id, keep the row with longest
            # caption (more info) — fallback to highest id (newest).
            all_rows = list(await conn.execute(
                select(BabyPhoto).where(BabyPhoto.drive_file_id.is_not(None))
                .order_by(BabyPhoto.id.asc())
            ))
            by_file: dict[str, list] = {}
            for r in all_rows:
                by_file.setdefault(r.drive_file_id, []).append(r)
            dup_ids_to_drop: list[int] = []
            for fid, rows in by_file.items():
                if len(rows) < 2:
                    continue
                # Pick keeper: longest caption, then highest id
                keeper = max(
                    rows,
                    key=lambda x: (len(x.caption or ""), x.id),
                )
                for r in rows:
                    if r.id != keeper.id:
                        dup_ids_to_drop.append(r.id)
            if not dry_run and dup_ids_to_drop:
                await conn.execute(
                    delete(BabyPhoto).where(BabyPhoto.id.in_(dup_ids_to_drop))
                )
        return {
            "found_orphans": len(orphan_ids),
            "found_duplicates": len(dup_ids_to_drop),
            "deleted": 0 if dry_run else len(orphan_ids) + len(dup_ids_to_drop),
            "orphan_ids": orphan_ids[:30],
            "duplicate_ids": dup_ids_to_drop[:30],
            "dry_run": dry_run,
            "display_instruction": (
                "Скажи юзеру: удалено N orphan-записей (без Drive) и M "
                "дубликатов (несколько строк на один drive_file_id). "
                "При дубликатах оставлена строка с самой длинной подписью."
            ),
        }

    async def _set_photo_date(self, photo_id: int, date_str: str) -> dict:
        """Manually fix the created_at of one photo (DD.MM or DD.MM.YYYY)."""
        from datetime import datetime
        from sqlalchemy import select, update as sql_update
        from src.db.models import BabyPhoto
        from src.utils.time import KYIV_TZ, now_kyiv

        date_s = (date_str or "").strip()
        parsed = None
        for fmt in ("%d.%m.%Y", "%d.%m", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(date_s, fmt)
                if fmt == "%d.%m":
                    parsed = parsed.replace(year=now_kyiv().year)
                parsed = parsed.replace(hour=12, minute=0, tzinfo=KYIV_TZ)
                break
            except ValueError:
                continue
        if not parsed:
            return {"error": f"Не разобрал дату '{date_str}'. Пиши 'DD.MM' или 'DD.MM.YYYY'."}
        async with self._memory._engine.begin() as conn:
            res = await conn.execute(
                sql_update(BabyPhoto).where(BabyPhoto.id == photo_id).values(
                    created_at=parsed.isoformat(),
                )
            )
        if not res.rowcount:
            return {"error": f"Фото с id={photo_id} не найдено"}
        return {"updated_id": photo_id, "new_date": parsed.strftime("%d.%m.%Y")}

    async def _battery_autonomy(self) -> dict:
        """Compute hours/minutes remaining at current discharge rate +
        suggest devices to turn off if draw is high."""
        from src.config import get_settings
        from src.integrations.luxcloud import LuxCloudClient
        from src.integrations.tuya import TuyaClient
        settings = get_settings()
        lux = LuxCloudClient.from_settings(settings)
        if not lux:
            return {"error": "LuxCloud не настроен"}
        try:
            rt = await lux.runtime()
        except Exception as e:
            return {"error": f"Инвертор недоступен: {e}"}

        battery_pct = float(rt.get("battery_pct") or 0)
        discharge_w = float(rt.get("battery_discharge_w") or 0)
        charge_w = float(rt.get("battery_charge_w") or 0)
        home_w = float(rt.get("home_consumption_w") or 0)
        on_grid = (charge_w > 30) or (float(rt.get("grid_import_w") or 0) > 30)

        # If we're on grid, no autonomy concern — but we can still
        # answer "if grid goes out NOW, what's the runtime?"
        effective_w = discharge_w if discharge_w > 0 else home_w
        remaining_kwh = (battery_pct / 100.0) * self._BATTERY_CAPACITY_KWH
        runtime_h = remaining_kwh / (effective_w / 1000.0) if effective_w > 0 else None
        if runtime_h is None or runtime_h > 999:
            runtime_str = "практически бесконечно (нет нагрузки)"
            runtime_minutes = None
        else:
            total_min = int(runtime_h * 60)
            h, m = divmod(total_min, 60)
            runtime_str = f"{h}ч {m:02d}мин"
            runtime_minutes = total_min

        # Device-by-device suggestions from Tuya
        recommendations: list[str] = []
        try:
            tuya = TuyaClient.from_settings(settings)
            if tuya:
                devices = await tuya.list_devices()
                # Score each ON device by power draw
                heavy = []
                for d in devices:
                    name = d.get("name") or ""
                    on = None
                    power = None
                    for s in (d.get("status") or []):
                        c = s.get("code", "")
                        v = s.get("value")
                        if (c == "switch" or c.startswith("switch_")) and not c.startswith("switch_led"):
                            if on is None:
                                on = bool(v)
                        if c in ("cur_power", "power"):
                            try:
                                power = float(v) / 10 if v and v > 50 else float(v or 0)
                            except (TypeError, ValueError):
                                pass
                    if on:
                        heavy.append((name, power or 0))
                heavy.sort(key=lambda x: -x[1])
                # If we have less than 3 hours OR draw > 300W — suggest
                if (runtime_minutes is not None and runtime_minutes < 180) or effective_w > 300:
                    for name, p in heavy[:3]:
                        if p > 0:
                            recommendations.append(f"выключить {name} (-{int(p)}Вт)")
                        else:
                            recommendations.append(f"выключить {name}")
        except Exception:
            log.exception("autonomy_tuya_failed")

        if effective_w > 200 and not recommendations:
            recommendations.append("зарядить телефоны и павербанки сейчас")
        if runtime_minutes is not None and runtime_minutes < 60:
            recommendations.insert(0, "🚨 батарея почти пуста — готовь свечи/фонарь")
        elif runtime_minutes is not None and runtime_minutes < 180:
            recommendations.insert(0, "⚠️ меньше 3 часов — собери минимум на ночь")

        return {
            "on_grid": on_grid,
            "battery_pct": int(battery_pct),
            "remaining_kwh": round(remaining_kwh, 1),
            "current_draw_w": int(effective_w),
            "runtime_pretty": runtime_str,
            "runtime_minutes": runtime_minutes,
            "recommendations": recommendations,
            "display_instruction": (
                "Покажи юзеру компактно: «🔋 X% · хватит на Yч Zмин при текущем "
                "потреблении» + перечисли рекомендации списком. Если on_grid=true — "
                "уточни «сейчас на сети, если свет уйдёт — хватит на Y»."
            ),
        }

    async def _solar_status(self) -> dict:
        try:
            from src.config import get_settings
            from src.integrations.luxcloud import LuxCloudClient
            client = LuxCloudClient.from_settings(get_settings())
            if not client:
                return {
                    "error": "LuxCloud не настроен",
                    "setup_instructions": (
                        "Добавь в Railway env:\n"
                        "  LUXCLOUD_EMAIL = твой email от LuxCloud\n"
                        "  LUXCLOUD_PASSWORD = пароль\n"
                        "  LUXCLOUD_REGION = eu  (или us / asia)\n"
                        "  LUX_INVERTER_SERIAL = серийник инвертора (в приложении LuxCloud → Devices)\n"
                        "После Restart Прораба."
                    ),
                }
            return await client.runtime()
        except Exception as e:
            return {"error": str(e)}

    async def _solar_today(self) -> dict:
        try:
            from src.config import get_settings
            from src.integrations.luxcloud import LuxCloudClient
            client = LuxCloudClient.from_settings(get_settings())
            if not client:
                return {"error": "LuxCloud не настроен"}
            return await client.today_energy()
        except Exception as e:
            return {"error": str(e)}

    # ─── Trip planner ────────────────────────────────────────────────

    async def _plan_trip(self, tool_input: dict) -> dict:
        """Create automation rules for a trip: turn off on leave, turn on before return."""
        from datetime import datetime, timedelta
        import json as _json
        from sqlalchemy import insert
        from src.db.models import AutomationRule
        from src.utils.time import iso_now

        try:
            leave = datetime.fromisoformat(tool_input["leave_at"])
            ret = datetime.fromisoformat(tool_input["return_at"])
        except Exception as e:
            return {"error": f"bad datetime: {e}"}

        devices_off = tool_input.get("devices_off") or ["ТВ", "бойлер"]
        devices_on = tool_input.get("devices_on_before_return") or ["бойлер"]
        dest = tool_input.get("destination", "")

        # Turn on 2 hours before return
        warmup = ret - timedelta(hours=2)
        trip_id = leave.strftime("%Y%m%d_%H%M")

        rules_created: list[dict] = []

        async with self._memory._engine.begin() as conn:
            # 1) On leave: enable trip mode + turn off devices
            for dev in devices_off:
                name = f"trip_{trip_id}_off_{dev}"
                await conn.execute(insert(AutomationRule).prefix_with("OR REPLACE").values(
                    name=name,
                    description=f"Поездка: выключить {dev} при отъезде ({leave.strftime('%d.%m %H:%M')})"
                                + (f" → {dest}" if dest else ""),
                    condition=_json.dumps({"type": "datetime", "at": leave.isoformat()}, ensure_ascii=False),
                    action=_json.dumps({"type": "device", "device": dev, "action": "off"}, ensure_ascii=False),
                    enabled=1, cooldown_min=1, created_at=iso_now(),
                    created_by=getattr(self, "_current_sender", "") or "trip_planner",
                ))
                rules_created.append({"name": name, "when": leave.isoformat(), "action": f"off {dev}"})

            # 2) Enable trip mode
            trip_mode_name = f"trip_{trip_id}_mode_on"
            await conn.execute(insert(AutomationRule).prefix_with("OR REPLACE").values(
                name=trip_mode_name,
                description=f"Поездка: включить trip mode до {ret.strftime('%d.%m %H:%M')}",
                condition=_json.dumps({"type": "datetime", "at": leave.isoformat()}, ensure_ascii=False),
                action=_json.dumps({
                    "type": "set_mode", "mode": "trip", "enabled": True, "until": ret.isoformat(),
                }, ensure_ascii=False),
                enabled=1, cooldown_min=1, created_at=iso_now(),
            ))
            rules_created.append({"name": trip_mode_name, "when": leave.isoformat(), "action": "trip mode ON"})

            # 3) Warmup before return: turn on devices
            for dev in devices_on:
                name = f"trip_{trip_id}_warmup_{dev}"
                await conn.execute(insert(AutomationRule).prefix_with("OR REPLACE").values(
                    name=name,
                    description=f"Поездка: включить {dev} за 2ч до приезда ({warmup.strftime('%d.%m %H:%M')})",
                    condition=_json.dumps({"type": "datetime", "at": warmup.isoformat()}, ensure_ascii=False),
                    action=_json.dumps({"type": "device", "device": dev, "action": "on"}, ensure_ascii=False),
                    enabled=1, cooldown_min=1, created_at=iso_now(),
                ))
                rules_created.append({"name": name, "when": warmup.isoformat(), "action": f"on {dev}"})

            # 4) On return: disable trip mode
            return_mode_name = f"trip_{trip_id}_mode_off"
            await conn.execute(insert(AutomationRule).prefix_with("OR REPLACE").values(
                name=return_mode_name,
                description="Поездка: выключить trip mode при приезде",
                condition=_json.dumps({"type": "datetime", "at": ret.isoformat()}, ensure_ascii=False),
                action=_json.dumps({
                    "type": "set_mode", "mode": "trip", "enabled": False,
                }, ensure_ascii=False),
                enabled=1, cooldown_min=1, created_at=iso_now(),
            ))
            rules_created.append({"name": return_mode_name, "when": ret.isoformat(), "action": "trip mode OFF"})

        return {
            "success": True,
            "trip_id": trip_id,
            "destination": dest,
            "leave_at": leave.isoformat(),
            "return_at": ret.isoformat(),
            "warmup_at": warmup.isoformat(),
            "rules_created": rules_created,
            "note": "Все правила одноразовые: сработают в указанные моменты. После приезда можно удалить через delete_automation_rule.",
        }

    # ─── SmartThings (vacuum) ────────────────────────────────────────

    async def _vacuum_status(self, name: str) -> dict:
        from src.config import get_settings
        from src.integrations.smartthings import SmartThingsClient
        client = SmartThingsClient.from_settings(get_settings())
        if not client:
            return {
                "error": "SmartThings не настроен",
                "setup_instructions": (
                    "1. Открой https://account.smartthings.com/tokens\n"
                    "2. Generate new token. Scopes: r:devices:* и x:devices:*\n"
                    "3. Скопируй токен (показывается один раз)\n"
                    "4. В Railway env: SMARTTHINGS_TOKEN = <твой токен>\n"
                    "5. Если пылесоса нет в SmartThings — в приложении SmartThings на телефоне:\n"
                    "   + Add device → Samsung → Vacuum → POWERbot → следуй мастеру"
                ),
            }
        try:
            devices = await client.list_devices()
            vacuum = client.find_vacuum(devices, needle=name)
            if not vacuum:
                return {
                    "error": "Пылесос не найден в SmartThings",
                    "available_devices": [{"name": d["name"], "type": d["type"]} for d in devices],
                }
            return await client.vacuum_summary(vacuum)
        except Exception as e:
            return {"error": str(e)}

    async def _vacuum_start(self, name: str, mode: str) -> dict:
        from src.config import get_settings
        from src.integrations.smartthings import SmartThingsClient
        client = SmartThingsClient.from_settings(get_settings())
        if not client:
            return {"error": "SmartThings не настроен"}
        try:
            devices = await client.list_devices()
            vacuum = client.find_vacuum(devices, needle=name)
            if not vacuum:
                return {"error": "Пылесос не найден"}
            await client.vacuum_start(vacuum["id"], mode)
            return {"success": True, "started": vacuum["name"], "mode": mode}
        except Exception as e:
            return {"error": str(e)}

    async def _vacuum_stop(self, name: str) -> dict:
        from src.config import get_settings
        from src.integrations.smartthings import SmartThingsClient
        client = SmartThingsClient.from_settings(get_settings())
        if not client:
            return {"error": "SmartThings не настроен"}
        try:
            devices = await client.list_devices()
            vacuum = client.find_vacuum(devices, needle=name)
            if not vacuum:
                return {"error": "Пылесос не найден"}
            await client.vacuum_stop(vacuum["id"])
            return {"success": True, "stopped": vacuum["name"], "action": "homing"}
        except Exception as e:
            return {"error": str(e)}

    async def _temperature_full(self) -> dict:
        """Aggregate indoor sensors + outdoor weather in a single response."""
        result: dict = {}
        formatted_lines: list[str] = ["🏠 <b>Дома:</b>"]
        # Indoor sensors via Tuya
        try:
            from src.config import get_settings
            from src.integrations.tuya import TuyaClient
            client = TuyaClient.from_settings(get_settings())
            if client:
                devices = await client.list_devices()
                sensors = []
                for d in devices:
                    cat = (d.get("category") or "").lower()
                    name = (d.get("name") or "").lower()
                    if "sensor" in cat or "temp" in name or "датчик" in name or "wsdcgq" in (d.get("product_name") or "").lower():
                        reading = await client.read_sensor(d.get("name"))
                        sensors.append(reading)
                        if reading.get("formatted"):
                            formatted_lines.append(f"  {reading['formatted']}")
                result["indoor"] = sensors
        except Exception as e:
            result["indoor_error"] = str(e)

        # Outdoor weather (always has fallback now)
        try:
            from src.integrations.weather import WeatherClient
            from src.config import get_settings
            wc = WeatherClient.from_settings(get_settings())
            if wc:
                w = await wc.current()
                result["outdoor"] = w
                formatted_lines.append(
                    f"\n🌍 <b>На улице:</b> 🌡 {w.get('temp_c')}°C "
                    f"(ощущается {w.get('feels_like_c')}°C), "
                    f"💧 {w.get('humidity_pct')}%, "
                    f"☁️ {w.get('description', '')}"
                )
        except Exception as e:
            result["outdoor_error"] = str(e)

        result["formatted"] = "\n".join(formatted_lines)
        result["display_instruction"] = "Покажи юзеру содержимое поля 'formatted' без изменений."
        return result

    async def _power_history_from_inverter(self, hours: int) -> dict:
        from datetime import datetime, timedelta
        from sqlalchemy import select
        from src.config import get_settings
        from src.db.models import PowerOutage
        from src.integrations.luxcloud import LuxCloudClient
        from src.utils.time import now_kyiv

        # 1) Try LuxCloud event log
        lux_events = []
        lux_error = None
        client = LuxCloudClient.from_settings(get_settings())
        if client:
            try:
                events = await client.recent_events(hours=hours)
                for ev in events:
                    blob = " ".join(str(v).lower() for v in (
                        ev.get("name") or "", ev.get("type") or "",
                        ev.get("code") or "",
                    ))
                    if "ac" in blob or "grid" in blob or "мережа" in blob or "сеть" in blob:
                        lux_events.append(ev)
            except Exception as e:
                lux_error = str(e)

        # 2) Always pull from local DB as well
        cutoff = (now_kyiv() - timedelta(hours=hours)).isoformat()
        async with self._memory._engine.connect() as conn:
            db_rows = list(await conn.execute(
                select(PowerOutage).where(PowerOutage.started_at >= cutoff)
                .order_by(PowerOutage.started_at.desc())
            ))

        # 3) Merge: prefer LuxCloud (precise), supplement with DB
        merged = []
        for ev in lux_events:
            merged.append({
                "source": "LuxCloud",
                "started": ev.get("during_time", "").split("~")[0].strip() if ev.get("during_time") else ev.get("time"),
                "ended": ev.get("during_time", "").split("~")[-1].strip() if "~" in (ev.get("during_time") or "") else None,
                "name": ev.get("name"),
                "status": ev.get("status"),
            })
        for r in db_rows:
            merged.append({
                "source": "Локальный детектор",
                "started": r.started_at,
                "ended": r.ended_at,
                "duration_min": r.duration_min,
                "notes": r.notes,
            })

        if not merged:
            msg = f"За последние {hours} ч отключений света не зафиксировано."
            if lux_error:
                msg += f"\n\n⚠️ LuxCloud event log недоступен: {lux_error}"
            return {
                "hours": hours,
                "outages_count": 0,
                "lux_error": lux_error,
                "formatted": msg,
                "display_instruction": "Покажи поле 'formatted'.",
            }

        lines = [f"⚡ <b>История света за {hours} ч</b>"]
        for e in merged[:15]:
            started = e.get("started") or "?"
            ended = e.get("ended") or "ещё длится"
            dur = e.get("duration_min")
            dur_str = f" ({dur} мин)" if dur else ""
            src = e.get("source", "")
            status_emoji = "✅" if e.get("status", "").lower() == "recovered" or ended != "ещё длится" else "🟠"
            lines.append(f"{status_emoji} {started} → {ended}{dur_str}  · {src}")

        return {
            "hours": hours,
            "outages_count": len(merged),
            "from_lux": len(lux_events),
            "from_db": len(db_rows),
            "lux_error": lux_error,
            "formatted": "\n".join(lines),
            "display_instruction": "Покажи поле 'formatted' без переформулирования.",
        }

    async def _record_past_outage(self, tool_input: dict) -> dict:
        from datetime import datetime
        from sqlalchemy import insert
        from src.db.models import PowerOutage
        try:
            started = datetime.fromisoformat(tool_input["started_iso"])
            ended = datetime.fromisoformat(tool_input["ended_iso"])
        except Exception as e:
            return {"error": f"Неверный формат даты: {e}"}
        duration_min = int((ended - started).total_seconds() / 60)
        source = tool_input.get("source", "вручную")
        async with self._memory._engine.begin() as conn:
            await conn.execute(insert(PowerOutage).values(
                started_at=started.isoformat(),
                ended_at=ended.isoformat(),
                duration_min=duration_min,
                notes=f"Источник: {source}",
            ))
        return {
            "success": True,
            "started": started.isoformat(),
            "ended": ended.isoformat(),
            "duration_min": duration_min,
            "formatted": f"✅ Записал отключение {started.strftime('%d.%m %H:%M')} → {ended.strftime('%H:%M')} ({duration_min} мин)",
            "display_instruction": "Покажи поле 'formatted'.",
        }

    async def _clean_outage_records(self, tool_input: dict) -> dict:
        from sqlalchemy import delete
        from src.db.models import PowerOutage
        conditions = []
        if tool_input.get("all"):
            async with self._memory._engine.begin() as conn:
                res = await conn.execute(delete(PowerOutage))
            return {"deleted": res.rowcount, "all": True}
        if tool_input.get("before_iso"):
            conditions.append(PowerOutage.started_at < tool_input["before_iso"])
        if tool_input.get("duration_max_min"):
            conditions.append(PowerOutage.duration_min < int(tool_input["duration_max_min"]))
        if not conditions:
            return {"error": "Укажи all=true, before_iso, или duration_max_min"}
        async with self._memory._engine.begin() as conn:
            res = await conn.execute(delete(PowerOutage).where(*conditions))
        return {"deleted": res.rowcount, "criteria": tool_input}
