#!/usr/bin/env python3

import argparse
import json
import sqlite3
import os
import sys
import html
import webbrowser
from datetime import datetime, timedelta
from itertools import groupby
from operator import itemgetter
from urllib.parse import quote

try:
    from zoneinfo import ZoneInfo
except ImportError:
    print("Error: 'zoneinfo' module not found.", file=sys.stderr)
    print("If you are using Python < 3.9, you may need to install the backport:", file=sys.stderr)
    print("pip install tzdata", file=sys.stderr)
    sys.exit(1)


def convert_json_to_sqlite(json_file_path):
    """
    Converts a JSON chat log to a SQLite database, correctly identifying sender names
    and prompting for overwrite if the database already exists.
    """
    db_file_path = os.path.splitext(json_file_path)[0] + '.db'

    if os.path.exists(db_file_path):
        response = input(f"Database file '{db_file_path}' already exists. Overwrite? (y/N): ").lower().strip()
        if response != 'y':
            print("Conversion cancelled by user.")
            sys.exit(0)
        try:
            os.remove(db_file_path)
            print(f"Overwriting existing database...")
        except OSError as e:
            print(f"Error: Could not remove existing database file: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        print(f"Loading JSON file: {json_file_path}...")
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print("JSON file loaded successfully.")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading JSON file: {e}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_file_path)
    cursor = conn.cursor()
    print(f"Creating database: {db_file_path}")

    cursor.execute("PRAGMA encoding = 'UTF-8';")
    cursor.execute('''
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, contact_name TEXT NOT NULL,
            timestamp TEXT NOT NULL, message_date TEXT NOT NULL, from_me BOOLEAN NOT NULL,
            sender_name TEXT NOT NULL, text TEXT NOT NULL )
    ''')
    cursor.execute('CREATE INDEX idx_message_date ON messages (message_date)')

    central_tz = ZoneInfo("America/Chicago")
    message_count = 0
    for chat in data.get('chats', []):
        contact_name = chat.get('contactName')
        if not contact_name: continue
        is_group_chat = chat.get('key', '').endswith('@g.us')
        for message in chat.get('messages', []):
            if message.get('type') == 'text' and 'text' in message:
                try:
                    timestamp_str = message['timestamp']
                    utc_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    central_dt = utc_dt.astimezone(central_tz)
                    message_date = central_dt.strftime('%Y-%m-%d')
                    from_me = message.get('fromMe', False)
                    
                    sender_name = 'Me' if from_me else (message.get('remoteResourceDisplayName') if is_group_chat else contact_name)
                    if not from_me and sender_name:
                        if '@s.whatsapp.net' in sender_name: sender_name = 'Them'
                        elif ' ' in sender_name: sender_name = sender_name.split(' ', 1)[0]
                    elif not sender_name:
                        sender_name = 'Unknown Sender'

                    cursor.execute(
                        'INSERT INTO messages (contact_name, timestamp, message_date, from_me, sender_name, text) VALUES (?, ?, ?, ?, ?, ?)',
                        (contact_name, timestamp_str, message_date, from_me, sender_name, message['text'])
                    )
                    message_count += 1
                except (KeyError, TypeError) as e:
                    print(f"Skipping a message due to missing data: {e}", file=sys.stderr)

    conn.commit()
    conn.close()
    print(f"\nConversion complete. Inserted {message_count} messages into '{db_file_path}'.")


def format_messages_for_display(messages, tz_info):
    """Formats a list of messages for HTML display."""
    formatted = []
    for msg in messages:
        utc_time = datetime.fromisoformat(msg['timestamp'].replace('Z', '+00:00'))
        local_time = utc_time.astimezone(tz_info)
        time_str = local_time.strftime('%I:%M %p').lstrip('0')
        
        safe_text = html.escape(msg['text']).replace('\n', '<br>')
        
        formatted.append({
            'from_me': msg['from_me'],
            'text': safe_text,
            'time_str': time_str
        })
    return formatted


