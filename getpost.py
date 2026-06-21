import argparse
import requests
import sys
import json

def parse_args():
    parser = argparse.ArgumentParser(description='Console HTTP client (GET/POST)')
    parser.add_argument('method', choices=['GET', 'POST'], help='HTTP method')
    parser.add_argument('url', help='Request URL')
    parser.add_argument('--params', nargs='*', help='Query parameters (key=value)', default=[])
    parser.add_argument('--data', help='Request body (for POST)')
    parser.add_argument('--headers', nargs='*', help='Headers (Key:Value)', default=[])
    return parser.parse_args()

def parse_key_value_list(items):
    result = {}
    for item in items:
        if '=' in item:
            k, v = item.split('=', 1)
            result[k] = v
        elif ':' in item:
            k, v = item.split(':', 1)
            result[k.strip()] = v.strip()
    return result

def main():
    args = parse_args()
    params = parse_key_value_list(args.params)
    headers = parse_key_value_list(args.headers)
    data = args.data
    if data:
        try:
            data = json.loads(data)
        except Exception:
            pass
    try:
        if args.method == 'GET':
            resp = requests.get(args.url, params=params, headers=headers)
        else:
            resp = requests.post(args.url, params=params, headers=headers, json=data if isinstance(data, dict) else None, data=None if isinstance(data, dict) else data)
        print(f'Status: {resp.status_code}')
        print('Headers:')
        for k, v in resp.headers.items():
            print(f'  {k}: {v}')
        print('Body:')
        print(resp.text)
    except Exception as e:
        print(f'Error: {e}', file=sys.stderr)

if __name__ == '__main__':
    main()