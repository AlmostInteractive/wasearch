# WhatsApp Chat Search by Date

## What's this do?
It will show you all chat messages that took place on a particular date.  Very useful for many situations, such as "What did I do on Feb 2, 2024? Let me check."  And many many other situations.  Probably.

## Instructions

1)  Get an Android phone with Android v13 or below
2)  Go to https://github.com/KnugiHK/WhatsApp-Key-DB-Extractor and run this tool to extract the database from your phone.  Don't worry if the Java part doesn't work, you just need the decrypted .db file
3)  Go to https://github.com/andreas-mausch/whatsapp-viewer and get the WhatsApp Viewer app.  Load the decrypted files and then export all the chats to a JSON file (eg: chats.json).
4)  Download the ZIP from this repo and extract it to a file.  Move the chats.json file to this folder.
5)  Run `python wasearch.py -c chats.json` to create a new database, `chats.db`
6)  Run `python wasearch.py chats.json YYYY-MM-DD` (Y = year, M = month, D = day) to extract all the chats from that day, create a pretty HTML file, and open it in your default browser.
