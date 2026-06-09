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
                "description": "Показать все правила автоматизации с их статусом.",
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
                "description": "Удалить правило автоматизации.",
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
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
                "name": "nova_incoming_probe",
                "description": (
                    "Эксперимент: проверить, может ли мобильный ключ Nova Poshta "
                    "получить список ВХОДЯЩИХ посылок. Триггеры: «проверь входящие "
                    "посылки NP», «попробуй мобильный ключ NP»."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "use_mobile_key": {
                            "type": "boolean",
                            "description": "Использовать nova_poshta_mobile_key вместо business (по умолчанию true)",
                        },
                    },
                },
            },
            {
                "name": "parcel_track",
                "description": (
                    "Отследить посылку Nova Poshta по ТТН. Возвращает статус, "
                    "город получателя, отделение, дату доставки. Триггеры: "
                    "«отследи ТТН», «посылка», «когда придёт», «новая почта». "
                    "Можно указать кто получатель — «marina» / «eugene» — "
                    "и последние 4 цифры телефона для полной информации."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ttn": {"type": "string", "description": "Номер накладной (14 цифр)"},
                        "title": {"type": "string", "description": "Короткое имя посылки, опц."},
                        "member": {
                            "type": "string",
                            "description": "Получатель: marina / eugene / family. По умолчанию family.",
                        },
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
            safe_path = os.path.normpath(os.path.join("/home/user/many", path))
            if not safe_path.startswith("/home/user/many"):
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
        elif tool_name == "nova_incoming_probe":
            from src.config import get_settings
            from src.integrations.nova_poshta import NovaPoshtaClient
            settings = get_settings()
            use_mobile = tool_input.get("use_mobile_key", True)
            key = (settings.nova_poshta_mobile_key if use_mobile
                   else settings.nova_poshta_api_key)
            if not key:
                return {"error": (
                    "Ключ не задан в env. Для мобильного — "
                    "NOVA_POSHTA_MOBILE_KEY, для бизнес — NOVA_POSHTA_API_KEY"
                )}
            client = NovaPoshtaClient(key)
            results = await client.try_list_incoming(days_back=30)
            return {
                "key_type": "mobile" if use_mobile else "business",
                "found": len(results),
                "items": results[:10],
                "display_instruction": (
                    "Если found > 0 — мобильный ключ работает! Покажи юзеру "
                    "список ТТН + raw_method чтобы он понял какой эндпоинт сработал. "
                    "Если found == 0 — мобильный ключ тоже не даёт входящих, "
                    "нужен план Б (iOS Shortcut или Gmail)."
                ),
            }

        elif tool_name == "parcel_track":
            return await self._parcel_track(
                tool_input.get("ttn", ""), tool_input.get("title", ""),
                tool_input.get("member", "family"),
                tool_input.get("phone_last4", ""),
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
            stats["gemini_configured"] = bool(getattr(settings, "gemini_api_key", ""))
            stats["display_instruction"] = (
                "Покажи юзеру кратко: какой провайдер сейчас работает "
                "(current_provider), сколько успешных вызовов у каждого, "
                "сколько падений, настроен ли Gemini как fallback."
            )
            return stats

        elif tool_name == "gemini_ping":
            from src.config import get_settings
            from src.integrations.gemini_client import GeminiClient
            client = GeminiClient.from_settings(get_settings())
            if not client:
                return {"status": "not_configured",
                        "message": "GEMINI_API_KEY не задан в Railway env"}
            try:
                reply = await client.complete(
                    system="Ответь одним словом: 'работаю'.",
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=10,
                )
                return {"status": "ok", "model": client.model, "reply": reply[:80]}
            except Exception as e:
                return {"status": "error", "error": str(e)[:200]}

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

        elif tool_name == "solar_status":
            return await self._solar_status()
        elif tool_name == "solar_today":
            return await self._solar_today()
        elif tool_name == "plan_trip":
            return await self._plan_trip(tool_input)

        elif tool_name == "control_smart_device":
            return await self._smart_control(tool_input.get("device", ""), tool_input.get("action", "status"))

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
            if action == "start":
                async with self._memory._engine.begin() as conn:
                    result = await conn.execute(insert(PowerOutage).values(
                        started_at=iso_now(), notes=tool_input.get("notes"),
                    ))
                return {"success": True, "status": "started", "id": result.inserted_primary_key[0] if result.inserted_primary_key else None}
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
                return {"success": True, "duration_min": duration_min}

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
            from src.db.models import FamilyMode
            from src.utils.time import iso_now
            payload = tool_input.get("payload")
            payload_str = _json.dumps({"info": payload}) if payload else None
            async with self._memory._engine.begin() as conn:
                await conn.execute(insert(FamilyMode).prefix_with("OR REPLACE").values(
                    name=tool_input["mode"],
                    enabled=1 if tool_input.get("enabled") else 0,
                    payload=payload_str,
                    started_at=iso_now(),
                    expires_at=tool_input.get("until"),
                ))
            return {"success": True, "mode": tool_input["mode"], "enabled": tool_input.get("enabled")}

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

    async def _automation_add(self, tool_input: dict) -> dict:
        import json as _json
        from sqlalchemy import insert
        from src.db.models import AutomationRule
        from src.utils.time import iso_now
        try:
            cond_json = _json.dumps(tool_input["condition"], ensure_ascii=False)
            act_json = _json.dumps(tool_input["action"], ensure_ascii=False)
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
        return {"success": True, "name": tool_input["name"]}

    async def _automation_list(self) -> dict:
        from sqlalchemy import select
        from src.db.models import AutomationRule
        async with self._memory._engine.connect() as conn:
            rows = list(await conn.execute(select(AutomationRule)))
        return {
            "count": len(rows),
            "rules": [
                {
                    "name": r.name, "description": r.description,
                    "enabled": bool(r.enabled), "cooldown_min": r.cooldown_min,
                    "fired_count": r.fired_count, "last_fired_at": r.last_fired_at,
                    "condition": r.condition, "action": r.action,
                }
                for r in rows
            ],
        }

    async def _automation_toggle(self, name: str, enabled: bool) -> dict:
        from sqlalchemy import update as sql_update
        from src.db.models import AutomationRule
        async with self._memory._engine.begin() as conn:
            res = await conn.execute(
                sql_update(AutomationRule).where(AutomationRule.name == name).values(enabled=1 if enabled else 0)
            )
        return {"success": True, "updated": res.rowcount}

    async def _automation_delete(self, name: str) -> dict:
        from sqlalchemy import delete
        from src.db.models import AutomationRule
        async with self._memory._engine.begin() as conn:
            res = await conn.execute(delete(AutomationRule).where(AutomationRule.name == name))
        return {"success": True, "deleted": res.rowcount}

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
