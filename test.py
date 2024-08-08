import requests

try:
    response = requests.get('https://youtube.com')
    print("Connection successful:", response.status_code)
except requests.RequestException as e:
    print("Connection failed:", e)
