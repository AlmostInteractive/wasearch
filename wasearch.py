#!/usr/bin/env python3

import argparse
import json
import sqlite3
import os
import sys
import html
import webbrowser
from datetime import datetime
from itertools import groupby
from operator import itemgetter

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

    Args:
        json_file_path (str): The path to the input JSON file.
    """
    db_file_path = os.path.splitext(json_file_path)[0] + '.db'

    if os.path.exists(db_file_path):
        response = input(f"Database file '{db_file_path}' already exists. Overwrite? (y/N): ").lower().strip()
        if response == 'y':
            print(f"Overwriting existing database...")
            try:
                os.remove(db_file_path)
            except OSError as e:
                print(f"Error: Could not remove existing database file: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            print("Conversion cancelled by user.")
            sys.exit(0)

    try:
        print(f"Loading JSON file: {json_file_path}...")
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print("JSON file loaded successfully.")
    except FileNotFoundError:
        print(f"Error: The file '{json_file_path}' was not found.", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from the file '{json_file_path}'.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_file_path)
    cursor = conn.cursor()
    print(f"Creating database: {db_file_path}")

    cursor.execute("PRAGMA encoding = 'UTF-8';")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_name TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            message_date TEXT NOT NULL,
            from_me BOOLEAN NOT NULL,
            sender_name TEXT NOT NULL,
            text TEXT NOT NULL
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_message_date ON messages (message_date)')

    central_tz = ZoneInfo("America/Chicago")
    message_count = 0

    for chat in data.get('chats', []):
        contact_name = chat.get('contactName')
        if not contact_name:
            continue
        
        is_group_chat = chat.get('key', '').endswith('@g.us')

        for message in chat.get('messages', []):
            if message.get('type') == 'text' and 'text' in message:
                try:
                    timestamp_str = message['timestamp']
                    from_me = message.get('fromMe', False)

                    utc_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    central_dt = utc_dt.astimezone(central_tz)
                    message_date = central_dt.strftime('%Y-%m-%d')
                    
                    if from_me:
                        sender_name = 'Me'
                    else:
                        if is_group_chat:
                            display_name = message.get('remoteResourceDisplayName')
                        else:
                            display_name = contact_name

                        if display_name:
                            if '@s.whatsapp.net' in display_name:
                                sender_name = 'Them'
                            elif ' ' in display_name:
                                sender_name = display_name.split(' ', 1)[0]
                            else:
                                sender_name = display_name
                        else:
                            sender_name = 'Unknown Sender'

                    message_data = (
                        contact_name,
                        timestamp_str,
                        message_date,
                        from_me,
                        sender_name,
                        message['text']
                    )
                    
                    cursor.execute('''
                        INSERT INTO messages (contact_name, timestamp, message_date, from_me, sender_name, text)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', message_data)
                    message_count += 1
                except (KeyError, TypeError) as e:
                    print(f"Skipping a message due to missing data: {e}", file=sys.stderr)

    conn.commit()
    conn.close()

    print(f"\nConversion complete.")
    print(f"Successfully inserted {message_count} text messages into '{db_file_path}'.")


def search_chats_by_date(db_file_path, search_date):
    """
    Searches chats on a specific date, writes them to a styled HTML file,
    and opens it in the default web browser.

    Args:
        db_file_path (str): The path to the SQLite database file.
        search_date (str): The date to search for in 'YYYY-MM-DD' format.
    """
    if not os.path.exists(db_file_path):
        print(f"Error: Database file '{db_file_path}' not found.", file=sys.stderr)
        sys.exit(1)

    try:
        date_obj = datetime.strptime(search_date, '%Y-%m-%d')
    except ValueError:
        print("Error: Invalid date format. Please use YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)
        
    base_name = os.path.splitext(os.path.basename(db_file_path))[0]
    output_filename = f"{base_name}_{search_date}.html"

    conn = sqlite3.connect(db_file_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        "SELECT contact_name, from_me, timestamp, sender_name, text FROM messages WHERE message_date = ? ORDER BY contact_name, timestamp",
        (search_date,)
    )
    results = cursor.fetchall()
    conn.close()

    if not results:
        print(f"No messages found for {search_date}")
        return

    conversations_to_render = []
    for contact_name, messages_iterator in groupby(results, key=itemgetter('contact_name')):
        messages = list(messages_iterator)
        first_timestamp = messages[0]['timestamp']
        conversations_to_render.append({
            'contact_name': contact_name,
            'messages': messages,
            'first_timestamp': first_timestamp
        })
    
    conversations_to_render.sort(key=itemgetter('first_timestamp'))

    css_styles = """
    html, body {
        font-family: "Roboto", sans-serif;
        margin: 0;
        padding: 0;
        background-color: #f0f0f0;
    }
    h1, h2 {
        color: #333;
        text-align: center;
        margin: 20px 0;
    }
    .conversation_group {
        background: #efe7dd url("https://cloud.githubusercontent.com/assets/398893/15136779/4e765036-1639-11e6-9201-67e728e86f39.jpg") repeat;
        padding: 10px 20px 20px 20px;
        margin: 20px auto;
        max-width: 800px;
        border: 1px solid #ccc;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        border-radius: 8px;
    }
    .conversation_group h2 {
        color: #075e54;
        border-bottom: 2px solid #128c7e;
        padding-bottom: 10px;
    }
    .conversation-container {
        overflow-x: hidden;
        padding: 0 16px;
    }
    .conversation-container::after {
        content: "";
        display: table;
        clear: both;
    }
    .message {
        color: #000;
        clear: both;
        line-height: 18px;
        font-size: 15px;
        padding: 8px;
        position: relative;
        margin: 8px 0;
        max-width: 85%;
        word-wrap: break-word;
        box-shadow: 0 1px 1px rgba(0,0,0,0.1);
    }
    .message::after {
        position: absolute;
        content: "";
        width: 0;
        height: 0;
        border-style: solid;
    }
    .metadata {
        display: inline-block;
        float: right;
        padding: 0 0 0 7px;
        position: relative;
        bottom: -4px;
    }
    .metadata .time {
        color: rgba(0, 0, 0, .45);
        font-size: 11px;
        display: inline-block;
    }
    .message.received {
        background: #fff;
        border-radius: 0px 5px 5px 5px;
        float: left;
    }
    .message.received::after {
        border-width: 0px 10px 10px 0;
        border-color: transparent #fff transparent transparent;
        top: 0;
        left: -10px;
    }
    .message.sent {
        background: #e1ffc7;
        border-radius: 5px 0px 5px 5px;
        float: right;
    }
    .message.sent::after {
        border-width: 0px 0 10px 10px;
        border-color: transparent transparent transparent #e1ffc7;
        top: 0;
        right: -10px;
    }
    """

    # Create the human-readable date string for display
    human_readable_date = date_obj.strftime('%B %d, %Y')

    html_parts = [
        '<!DOCTYPE html>', '<html lang="en">', '<head>',
        '  <meta charset="UTF-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">',
        '  <link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Roboto:400,600">',
        f'  <title>Chat Logs for {human_readable_date}</title>',
        f'  <style>{css_styles}</style>',
        '</head>', '<body>',
        f'<h1>Chat Logs for {human_readable_date}</h1>'
    ]
    
    central_tz = ZoneInfo("America/Chicago")

    for conversation in conversations_to_render:
        contact_name = conversation['contact_name']
        messages = conversation['messages']

        html_parts.append('<div class="conversation_group">')
        safe_contact_name = html.escape(contact_name)
        html_parts.append(f'  <h2>{safe_contact_name}</h2>')
        html_parts.append('  <div class="conversation-container">')
        
        for message in messages:
            utc_time = datetime.fromisoformat(message['timestamp'].replace('Z', '+00:00'))
            central_time = utc_time.astimezone(central_tz)
            time_str = central_time.strftime('%I:%M %p').lstrip('0') # e.g., 9:30 PM
            
            safe_text = html.escape(message['text']).replace('\n', '<br>')
            message_class = 'sent' if message['from_me'] else 'received'
            
            html_parts.append(f'    <div class="message {message_class}">')
            html_parts.append(f'      {safe_text}')
            html_parts.append(f'      <span class="metadata"><span class="time">{time_str}</span></span>')
            html_parts.append('    </div>')

        html_parts.append('  </div>')
        html_parts.append('</div>')

    html_parts.extend(['</body>', '</html>'])
    
    final_html = "\n".join(html_parts)
    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write(final_html)
        print(f"Successfully wrote chat log to '{output_filename}'")
        
        webbrowser.open_new_tab(f"file://{os.path.realpath(output_filename)}")
        print("Opening report in your default browser...")

    except IOError as e:
        print(f"Error: Could not write to file '{output_filename}': {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Could not open browser: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="A tool to convert and search WhatsApp chat logs.",
        epilog="Examples:\n"
               "  wasearch.py --convert ChatLog.json\n"
               "  wasearch.py ChatLog.db 2025-01-30",
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
