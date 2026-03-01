import os
import random
import requests


QUOTES = [
    "A home is not a place — it's a feeling.",
    "Great communities are built one act of care at a time.",
    "Your neighbourhood is only as strong as its people.",
    "Start where you are. Use what you have. Do what you can.",
    "Small daily improvements lead to stunning long-term results.",
    "The strength of a community lies in its people helping each other.",
    "Every problem is a gift — without them we wouldn't grow.",
]

MOCK = {
    'temperature': 22,
    'feels_like': 20,
    'description': 'Partly Cloudy',
    'icon': '02d',
    'city': 'Johannesburg',
    'humidity': 55,
    'wind': 12,
    'offline': True,
}


def get_weather(city: str = None) -> dict:
    city = city or os.getenv('WEATHER_CITY', 'Johannesburg')
    api_key = os.getenv('WEATHER_API_KEY', '')

    if not api_key:
        data = dict(MOCK)
        data['city'] = city
        return data

    try:
        url = (
            f'https://api.openweathermap.org/data/2.5/weather'
            f'?q={city}&appid={api_key}&units=metric'
        )
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        j = resp.json()
        return {
            'temperature': round(j['main']['temp']),
            'feels_like':  round(j['main']['feels_like']),
            'description': j['weather'][0]['description'].title(),
            'icon':        j['weather'][0]['icon'],
            'city':        j['name'],
            'humidity':    j['main']['humidity'],
            'wind':        round(j['wind']['speed']),
            'offline':     False,
        }
    except Exception:
        data = dict(MOCK)
        data['city'] = city
        return data


def get_quote() -> str:
    return random.choice(QUOTES)


# Map OWM icon codes to Font Awesome icons + colours
ICON_MAP = {
    '01': ('fa-sun',            '#fbbf24'),   # clear sky
    '02': ('fa-cloud-sun',      '#94a3b8'),   # few clouds
    '03': ('fa-cloud',          '#94a3b8'),   # scattered clouds
    '04': ('fa-clouds',         '#64748b'),   # broken clouds
    '09': ('fa-cloud-drizzle',  '#60a5fa'),   # shower rain
    '10': ('fa-cloud-rain',     '#60a5fa'),   # rain
    '11': ('fa-bolt',           '#fbbf24'),   # thunderstorm
    '13': ('fa-snowflake',      '#bfdbfe'),   # snow
    '50': ('fa-smog',           '#94a3b8'),   # mist
}


def weather_fa(icon_code: str):
    prefix = icon_code[:2] if icon_code else '02'
    return ICON_MAP.get(prefix, ('fa-cloud-sun', '#94a3b8'))