def search_chats_by_date(db_file_path, search_date_str):
    if not os.path.exists(db_file_path):
        print(f"Error: Database file '{db_file_path}' not found.", file=sys.stderr)
        sys.exit(1)

    try:
        search_date_obj = datetime.strptime(search_date_str, '%Y-%m-%d')
    except ValueError:
        print("Error: Invalid date format. Please use YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)
    
    prev_date_obj = search_date_obj - timedelta(days=1)
    next_date_obj = search_date_obj + timedelta(days=1)
    prev_date_str = prev_date_obj.strftime('%Y-%m-%d')
    next_date_str = next_date_obj.strftime('%Y-%m-%d')

    conn = sqlite3.connect(db_file_path)
    conn.row_factory = sqlite3.Row
    
    query = "SELECT * FROM messages WHERE message_date IN (?, ?, ?) ORDER BY contact_name, timestamp"
    all_results = conn.execute(query, (prev_date_str, search_date_str, next_date_str)).fetchall()
    conn.close()

    if not any(r['message_date'] == search_date_str for r in all_results):
        print(f"No messages found for {search_date_str}")
        return

    all_conversations = {}
    for r in all_results:
        contact = r['contact_name']
        msg_date = r['message_date']
        if contact not in all_conversations:
            all_conversations[contact] = {'prev': [], 'current': [], 'next': [], 'first_current_timestamp': None}
        
        if msg_date == prev_date_str: all_conversations[contact]['prev'].append(dict(r))
        elif msg_date == search_date_str:
            all_conversations[contact]['current'].append(dict(r))
            if not all_conversations[contact]['first_current_timestamp']:
                all_conversations[contact]['first_current_timestamp'] = r['timestamp']
        elif msg_date == next_date_str: all_conversations[contact]['next'].append(dict(r))
    
    conversations_to_render = [
        {'contact_name': name, **data} for name, data in all_conversations.items() if data['current']
    ]
    conversations_to_render.sort(key=lambda x: x['first_current_timestamp'])

    central_tz = ZoneInfo("America/Chicago")
    for conv in conversations_to_render:
        conv['prev_messages'] = format_messages_for_display(conv['prev'], central_tz)
        conv['current_messages'] = format_messages_for_display(conv['current'], central_tz)
        conv['next_messages'] = format_messages_for_display(conv['next'], central_tz)
        conv['slug'] = quote(conv['contact_name'])

    output_filename = f"{os.path.splitext(os.path.basename(db_file_path))[0]}_{search_date_str}.html"
    human_readable_date = search_date_obj.strftime('%B %d, %Y')
    
    html_template = """
    <!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Roboto:400,600">
    <title>Chat Logs for {human_readable_date}</title><style>
    html,body{{font-family:"Roboto",sans-serif;margin:0;padding:0;background-color:#f0f0f0}}h1,h2{{color:#333;text-align:center;margin:20px 0}}.conversation_group{{background:#efe7dd url("https://cloud.githubusercontent.com/assets/398893/15136779/4e765036-1639-11e6-9201-67e728e86f39.jpg") repeat;padding:10px 20px;margin:20px auto;max-width:800px;border:1px solid #ccc;box-shadow:0 2px 5px rgba(0,0,0,.1);border-radius:8px}}.conversation_group h2{{color:#075e54;border-bottom:2px solid #128c7e;padding-bottom:10px;display:flex;justify-content:space-between;align-items:center}}.conversation-container{{overflow-x:hidden;padding:0 16px}}.conversation-container::after{{content:"";display:table;clear:both}}.message{{color:#000;clear:both;line-height:18px;font-size:15px;padding:8px;position:relative;margin:8px 0;max-width:85%;word-wrap:break-word;box-shadow:0 1px 1px rgba(0,0,0,.1)}}.message::after{{position:absolute;content:"";width:0;height:0;border-style:solid}}.metadata{{display:inline-block;float:right;padding:0 0 0 7px;position:relative;bottom:-4px}}.metadata .time{{color:rgba(0,0,0,.45);font-size:11px;display:inline-block}}.message.received{{background:#fff;border-radius:0 5px 5px 5px;float:left}}.message.received::after{{border-width:0 10px 10px 0;border-color:transparent #fff transparent transparent;top:0;left:-10px}}.message.sent{{background:#e1ffc7;border-radius:5px 0 5px 5px;float:right}}.message.sent::after{{border-width:0 0 10px 10px;border-color:transparent transparent transparent #e1ffc7;top:0;right:-10px}}.day-loader{{font-size:20px;font-weight:700;text-decoration:none;color:#075e54;cursor:pointer;padding:0 10px;user-select:none}}.day-loader:hover{{color:#128c7e}}.invisible{{visibility:hidden}}.collapsed{{display:none}}
    </style></head><body><h1>Chat Logs for {human_readable_date}</h1>{conversations_html}
    <script>
    document.addEventListener('click', function(e) {{
        if (e.target.matches('.day-loader')) {{
            const targetId = e.target.getAttribute('data-target');
            const targetEl = document.getElementById(targetId);
            if (targetEl) {{
                targetEl.classList.remove('collapsed');
                e.target.classList.add('invisible');
            }}
        }}
    }});
    </script></body></html>"""

    message_template = "<div class='message {css_class}'>{text}<span class='metadata'><span class='time'>{time_str}</span></span></div>"
    
    conversations_html = []
    for conv in conversations_to_render:
        prev_html = "".join([message_template.format(css_class='sent' if m['from_me'] else 'received', **m) for m in conv['prev_messages']])
        curr_html = "".join([message_template.format(css_class='sent' if m['from_me'] else 'received', **m) for m in conv['current_messages']])
        next_html = "".join([message_template.format(css_class='sent' if m['from_me'] else 'received', **m) for m in conv['next_messages']])
        
        prev_id = f"prev-{conv['slug']}"
        next_id = f"next-{conv['slug']}"

        conv_html = f"""
        <div class="conversation_group">
            <h2>
                <span class="day-loader {'invisible' if not prev_html else ''}" data-target="{prev_id}">«</span>
                {html.escape(conv['contact_name'])}
                <span class="day-loader {'invisible' if not next_html else ''}" data-target="{next_id}">»</span>
            </h2>
            <div class="conversation-container">
                <div id="{prev_id}" class="collapsed">{prev_html}</div>
                {curr_html}
                <div id="{next_id}" class="collapsed">{next_html}</div>
            </div>
        </div>"""
        conversations_html.append(conv_html)

    final_html = html_template.format(
        human_readable_date=human_readable_date, 
        conversations_html="".join(conversations_html)
    )

    try:
        with open(output_filename, 'w', encoding='utf-8') as f: f.write(final_html)
        print(f"Successfully wrote chat log to '{output_filename}'")
        webbrowser.open_new_tab(f"file://{os.path.realpath(output_filename)}")
    except IOError as e:
        print(f"Error writing to file '{output_filename}': {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="A tool to convert and search WhatsApp chat logs.",
        epilog="Examples:\n  wasearch.py --convert ChatLog.json\n  wasearch.py ChatLog.db 2025-01-30",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '-c', '--convert', dest='json_file', metavar='ChatLog.json',
        help='Convert the specified JSON file to a SQLite DB.'
    )
    parser.add_argument('db_file', nargs='?', help='The database file to search.')
    parser.add_argument('search_date', nargs='?', help='The date to search for (YYYY-MM-DD).')
    args = parser.parse_args()

    if args.json_file:
        convert_json_to_sqlite(args.json_file)
    elif args.db_file and args.search_date:
        search_chats_by_date(args.db_file, args.search_date)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
