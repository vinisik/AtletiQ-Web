import json
import os
from django.conf import settings

def escudos_times(request):
    json_path = os.path.join(settings.BASE_DIR, 'escudos.json')
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            escudos = json.load(f)
    except FileNotFoundError:
        escudos = {}
    return {'ESCUDOS': escudos}