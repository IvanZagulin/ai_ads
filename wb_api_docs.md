Списки кампаний
/adv/v1/promotion/count


get
https://advert-api.wildberries.ru/adv/v1/promotion/count
Описание метода
Метод возвращает списки всех рекламных кампаний продавца с их ID. Кампании сгруппированы по типу и статусу, у каждой указана дата последнего изменения.

Лимит запросов на один аккаунт продавца:
Период	Лимит	Интервал	Всплеск
1 сек	5 запросов	200 мс	5 запросов

Примеры ответа
200
401
429
Content type
application/json

Копировать
Свернуть все
{
"adverts": [
{
"type": 9,
"status": 8,
"count": 3,
"advert_list": [
{
"advertId": 6485174,
"changeTime": "2023-05-10T12:12:52.676254+03:00"
},
{
"advertId": 6500443,
"changeTime": "2023-05-10T17:08:46.370656+03:00"
},
{
"advertId": 7936341,
"changeTime": "2023-07-12T15:51:08.367478+03:00"
}
]
}
],
"all": 3
}




Информация о кампаниях
/api/advert/v2/adverts


get
https://advert-api.wildberries.ru/api/advert/v2/adverts
Описание метода
Метод возвращает информацию о рекламных кампаниях с единой или ручной ставкой по их статусам, типам оплаты и ID.

Лимит запросов на один аккаунт продавца:
Период	Лимит	Интервал	Всплеск
1 сек	5 запросов	200 мс	5 запросов
Authorizations:
HeaderApiKey
query Parameters
ids	
string
Example: ids=12345,23456,34567,45678,56789
ID кампаний, максимум 50

statuses	
string
Example: statuses=-1,4,8
Статусы кампаний:

-1 — удалена, процесс удаления будет завершён в течение 10 минут
4 — готова к запуску
7 — завершена
8 — отменена
9 — активна
11 — на паузе
payment_type	
string
Enum: "cpm" "cpc"
Тип оплаты:

cpm — за показы
cpc — за клик
Примеры ответа
200
400
401
429
Content type
application/json

Копировать
Свернуть все
{
"adverts": [
{
"bid_type": "manual",
"id": 567456457,
"nm_settings": [
{
"bids_kopecks": {
"recommendations": 0,
"search": 0
},
"nm_id": 123456789,
"subject": {
"id": 52,
"name": "кошельки"
}
},
{
"bids_kopecks": {
"recommendations": 11200,
"search": 11200
},
"nm_id": 987654321,
"subject": {
"id": 54,
"name": "ювелирные кольца"
}
}
],
"settings": {
"name": "Кампания от 01.02.2024",
"payment_type": "cpm",
"placements": {
"recommendations": false,
"search": true
}
},
"status": 7,
"timestamps": {
"created": "2024-02-01T09:57:38.500606+03:00",
"deleted": "2024-02-05T14:29:32.633968+03:00",
"started": "2024-02-05T12:38:10.212086+03:00",
"updated": "2024-02-05T14:29:32.633968+03:00"
}
},
{
"bid_type": "manual",
"id": 28150154,
"nm_settings": [
{
"bids_kopecks": {
"recommendations": 0,
"search": 1100
},
"nm_id": 5764746785,
"subject": {
"id": 69,
"name": "платья"
}
}
],
"settings": {
"name": "Кампания от 28.08.2025 ",
"payment_type": "cpc",
"placements": {
"recommendations": false,
"search": true
}
},
"status": 11,
"timestamps": {
"created": "2025-08-28T09:50:57.611559+03:00",
"deleted": "2100-01-01T00:00:00+03:00",
"started": null,
"updated": "2025-09-10T10:14:58.475499+03:00"
}
}
]
}

Создать кампанию
/adv/v2/seacat/save-ad


post
https://advert-api.wildberries.ru/adv/v2/seacat/save-ad
Описание метода
Метод создаёт кампанию:

с ручной ставкой для продвижения товаров в поиске и/или рекомендациях
с единой ставкой для продвижения товаров одновременно в поиске и рекомендациях
Лимит запросов на один аккаунт продавца:
Период	Лимит	Интервал	Всплеск
1 мин	5 запросов	12 сек	5 запросов
Authorizations:
HeaderApiKey
Request Body schema: application/json
name	
string
Название кампании

nms	
Array of integers
Карточки товаров для кампании. Доступные карточки товаров можно получить с помощью метода Карточки товаров для кампаний. Максимум 50 товаров (nm)

bid_type	
string
Default: "manual"
Enum: "manual" "unified"
Тип ставки:

manual — ручная
unified — единая
payment_type	
string
Default: "cpm"
Enum: "cpm" "cpc"
Тип оплаты:

cpm — за показы
cpc — за клик. При создании с этим типом оплаты в кампании автоматически устанавливается минимальная ставка
placement_types	
Array of strings
Default: ["search"]
Items Enum: "search" "recommendations"
Места размещения:

search — в поиске
recommendations — в рекомендациях
Укажите только для кампании с ручной ставкой

Примеры запроса
Payload
Content type
application/json

Копировать
Свернуть все
{
"name": "Телефоны",
"nms": [
146168367,
200425104
],
"bid_type": "manual",
"placement_types": [
"search",
"recommendations"
]
}
Примеры ответа
200
400
401
429
Content type
application/json

Копировать
1234567



Минимальные ставки для карточек товаров
/api/advert/v1/bids/min


post
https://advert-api.wildberries.ru/api/advert/v1/bids/min
Описание метода
Метод возвращает минимальные ставки для карточек товаров в копейках по типу оплаты и местам размещения.

Лимит запросов на один аккаунт продавца:
Период	Лимит	Интервал	Всплеск
1 мин	20 запросов	3 сек	5 запросов
Authorizations:
HeaderApiKey
Request Body schema: application/json
required
advert_id
required
integer <int64>
ID кампании

nm_ids
required
Array of integers <int64> [ 1 .. 100 ] characters [ items <int64 > ]
Список артикулов WB

payment_type
required
string
Enum: "cpm" "cpc"
Тип оплаты: - cpm — за показы - cpc — за клик

placement_types
required
Array of strings
Items Enum: "combined" "search" "recommendation"
Места размещения:

search — поиск
recommendation — рекомендации
combined — поиск и рекомендации

{
  "bids": [
    {
      "bids": [
        {
          "type": "combined",
          "value": 155
        },
        {
          "type": "search",
          "value": 250
        },
        {
          "type": "recommendation",
          "value": 250
        }
      ],
      "nm_id": 12345678
    },
    {
      "bids": [
        {
          "type": "combined",
          "value": 155
        },
        {
          "type": "search",
          "value": 250
        },
        {
          "type": "recommendation",
          "value": 250
        }
      ],
      "nm_id": 87654321
    }
  ]
}


Запуск кампании
/adv/v0/start


get
https://advert-api.wildberries.ru/adv/v0/start
Описание метода
Метод запускает кампании в статусах 4 — готово к запуску — или 11 — пауза. Чтобы запустить кампанию, проверьте ее бюджет. Если бюджета недостаточно, пополните его.

Лимит запросов на один аккаунт продавца:
Период	Лимит	Интервал	Всплеск
1 сек	5 запросов	200 мс	5 запросов
Authorizations:
HeaderApiKey
query Parameters
id
required
integer
Example: id=1234
ID кампании

Ответы

200
Успешно


400
Неправильный запрос


401
Не авторизован


422
Статус не изменен


429
Слишком много запросов

Примеры ответа
400
401
422
429
Content type
application/json
Example

IncorrectId
IncorrectId
Некорректный ID кампании


Копировать
Пауза кампании
/adv/v0/pause


get
https://advert-api.wildberries.ru/adv/v0/pause
Описание метода
Метод ставит кампании в статусе 9 — активна — на паузу.

Лимит запросов на один аккаунт продавца:
Период	Лимит	Интервал	Всплеск
1 сек	5 запросов	200 мс	5 запросов
Authorizations:
HeaderApiKey
query Parameters
id
required
integer
Example: id=1234
ID кампании

Ответы

200
Успешно


400
Неправильный запрос


401
Не авторизован


422
Статус не изменен


429
Слишком много запросов

Примеры ответа
400
401
422
429
Content type
application/json
Example

IncorrectId
IncorrectId
Некорректный ID кампании


Копировать

Завершение кампании
/adv/v0/stop


get
https://advert-api.wildberries.ru/adv/v0/stop
Описание метода
Метод завершает кампании в статусах:

4 — готово к запуску
9 — активна
11 — пауза
Лимит запросов на один аккаунт продавца:
Период	Лимит	Интервал	Всплеск
1 сек	5 запросов	200 мс	5 запросов
Authorizations:
HeaderApiKey
query Parameters
id
required
integer
Example: id=1234
ID кампании

Ответы

200
Успешно


400
Неправильный запрос


401
Не авторизован


422
Статус не изменен


429
Слишком много запросов

Примеры ответа
400
401
422
429
Content type
application/json
Example

IncorrectId
IncorrectId
Некорректный ID кампании


Копировать
{
"error": "Invalid Advert: invalid advert"
}

Минимальные ставки для карточек товаров
/api/advert/v1/bids/min


post
https://advert-api.wildberries.ru/api/advert/v1/bids/min
Описание метода
Метод возвращает минимальные ставки для карточек товаров в копейках по типу оплаты и местам размещения.

Лимит запросов на один аккаунт продавца:
Период	Лимит	Интервал	Всплеск
1 мин	20 запросов	3 сек	5 запросов
Authorizations:
HeaderApiKey
Request Body schema: application/json
required
advert_id
required
integer <int64>
ID кампании

nm_ids
required
Array of integers <int64> [ 1 .. 100 ] characters [ items <int64 > ]
Список артикулов WB

payment_type
required
string
Enum: "cpm" "cpc"
Тип оплаты: - cpm — за показы - cpc — за клик

placement_types
required
Array of strings
Items Enum: "combined" "search" "recommendation"
Места размещения:

search — поиск
recommendation — рекомендации
combined — поиск и рекомендации

{
  "advert_id": 98765432,
  "nm_ids": [
    12345678,
    87654321
  ],
  "payment_type": "cpm",
  "placement_types": [
    "combined",
    "search",
    "recommendation"
  ]
}

{
  "bids": [
    {
      "bids": [
        {
          "type": "combined",
          "value": 155
        },
        {
          "type": "search",
          "value": 250
        },
        {
          "type": "recommendation",
          "value": 250
        }
      ],
      "nm_id": 12345678
    },
    {
      "bids": [
        {
          "type": "combined",
          "value": 155
        },
        {
          "type": "search",
          "value": 250
        },
        {
          "type": "recommendation",
          "value": 250
        }
      ],
      "nm_id": 87654321
    }
  ]
}Изменение ставок в кампаниях
/api/advert/v1/bids


patch
https://advert-api.wildberries.ru/api/advert/v1/bids
Описание метода
Метод меняет ставки карточек товаров по артикулам WB в кампаниях:

с единой ставкой
с ручной ставкой
с моделью оплаты cpc — за клики
Для кампаний в статусах 4, 9 и 11.

В запросе укажите место размещения в параметре placement:

combined — в поиске и рекомендациях для кампаний с единой ставкой
search или recommendations — в поиске или рекомендациях для кампаний с ручной ставкой
Лимит запросов на один аккаунт продавца:
Период	Лимит	Интервал	Всплеск
1 сек	5 запросов	200 мс	5 запросов
Authorizations:
HeaderApiKey
Request Body schema: application/json
required
bids
required
Array of objects <= 50 items
Ставки в кампаниях

Array (<= 50 items)
advert_id
required
integer <int64>
ID кампании

nm_bids
required
Array of objects <= 50 items
Ставки, копейки

{
  "bids": [
    {
      "advert_id": 12345,
      "nm_bids": [
        {
          "nm_id": 13335157,
          "bid_kopecks": 250,
          "placement": "recommendations"
        }
      ]
    }
  ]
}

{
  "bids": [
    {
      "advert_id": 12345,
      "nm_bids": [
        {
          "nm_id": 13335157,
          "bid_kopecks": 250,
          "placement": "recommendations"
        }
      ]
    }
  ]
}

Изменение списка карточек товаров в кампаниях
/adv/v0/auction/nms


patch
https://advert-api.wildberries.ru/adv/v0/auction/nms
Описание метода
Метод добавляет и удаляет карточки товаров в кампаниях.

Для кампаний в статусах 4, 9 и 11.

Для добавляемых товаров устанавливается текущая минимальная ставка.

Лимит запросов на один аккаунт продавца:
Период	Лимит	Интервал	Всплеск
1 сек	1 запрос	1 сек	1 запрос
Authorizations:
HeaderApiKey
Request Body schema: application/json
required
nms
required
Array of objects <= 20 items
Карточки товаров в кампаниях

Array (<= 20 items)
advert_id
required
integer <int64>
ID кампании

nms
required
object
Карточки товаров. Максимум 50 товаров для одной кампании
Список ставок поисковых кластеров
/adv/v0/normquery/get-bids


post
https://advert-api.wildberries.ru/adv/v0/normquery/get-bids
Описание метода
Метод возвращает список поисковых кластеров со ставками по:

ID кампаний
артикулам WB
Лимит запросов на один аккаунт продавца:
Период	Лимит	Интервал	Всплеск
1 сек	5 запросов	200 мс	10 запросов
Authorizations:
HeaderApiKey
Request Body schema: application/json
required
items
required
Array of objects (V0GetNormQueryBidsRequestItem) <= 100 items
Array (<= 100 items)
advert_id
required
integer
ID кампании

nm_id
required
integer
Артикул WB

Установить ставки для поисковых кластеров
/adv/v0/normquery/bids


post
https://advert-api.wildberries.ru/adv/v0/normquery/bids
Описание метода
Метод устанавливает ставки на поисковые кластеры.
Можно использовать только для кампаний с:

ручной ставкой
моделью оплаты cpm — за показы
Лимит запросов на один аккаунт продавца:
Период	Лимит	Интервал	Всплеск
1 сек	2 запроса	500 мс	4 запроса
Authorizations:
HeaderApiKey
Request Body schema: application/json
required
bids
required
Array of objects (V0SetNormQueryBidsRequestItem) <= 100 items
Array (<= 100 items)
advert_id
required
integer
ID кампании

nm_id
required
integer
Артикул WB

norm_query
required
string
Поисковый кластер

bid
required
integer
Ставка за тысячу показов, ₽

